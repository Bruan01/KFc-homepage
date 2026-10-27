/*
 * KFlow 桌面终端 · ESP32-S3 固件 v0.5.0
 *
 * 首屏是小 K 的立绘：点一下（触摸）或按一下 BOOT 才进入数据页。
 * 数据页静置一段时间会自动回到首屏，像屏保一样。
 *
 * 流程：上电 → 画首屏 → 连 WiFi → 有令牌就点按进入；没令牌先走配对码。
 * 交互：首屏点按/短按进入。
 *       数据页分三段（校准后才生效）：上带签到、中带翻页、下带刷新；
 *       BOOT 短按固定回小 K，长按 3 秒清除令牌。
 * 时间：服务端 epoch 对时（NTP 兜底），掉电后没网就显示 --:--，不编造。
 * 离线：摘要写进 NVS，断网/重启先显示上次的数据，页脚标注 cached/OFFLINE。
 * 中文：板子上的字库只有 ASCII，中文正文由服务端画成 1-bit 位图再传下来
 *       （/api/terminal/textboard），设备端不做排版也不存字库。
 *
 * 依赖库：TFT_eSPI（Bodmer）、ArduinoJson 7.x
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <TFT_eSPI.h>
#include <Preferences.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include <sys/time.h>

#include "config.h"
#include "xiaok_splash.h"
#include "xiaok_face.h"  // 眨眼用的眼睛局部帧，与 splash 同一张源图

#ifndef KFLOW_BASE
#error "缺少 config.h：先复制 config.example.h 并填入 WiFi 与服务地址"
#endif

// ---------------------------------------------------------------- 常量与状态

static const uint32_t WIFI_RETRY_MS = 15000;
static const uint32_t HTTP_TIMEOUT_MS = 8000;
static const uint32_t PAIR_POLL_MS = 3000;
static const int PIN_BUTTON = 0;  // BOOT 键，按下为 LOW
static const long LONG_PRESS_MS = 3000;
static const uint32_t TAP_DEBOUNCE_MS = 400;

// 首屏时钟的左上角（Font 2，"88:88" 宽 40px，右侧留 0px 也够）。
// drawSplash 排版和 loop 的 tickClock 都用这个常量，避免两处写死的坐标漂移。
static const int SPLASH_CLOCK_X = 188;

// 数据页分三段：上带签到、中带翻页、下带刷新。
// 两条分界线刻意和页面里本来就有的横线对齐（积分块下的 112、页脚上的 252），
// 屏幕上因此看得见边界——看不见的"分区"等于没有分区。
static const int ZONE_CHECKIN_END = 112;  // y < 112        -> 签到
static const int ZONE_NEXT_END = 252;     // 112 <= y < 252 -> 翻页；>= 252 -> 刷新

// 数据页一共五屏：0 概览 / 1 社区数据 / 2 碎碎念 / 3 最新帖子 / 4 通知
static const int PAGE_COUNT = 5;
static const int PAGE_MURMUR = 2;
static const int PAGE_TOPIC = 3;
static const int PAGE_NOTICE = 4;

// 主动提醒：新通知到达时自动亮起，20 秒后自己退回首屏。
// 20 秒是「抬头能看见」的下限——再短会错过，再长就变成抢屏。
static const uint32_t ATTENTION_MS = 20000;
// 这期间有过输入就算"人在看"，新通知只亮角标、不切页。
static const uint32_t ATTENTION_HOLD_OFF_MS = 30000;
// 首屏待机轮询。有未读时 60 秒问一次，没有就 5 分钟一次：
// 首屏是"没在看内容"的状态，但恰恰是它最该先知道有新东西。
static const uint32_t SPLASH_POLL_ALERT_MS = 60000;
static const uint32_t SPLASH_POLL_IDLE_MS = 300000;

// 文字板在位图模式下最多两块：碎碎念一块正文，帖子是标题+正文两块。
// 上限给足但不必精确——超出就整块丢弃，屏幕上少一块总比画歪好。
static const int BOARD_MAX_BLOCKS = 6;
static const int BOARD_HEADER_BYTES = 12;  // x,y,w,h,stride,color 各 2 字节
// 位图缓存多久算过期。比摘要刷新（300 秒）短：翻页是人的动作，
// 手上点一下却看到五分钟前的内容会很别扭。
static const uint32_t BOARD_TTL_MS = 90000;
// 单块位图上限。216x152 的 1bpp 约 4.1KB，留一倍余量足够。
static const size_t BOARD_MAX_BYTES = 16384;

enum ButtonEvent { BTN_NONE, BTN_SHORT, BTN_LONG };
enum ScreenMode { MODE_SPLASH, MODE_DATA, MODE_CALIBRATE, MODE_TOUCHTEST };

void logStatus();       // 前置声明：runPairing/fetchSummary 也会调用
bool touchRawPressed(); // 前置声明：logStatus 要报当前是否按着

#ifndef TOUCH_ENABLED
#define TOUCH_ENABLED 0
#endif
// 「按下去」这层不需要校准：只认压力，不认坐标。
#ifndef TOUCH_TAP_ENABLED
#define TOUCH_TAP_ENABLED 1
#endif
#ifndef TOUCH_Z_MIN
#define TOUCH_Z_MIN 150
#endif
#ifndef TOUCH_Z_MAX
#define TOUCH_Z_MAX 3950
#endif
// 连续多少次采样超阈值才算按下去。噪声是单点毛刺，手指按住会持续上百毫秒。
#ifndef TOUCH_TAP_STREAK
#define TOUCH_TAP_STREAK 2
#endif
#ifndef IDLE_TO_SPLASH_SECONDS
#define IDLE_TO_SPLASH_SECONDS 60
#endif

// 校准值不写死在编译期，而是存 NVS：开机读回，校准完立刻 setTouch 生效。
// 这样一次烧录就能反复校准，改一次不用重烧一次。
// 下面的 fallback 只在一次都没校准过时兜底，精度不可信，仅保证不崩。
// 真正要判断「有没有可用校准」看 g_calValid，不是看 TOUCH_ENABLED。
static const uint16_t TOUCH_CAL_FALLBACK[5] = {320, 3560, 340, 3620, 1};

// 校准窗口：10 秒够沿四边划一圈；20ms 采样一次，一圈约 500 个点。
static const uint32_t CAL_DURATION_MS = 10000;
static const uint32_t CAL_SAMPLE_MS = 20;
// 有效跨度下限。正常屏 raw 跨度在 2500~3800，只划三条边也远大于 800，
// 低于这个值说明基本没划，判定为失败。
static const uint16_t CAL_MIN_SPAN = 800;

// 串口诊断。USB CDC 在电脑打开串口前输出的内容会丢，所以除了上电横幅，
// 还支持「从串口发任意一个字符」立刻回一份状态报告，用来远程判断板子卡在哪一步。
#ifndef DEBUG_SERIAL
#define DEBUG_SERIAL 1
#endif

#if DEBUG_SERIAL
#define LOGF(...) Serial.printf(__VA_ARGS__)
#else
#define LOGF(...) \
  do {            \
  } while (0)
#endif

static const uint16_t C_INK = TFT_BLACK;
static const uint16_t C_PAPER = TFT_WHITE;
static const uint16_t C_MUTED = 0x8410;   // 中灰
static const uint16_t C_ACCENT = 0x0320;  // 深绿，仅用于强调线
static const uint16_t C_ALERT = 0xF800;   // 纯红，只给未读角标用

TFT_eSPI tft = TFT_eSPI();
Preferences prefs;

struct NotifItem {
  String label;
  String title;
  bool isRead = false;
};

struct Snapshot {
  bool valid = false;
  String username;
  String deviceName;
  String serverTime;
  String lastLabel;
  String lastTitle;
  int balance = 0;
  int unread = 0;
  int badges = 0;
  int streak = 0;
  int topics = 0;
  int replies = 0;
  int likes = 0;       // 收到的赞
  int activeDays = 0;  // 活跃天数
  int latestId = 0;    // 最新一条通知的 id，设备拿它当「水位线」判有没有新的
  NotifItem items[3];  // 最新三条：第 2 页一次列完，不用来回翻
  int itemCount = 0;
  // 签到状态不缓存：缓存是"上次看到的样子"，跨天就会撒谎。
  // 只有本次真的问过服务端（或真的签到过）才算知道。
  bool checkinDone = false;
  bool checkinKnown = false;
  int checkinReward = 0;
} snap;

String g_token;

// 服务地址是运行时的，不是编译期的。
//
// 之前写死成宏，结果 Mac 的 DHCP 租约一换（.71 → .87），设备照样连上 WiFi、
// 照样显示有网，但每个请求都打到一个没人应答的地址上，串口只留一句
// http=-1。查了半天才发现跟 WiFi 毫无关系。
//
// 现在：启动读 NVS，没有才退回宏；串口发 u 可以改，改完不用重烧。
char g_base[80] = KFLOW_BASE;
bool g_wifiOk = false;
// 「还没连上」和「连过了但失败」是两件事：前者不该在首屏写 no wifi，
// 否则开机那段关联时间会显示一个还没成立的结论。只有真失败才置这个标志。
bool g_wifiFailed = false;
uint32_t g_refreshSeconds = REFRESH_FALLBACK_SECONDS;
uint32_t g_nextSyncAt = 0;
bool g_offline = false;
String g_lastClockText;    // 上一帧画的时钟文本，变了才重绘
bool g_fromCache = false;  // 当前 snap 来自 NVS 缓存，而不是本次同步
uint32_t g_pairRetrySeconds = 5;  // 配对失败退避，避免把服务端限流刷爆
int g_page = 0;            // 数据页当前屏：0 概览 / 1 社区 / 2 碎碎念 / 3 帖子 / 4 通知
uint32_t g_lastInputAt = 0;  // 最后一次输入时间，用来算静置回首屏
bool g_touchSeen = false;    // 确认收到过一次真实触摸：首屏会亮一颗绿点

// 「上次见到的最新通知 id」，存 NVS。它和未读数不是一回事：
//   未读数来自服务端，红色角标跟着它走——读了才会消失；
//   水位线只在本地，用来判断"这一条我是不是第一次见"，决定要不要主动弹。
// 两个概念分开，屏幕就不会因为"看过但没读"而假装没有新东西。
uint32_t g_seenNoticeId = 0;
bool g_pendingNotice = false;   // 本次同步发现新通知，等渲染时消费
uint32_t g_attnUntil = 0;       // 主动提醒窗口的结束时刻
uint32_t g_nextSplashPoll = 0;  // 首屏待机轮询的下次时间

// 当前在哪个界面。声明放这里而不是"首屏/交互"那一节，是因为 OTA 那段
// （位置更靠前）要判断"现在能不能动屏幕"。
ScreenMode g_mode = MODE_SPLASH;

// 前置声明：OTA 升级失败后要重绘当前页面，而这两个函数定义在后面。
void renderPage();
void showSplash();

// 服务端画好的中文位图。放 PSRAM 而不是内部 RAM：5KB×2 在 8MB 里
// 九牛一毛，而内部 RAM 一旦被挤占，WiFi 缓冲区就会跟着缩水。
struct BoardCache {
  uint8_t *data = nullptr;
  size_t len = 0;
  uint32_t fetchedAt = 0;
  bool valid = false;
  bool failed = false;
};
// 0 = 碎碎念（/textboard?slot=murmur），1 = 最新帖子（slot=topic）
BoardCache g_boards[2];

// 触摸原始采样。与 TOUCH_ENABLED 无关，始终在跑：它只读 XPT2046 的裸值，
// 用来判断「线有没有接对」「要不要重新校准」，结果通过串口状态报告取回。
struct TouchProbe {
  uint32_t samples = 0;   // 采样次数
  uint32_t pressed = 0;   // 判定为按下的次数（Z 在合理压力区间）
  uint32_t zeroXy = 0;    // X/Y 同时为 0 的次数——T_DIN 悬空的典型特征
  uint16_t lastX = 0, lastY = 0, lastZ = 0;
  uint16_t minX = 4095, maxX = 0, minY = 4095, maxY = 0;
  uint16_t minZ = 4095, maxZ = 0;
} probe;
uint32_t g_lastProbeAt = 0;

// 校准状态。g_calValid 是「坐标层能不能用」的唯一判据——
// TOUCH_ENABLED 只决定要不要把坐标代码编译进来，真有没有校准看这里。
bool g_calValid = false;
uint16_t g_touchCal[5] = {320, 3560, 340, 3620, 1};
uint32_t g_calStartAt = 0;
uint32_t g_calLastSampleAt = 0;
uint16_t g_calMinX = 4095, g_calMaxX = 0, g_calMinY = 4095, g_calMaxY = 0;
uint32_t g_calHits = 0;
uint32_t g_calLastDrawAt = 0;
uint16_t g_calRawX = 0, g_calRawY = 0, g_calRawZ = 0;

// ---------------------------------------------------------------- 时钟

// ESP32-S3 掉电后 RTC 清零，时间只能靠 NTP。没对时成功就显示 --:--，
// 不拿开机时长去推算——显示错误的时间比显示空白更糟。
bool clockReady() { return time(nullptr) > 1700000000; }  // 2023-11-14 之后才算真对上

String clockText(bool withSeconds) {
  time_t now = time(nullptr);
  if (now <= 1700000000) return withSeconds ? String("--:--:--") : String("--:--");
  struct tm info;
  localtime_r(&now, &info);  // configTime 已设 TZ=+8，这里直接是本地时间
  char buf[12];
  if (withSeconds) {
    snprintf(buf, sizeof(buf), "%02d:%02d:%02d", info.tm_hour, info.tm_min, info.tm_sec);
  } else {
    snprintf(buf, sizeof(buf), "%02d:%02d", info.tm_hour, info.tm_min);
  }
  return String(buf);
}

// 只重画时钟那一小块。文本没变就不动笔，因此除秒级跳动外几乎零开销，
// 也不会像整屏重绘那样闪一下。
void tickClock(int x, int y, uint8_t font, bool withSeconds, uint16_t color) {
  String text = clockText(withSeconds);
  if (text == g_lastClockText) return;
  g_lastClockText = text;
  int w = tft.textWidth(withSeconds ? "88:88:88" : "88:88", font);
  tft.fillRect(x, y, w, tft.fontHeight(font), C_PAPER);
  tft.setTextColor(color, C_PAPER);
  tft.drawString(text, x, y, font);
}

// 时区独立设，和有没有网无关：只要 TZ 对了，localtime 就是北京时间。
void clockSetTimezone() {
  setenv("TZ", "CST-8", 1);
  tzset();
}

// SNTP 要在 WiFi 连上之后再启动，否则首个请求发不出去，之后就一直是 --:--。
void clockBegin() {
  configTime(8 * 3600, 0, "ntp.aliyun.com", "ntp.tencent.com", "pool.ntp.org");
  clockSetTimezone();  // configTime 会重写 TZ，这里再兜一次
  LOGF("[clock] sntp started\n");
}

// 服务端时间兜底。很多网络屏蔽 UDP/123，NTP 对不上时就用接口里的 epoch。
void applyEpoch(time_t epoch) {
  if (epoch <= 1700000000) return;
  struct timeval tv;
  tv.tv_sec = epoch;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
}

// ---------------------------------------------------------------- 绘制工具

void hline(int y, uint16_t color = 0xCE79) {
  tft.drawFastHLine(0, y, tft.width(), color);
}

void drawRight(const String &text, int right, int y, uint8_t font, uint16_t color = C_INK) {
  tft.setTextColor(color, C_PAPER);
  tft.drawString(text, right - tft.textWidth(text, font), y, font);
}

String truncate(const String &text, int maxWidth, uint8_t font) {
  if (tft.textWidth(text, font) <= maxWidth) return text;
  String cut = text;
  while (cut.length() > 1 && tft.textWidth(cut + "..", font) > maxWidth) {
    cut.remove(cut.length() - 1);
  }
  return cut + "..";
}

bool isAscii(const String &text) {
  for (size_t i = 0; i < text.length(); i++) {
    if ((uint8_t)text[i] > 0x7E) return false;
  }
  return true;
}

void screenMessage(const String &title, const String &line1, const String &line2 = "") {
  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("KFLOW", 12, 12, 2);
  hline(38);
  tft.drawString(title, 12, 70, 4);
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString(truncate(line1, 216, 2), 12, 118, 2);
  if (line2.length()) tft.drawString(truncate(line2, 216, 2), 12, 142, 2);
}

// ---------------------------------------------------------------- 网络

bool isHttps() { return String(g_base).startsWith("https://"); }

int httpCall(const char *method, const String &path, const String &body, const String &token,
             String &out, uint32_t timeoutMs = HTTP_TIMEOUT_MS) {
  if (WiFi.status() != WL_CONNECTED) return -1;

  HTTPClient http;
  http.setTimeout(timeoutMs);
  http.setReuse(false);

  WiFiClient plain;
  WiFiClientSecure tls;
  bool ok;
  if (isHttps()) {
    tls.setInsecure();  // 局域网自签证书；公网部署请换成 setCACert()
    ok = http.begin(tls, String(g_base) + path);
  } else {
    ok = http.begin(plain, String(g_base) + path);
  }
  if (!ok) return -2;

  http.addHeader("Accept", "application/json");
  if (token.length()) http.addHeader("Authorization", "Bearer " + token);
  if (body.length()) http.addHeader("Content-Type", "application/json");

  int status;
  if (strcmp(method, "POST") == 0) {
    status = http.POST(body);
  } else {
    status = http.GET();
  }

  out = status > 0 ? http.getString() : String("");
  http.end();
  return status;
}

// 二进制 GET。不能复用上面的 httpCall：它走 getString()，会把字节串当文本，
// 1-bit 位图里到处是 0x00，第一个空字节就把后面全截了。
// 这里直接读 stream，按 Content-Length 收满就停；服务端没报名长度就收到上限为止。
int httpGetBinary(const String &path, const String &token, uint8_t *buf, size_t cap, size_t &outLen) {
  outLen = 0;
  if (WiFi.status() != WL_CONNECTED) return -1;

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setReuse(false);

  WiFiClient plain;
  WiFiClientSecure tls;
  bool ok;
  if (isHttps()) {
    tls.setInsecure();
    ok = http.begin(tls, String(g_base) + path);
  } else {
    ok = http.begin(plain, String(g_base) + path);
  }
  if (!ok) return -2;

  http.addHeader("Accept", "application/octet-stream");
  if (token.length()) http.addHeader("Authorization", "Bearer " + token);

  int status = http.GET();
  if (status != 200) {
    http.end();
    return status;
  }

  int announced = http.getSize();  // -1 表示 chunked 或未知
  if (announced > 0 && (size_t)announced > cap) {
    http.end();
    return -3;  // 比预留缓冲还大，宁可不读也不越界写
  }

  WiFiClient *stream = http.getStreamPtr();
  size_t want = announced > 0 ? (size_t)announced : cap;
  uint32_t lastByteAt = millis();
  while (outLen < want && millis() - lastByteAt < 5000) {
    size_t avail = stream->available();
    if (!avail) {
      if (!http.connected() && outLen > 0) break;
      delay(10);
      continue;
    }
    size_t room = cap - outLen;
    size_t take = avail < room ? avail : room;
    size_t got = stream->readBytes(buf + outLen, take);
    if (!got) break;
    outLen += got;
    lastByteAt = millis();
  }
  http.end();
  return outLen > 0 ? 200 : -4;
}

// ---------------------------------------------------------------- OTA
//
// 板子摆在桌上，不该为了改一行字被拔来拔去。这一节让它自己换掉自己：
// 问服务端「我该升吗」→ 流式下载 → Update 写进另一个 app 槽 → 重启。
//
// 三个安全点：
//
// 1. 版本判断在服务端。固件只回答"是/否"，不自己比大小——比大小的逻辑
//    写两遍迟早两边不一致。
// 2. MD5 在 Update.setMD5() 里校验。不匹配时 Update.end() 直接失败，
//    分区不切换，设备还跑老固件。这是唯一挡住"下到半个文件就重启"的东西。
// 3. 失败退避 6 小时。连着失败通常是分区或网络问题，立即重试只是刷日志。

#if OTA_ENABLED

struct OtaPlan {
  bool available = false;
  String version;
  String md5;
  int size = 0;
} g_otaPlan;

uint32_t g_otaNextCheckAt = 0;   // 下次该查版本的时刻（millis）
uint32_t g_otaFailUntil = 0;     // 冷却到什么时候
bool g_otaRunning = false;       // 正在下载/写入，期间忽略触摸

// 升级时的整屏界面。刻意全屏覆盖而不是弹个小框：这一刻设备在改自己的
// 固件，断电就废，屏幕必须明确告诉人「别拔」。
void otaScreen(const String &version) {
  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_ACCENT, C_PAPER);
  tft.drawString("UPDATING", 12, 78, 2);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString(version, 12, 104, 4);
  tft.drawRect(12, 166, 216, 14, C_INK);
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("do not unplug", 12, 196, 2);
}

void otaProgress(int pct, const String &detail) {
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  tft.fillRect(14, 168, 212, 10, C_PAPER);
  tft.fillRect(14, 168, 212 * pct / 100, 10, C_ACCENT);
  // 百分比和已下载字节数：断电重来的时候，这两个数字是唯一能判断
  // "卡在哪"的证据。只画进度条看不出是慢还是停。
  tft.fillRect(12, 188, 216, 20, C_PAPER);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString(String(pct) + "%  " + detail, 12, 190, 2);
}

void otaMessage(const String &line1, const String &line2, uint16_t color) {
  tft.fillRect(12, 188, 216, 20, C_PAPER);
  tft.setTextColor(color, C_PAPER);
  tft.drawString(line1, 12, 190, 2);
  if (line2.length()) {
    tft.fillRect(12, 212, 216, 20, C_PAPER);
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString(line2, 12, 214, 1);
  }
}

// 问服务端。返回 true 表示"问到了"，不是"有更新"——两者要分开，
// 否则网络不通会被误当成"已是最新"，然后 24 小时不再重试。
bool otaCheck() {
  if (g_token.length() == 0) return false;

  String body;
  String path = String("/api/terminal/firmware/latest?current=") + FIRMWARE_VERSION;
  int status = httpCall("GET", path, "", g_token, body, 10000);
  if (status != 200) {
    LOGF("[ota] check http=%d\n", status);
    return false;
  }

  JsonDocument doc;
  if (deserializeJson(doc, body) != DeserializationError::Ok) {
    LOGF("[ota] check bad json (%d bytes)\n", (int)body.length());
    return false;
  }

  g_otaPlan.available = doc["update_available"] | false;
  g_otaPlan.version = doc["latest"].as<String>();
  g_otaPlan.md5 = doc["md5"].as<String>();
  g_otaPlan.size = doc["size"] | 0;

  LOGF("[ota] check latest=%s size=%d avail=%d\n", g_otaPlan.version.c_str(),
       g_otaPlan.size, g_otaPlan.available ? 1 : 0);
  return true;
}

// 回执：告诉服务端"我现在跑的是几版"。
// 没有它，服务端记着的永远是推之前的版本，下次一问又推一遍。
void otaReport(const char *result) {
  if (g_token.length() == 0) return;
  String body = String("{\"version\":\"") + FIRMWARE_VERSION + "\",\"result\":\"" + result + "\"}";
  String out;
  int status = httpCall("POST", "/api/terminal/firmware/report", body, g_token, out, 8000);
  LOGF("[ota] report %s -> http=%d\n", result, status);
}

// 下载并写入另一个 app 槽。
//
// 不用 httpGetBinary：那个把整个 body 收进内存缓冲（1.2MB 放 PSRAM 也行，
// 但没必要），而且它按 cap 截断——固件被截断是最坏的结果。这里边收边写，
// 写满 total 才算完，中间任何一个字节出错都立刻 abort。
bool otaApply() {
  String url = String(g_base) + "/api/terminal/firmware/download?version=" + g_otaPlan.version;

  HTTPClient http;
  http.setTimeout(15000);
  http.setReuse(false);

  WiFiClient plain;
  WiFiClientSecure tls;
  bool ok;
  if (isHttps()) {
    tls.setInsecure();
    ok = http.begin(tls, url);
  } else {
    ok = http.begin(plain, url);
  }
  if (!ok) {
    LOGF("[ota] begin failed\n");
    return false;
  }
  http.addHeader("Authorization", "Bearer " + g_token);
  http.setTimeout(20000);

  int code = http.GET();
  if (code != 200) {
    LOGF("[ota] download http=%d\n", code);
    http.end();
    return false;
  }

  int total = http.getSize();
  if (total <= 0) {
    LOGF("[ota] no content-length (chunked?), refuse\n");
    http.end();
    return false;
  }

  // begin 会拿分区容量和 total 比对，装不下直接 false。这是唯一能在
  // 下载前发现"分区方案不对"的地方。
  if (!Update.begin(total)) {
    LOGF("[ota] Update.begin(%d) refused: %s\n", total, Update.errorString());
    http.end();
    return false;
  }
  // 边下载边算摘要，end() 时比对。不一致就不切分区。
  if (g_otaPlan.md5.length() == 32) {
    Update.setMD5(g_otaPlan.md5.c_str());
  } else {
    LOGF("[ota] manifest has no md5, writing without digest check\n");
  }

  WiFiClient *stream = http.getStreamPtr();
  uint8_t buf[1024];
  int written = 0;
  int shownPct = -1;
  uint32_t lastDataAt = millis();

  while (written < total) {
    size_t avail = stream->available();
    if (!avail) {
      if (!http.connected()) break;
      if (millis() - lastDataAt > 20000) break;  // 卡住 20 秒就当断线
      delay(5);
      continue;
    }
    size_t take = avail < sizeof(buf) ? avail : sizeof(buf);
    size_t got = stream->readBytes(buf, take);
    if (!got) break;
    if (Update.write(buf, got) != got) {
      LOGF("[ota] write failed at %d: %s\n", written, Update.errorString());
      Update.abort();
      http.end();
      return false;
    }
    written += got;
    lastDataAt = millis();

    int pct = (int)((int64_t)written * 100 / total);
    if (pct != shownPct) {
      shownPct = pct;
      otaProgress(pct, String(written / 1024) + "/" + String(total / 1024) + "K");
    }
  }
  http.end();

  if (written != total) {
    LOGF("[ota] short read %d/%d\n", written, total);
    Update.abort();
    return false;
  }

  // evenIfRemaining=true：这里已经按 total 收满了，没有剩余可等。
  if (!Update.end(true)) {
    LOGF("[ota] end failed: %s\n", Update.errorString());
    return false;
  }
  LOGF("[ota] written %d bytes, md5 ok, restarting\n", written);
  return true;
}

// 一轮完整的「查 → 升」。返回是否真的升了（用于决定要不要重启）。
bool otaOnce() {
  if (!otaCheck()) return false;
  if (!g_otaPlan.available) return false;
  if (g_otaPlan.size <= 0 || g_otaPlan.md5.length() != 32) {
    LOGF("[ota] manifest incomplete, skip\n");
    return false;
  }

  LOGF("[ota] applying %s (%d bytes)\n", g_otaPlan.version.c_str(), g_otaPlan.size);
  g_otaRunning = true;
  otaScreen(g_otaPlan.version);
  otaProgress(0, "0/" + String(g_otaPlan.size / 1024) + "K");

  bool ok = otaApply();
  g_otaRunning = false;
  if (!ok) {
    g_otaFailUntil = millis() + OTA_RETRY_AFTER_FAIL_MS;
    otaScreen(g_otaPlan.version);
    otaMessage("FAILED", Update.errorString(), C_INK);
    delay(3000);
    // 失败不能留在升级界面：屏幕卡在 47% 会让人以为还在跑。
    if (g_mode == MODE_DATA) {
      renderPage();
    } else {
      showSplash();
    }
    return false;
  }

  otaMessage("DONE", "rebooting...", C_ACCENT);
  delay(1200);
  ESP.restart();
  return true;
}

// loop 每轮调一次。所有取舍都在这里：什么时候查、什么时候不查。
void otaTick() {
  if (g_otaRunning) return;
  uint32_t now = millis();
  if ((int32_t)(now - g_otaNextCheckAt) < 0) return;

  g_otaNextCheckAt = now + OTA_CHECK_INTERVAL_MS;

  if (g_otaFailUntil && (int32_t)(now - g_otaFailUntil) < 0) return;
  if (WiFi.status() != WL_CONNECTED) return;
  if (g_token.length() == 0) return;

  // 用户正在操作时别抢：升级会全屏覆盖 + 重启，正看着屏幕的人会莫名其妙。
  // 校准模式下更不能动——那 10 秒窗口被打断就得重来。
  if (g_mode == MODE_CALIBRATE) return;
  if (now - g_lastInputAt < 15000) return;

  otaOnce();
}

#endif  // OTA_ENABLED

// showUi=false 时静默重连：不擦屏、不画进度，让首屏/数据页留在屏幕上。
// 掉线时每 15 秒重连一次，如果每次都整屏重绘，小 K 首屏会被 "Connecting" 反复盖掉。
bool connectWifi(uint32_t timeoutMs = 20000, bool showUi = true) {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint32_t started = millis();
  uint8_t dots = 0;
  if (showUi) {
    tft.fillScreen(C_PAPER);
    tft.setTextColor(C_INK, C_PAPER);
    tft.drawString("KFLOW", 12, 12, 2);
    hline(38);
    tft.drawString("Connecting", 12, 80, 4);
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString(WIFI_SSID, 12, 126, 2);
  }

  while (WiFi.status() != WL_CONNECTED && millis() - started < timeoutMs) {
    delay(400);
    if (showUi) {
      tft.fillRect(12, 160, 24, 20, C_PAPER);
      tft.setTextColor(C_MUTED, C_PAPER);
      tft.drawString(String("....").substring(0, dots % 4 + 1), 12, 160, 4);
      dots++;
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    g_wifiOk = true;
    g_wifiFailed = false;
    LOGF("[wifi] connected ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(), (int)WiFi.RSSI());
    if (showUi) {
      tft.setTextColor(C_ACCENT, C_PAPER);
      tft.drawString(WiFi.localIP().toString(), 12, 208, 2);
      delay(600);
    }
    return true;
  }
  g_wifiOk = false;
  g_wifiFailed = true;
  return false;
}

// ---------------------------------------------------------------- WiFi 扫描
//
// 这块板子的射频只有 2.4GHz（802.11 b/g/n）。5GHz 不是"连不上"，是扫都扫
// 不到——换路由器、改密码、或者怀疑信号的时候，第一件事就是扫一遍：
//   * 目标 SSID 在不在（很多路由器默认只开 5G，或把 2.4G 藏在后台开关里）
//   * 信道几号（1/6/11 之外的信道在某些固件上噪声更大）
//   * 加密方式（WPA3-only 的 AP 这块芯片连不上，必须退到 WPA2 混合模式）
//   * 信号强度（低于 -85dBm 基本握手不了）
static const char *encName(wifi_auth_mode_t m) {
  switch (m) {
    case WIFI_AUTH_OPEN: return "OPEN";
    case WIFI_AUTH_WEP: return "WEP";
    case WIFI_AUTH_WPA_PSK: return "WPA";
    case WIFI_AUTH_WPA2_PSK: return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/2";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-ENT";
    case WIFI_AUTH_WPA3_PSK: return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/3";
#ifdef WIFI_AUTH_WPA3_ENT_192
    case WIFI_AUTH_WPA3_ENT_192: return "WPA3-192";
#endif
    default: return "?";
  }
}

void scanWifi() {
  bool wasConnected = (WiFi.status() == WL_CONNECTED);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(false, false);  // 只断不擦：扫完还要用原来那套凭据连回去
  delay(150);

  int n = WiFi.scanNetworks(false, true);  // 同步扫描，含隐藏 SSID
  LOGF("[scan] found=%d (2.4GHz only — 5GHz is invisible to this radio)\n", n);
  if (n <= 0) {
    LOGF("[scan] nothing in range. the AP's 2.4GHz radio is probably off\n");
  }
  int mine = -1;
  for (int i = 0; i < n; i++) {
    String ssid = WiFi.SSID(i);
    if (!ssid.length()) ssid = "<hidden>";
    bool hit = (ssid == WIFI_SSID);
    if (hit) mine = i;
    LOGF("[scan] %s%-20s ch=%2d rssi=%4d %s\n", hit ? "*" : " ", ssid.c_str(),
         WiFi.channel(i), (int)WiFi.RSSI(i), encName(WiFi.encryptionType(i)));
  }
  if (mine < 0) {
    // 这句是重点：目标 SSID 不在列表里，说明问题在路由器那一侧，不在固件。
    LOGF("[scan] \"%s\" NOT found\n", WIFI_SSID);
  } else {
    LOGF("[scan] \"%s\" ch=%d rssi=%d enc=%s\n", WIFI_SSID, WiFi.channel(mine),
         (int)WiFi.RSSI(mine), encName(WiFi.encryptionType(mine)));
  }
  WiFi.scanDelete();

  if (wasConnected) {
    // 一次诊断不该把设备从网上踢下来：扫完立刻重连回原配置。
    connectWifi(15000, false);
    LOGF("[scan] reconnected=%d ip=%s\n", (int)g_wifiOk,
         g_wifiOk ? WiFi.localIP().toString().c_str() : "-");
  }
}

// 真机没有键盘，改服务地址只能从 USB 串口喂一行进来。
//
// 这功能是拿真实故障换来的：Mac 的 DHCP 从 .71 跳到 .87，设备网络一切正常、
// 首屏也显示有 WiFi，只是每个请求打到一个空的地址上。当时只能重烧固件。
// 存进 NVS 之后，这类问题接根线发一行就解决了。
void serialSetBase() {
  LOGF("[base] current=%s\n", g_base);
  LOGF("[base] send url + Enter (empty Enter = back to compile-time default)\n");

  String line;
  uint32_t deadline = millis() + 60000;
  while (millis() < deadline) {
    while (Serial.available()) {
      int c = Serial.read();
      if (c == '\r') continue;
      if (c == '\n') {
        line.trim();
        if (!line.length()) {
          strncpy(g_base, KFLOW_BASE, sizeof(g_base) - 1);
          g_base[sizeof(g_base) - 1] = 0;
          prefs.remove("base");
          LOGF("[base] reset -> %s\n", g_base);
        } else if (line.startsWith("http://") || line.startsWith("https://")) {
          strncpy(g_base, line.c_str(), sizeof(g_base) - 1);
          g_base[sizeof(g_base) - 1] = 0;
          prefs.putString("base", g_base);
          LOGF("[base] saved -> %s\n", g_base);
        } else {
          LOGF("[base] rejected (needs http:// or https://)\n");
        }
        return;
      }
      if (line.length() < 72) line += (char)c;
    }
    delay(20);
  }
  LOGF("[base] timeout, unchanged (%s)\n", g_base);
}

// ---------------------------------------------------------------- 配对
void drawPairingCode(const String &code, int remainSeconds) {
  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("KFLOW", 12, 12, 2);
  hline(38);

  tft.drawString("Pair this screen", 12, 52, 2);
  tft.fillRect(0, 84, 240, 60, C_PAPER);
  for (int i = 0; i < (int)code.length(); i++) {
    tft.drawChar(26 + i * 34, 98, code[i], C_INK, C_PAPER, 4);
  }
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("Open /terminal and", 12, 168, 2);
  tft.drawString("enter this code", 12, 188, 2);

  tft.fillRect(0, 232, 240, 24, C_PAPER);
  tft.drawString("valid " + String(remainSeconds / 60) + "m " + String(remainSeconds % 60) + "s", 12, 232, 2);
}

void runPairing() {
  while (true) {
    String body = String("{\"device_id\":\"") + DEVICE_ID + "\",\"hardware\":\"esp32s3-ili9341\",\"firmware\":\"" +
                  FIRMWARE_VERSION + "\"}";
    String response;
    int status = httpCall("POST", "/api/terminal/pair/start", body, "", response);
    if (status != 200) {
      String reason;
      if (status == 429) {
        reason = "Too many requests";
      } else if (status < 0) {
        reason = "No connection";
      } else {
        reason = String("HTTP ") + status;
        if (status == 403) reason = "Pairing disabled";
      }
      // 退避重试：服务端有 IP 限流，1 秒一次的重试会被 429 打成死循环
      for (int remain = (int)g_pairRetrySeconds; remain > 0; remain--) {
        screenMessage(reason, "Retry in " + String(remain) + "s",
                      status == 429 ? "Server busy, waiting" : "Check wifi & KFLOW_BASE");
        delay(1000);
      }
      g_pairRetrySeconds *= 2;
      if (g_pairRetrySeconds > 120) g_pairRetrySeconds = 120;
      if (status < 0) connectWifi(12000, false);
      continue;
    }
    g_pairRetrySeconds = 5;

#if ARDUINOJSON_VERSION_MAJOR >= 7
    JsonDocument doc;
#else
    DynamicJsonDocument doc(4096);
#endif
    DeserializationError err = deserializeJson(doc, response);
    if (err) {
      screenMessage("Bad response", err.c_str());
      delay(3000);
      continue;
    }

    String code = doc["pairing_code"].as<String>();
    uint32_t expiresIn = doc["expires_in"] | 600;
    uint32_t startedAt = millis();
    LOGF("[pair] code=%s expires_in=%us\n", code.c_str(), (unsigned)expiresIn);
    drawPairingCode(code, expiresIn);

    while (millis() - startedAt < expiresIn * 1000UL) {
      delay(PAIR_POLL_MS);
      drawPairingCode(code, expiresIn - (millis() - startedAt) / 1000);

      String pollBody = String("{\"device_id\":\"") + DEVICE_ID + "\",\"code\":\"" + code + "\"}";
      String pollResponse;
      int pollStatus = httpCall("POST", "/api/terminal/pair/poll", pollBody, "", pollResponse);
      if (pollStatus != 200) continue;

#if ARDUINOJSON_VERSION_MAJOR >= 7
      JsonDocument pdoc;
#else
      DynamicJsonDocument pdoc(4096);
#endif
      if (deserializeJson(pdoc, pollResponse)) continue;
      String state = pdoc["status"] | "";
      String token = pdoc["token"] | "";
      if (state == "active" && token.length()) {
        g_token = token;
        prefs.putString("token", g_token);
        g_refreshSeconds = pdoc["refresh_seconds"] | REFRESH_FALLBACK_SECONDS;
        screenMessage("Paired", "Fetching your account...");
        delay(800);
        return;
      }
      if (state == "revoked") {
        // 网页端吊销了这台设备：不要在这里干等，直接要一个新码重新走配对。
        screenMessage("Device revoked", "New code in a moment");
        delay(1500);
        break;
      }
    }
  }
}

// ---------------------------------------------------------------- 离线缓存

// 只缓存「看一眼就够」的那几个字段，存 NVS 的 "cache" 键，约 300 字节。
void saveSnapshotCache() {
  if (!snap.valid) return;

  // NVS 有擦写寿命（约 10 万次）：300 秒刷一次，一年就把额度用光了。
  // 所以只在关键字段变了、或距上次落盘超过 1 小时时才真正写。
  String fingerprint = String(snap.balance) + "|" + String(snap.unread) + "|" +
                       String(snap.badges) + "|" + String(snap.topics) + "|" +
                       String(snap.streak) + "|" + snap.lastLabel;
  static String lastFingerprint;
  static uint32_t lastSavedAt = 0;
  bool stale = (millis() - lastSavedAt) > 3600000UL;
  if (fingerprint == lastFingerprint && !stale) return;

#if ARDUINOJSON_VERSION_MAJOR >= 7
  JsonDocument doc;
#else
  DynamicJsonDocument doc(1024);
#endif
  doc["u"] = snap.username;
  doc["t"] = snap.serverTime;
  doc["l"] = snap.lastLabel;
  doc["ti"] = snap.lastTitle;
  doc["b"] = snap.balance;
  doc["n"] = snap.unread;
  doc["g"] = snap.badges;
  doc["s"] = snap.streak;
  doc["p"] = snap.topics;
  doc["r"] = snap.replies;
  doc["k"] = snap.likes;
  doc["a"] = snap.activeDays;
  // 通知最多三条，拆成 l0/t0 … l2/t2 平铺存：比嵌数组短，
  // 也比拼分隔符安全（标题里出现什么字符都不用转义）。
  char key[4];
  for (int i = 0; i < snap.itemCount && i < 3; i++) {
    snprintf(key, sizeof(key), "l%d", i);
    doc[key] = snap.items[i].label;
    snprintf(key, sizeof(key), "t%d", i);
    doc[key] = snap.items[i].title;
  }
  String out;
  serializeJson(doc, out);
  prefs.putString("cache", out);
  lastFingerprint = fingerprint;
  lastSavedAt = millis();
  LOGF("[cache] saved %u bytes\n", (unsigned)out.length());
}

// 开机先把上次的数据摆上屏：断网、服务端挂了也能看到最后一眼的样子，
// 只是页脚的 sync 会变成 cached，明确告诉你这是旧数据。
bool loadSnapshotCache() {
  String raw = prefs.getString("cache", "");
  if (!raw.length()) return false;
#if ARDUINOJSON_VERSION_MAJOR >= 7
  JsonDocument doc;
#else
  DynamicJsonDocument doc(1024);
#endif
  if (deserializeJson(doc, raw)) {
    LOGF("[cache] corrupt, ignored\n");
    return false;
  }
  snap.username = doc["u"].as<String>();
  snap.serverTime = doc["t"].as<String>();
  snap.lastLabel = doc["l"].as<String>();
  snap.lastTitle = doc["ti"].as<String>();
  snap.balance = doc["b"] | 0;
  snap.unread = doc["n"] | 0;
  snap.badges = doc["g"] | 0;
  snap.streak = doc["s"] | 0;
  snap.topics = doc["p"] | 0;
  snap.replies = doc["r"] | 0;
  snap.likes = doc["k"] | 0;
  snap.activeDays = doc["a"] | 0;
  char key[4];
  snap.itemCount = 0;
  for (int i = 0; i < 3; i++) {
    snprintf(key, sizeof(key), "l%d", i);
    String label = doc[key] | "";
    snprintf(key, sizeof(key), "t%d", i);
    String title = doc[key] | "";
    if (!label.length()) break;
    snap.items[i].label = label;
    snap.items[i].title = title;
    snap.itemCount = i + 1;
  }
  if (snap.itemCount > 0) {
    snap.lastLabel = snap.items[0].label;
    snap.lastTitle = snap.items[0].title;
  }
  snap.valid = true;
  g_fromCache = true;
  LOGF("[cache] loaded %u bytes balance=%d\n", (unsigned)raw.length(), snap.balance);
  return true;
}

// ---------------------------------------------------------------- 数据

bool fetchSummary() {
  String payload;
  int status = httpCall("GET", "/api/terminal/summary", "", g_token, payload);
  LOGF("[sync] http=%d bytes=%u\n", status, (unsigned)payload.length());

  if (status == 401 || status == 403) {
    LOGF("[sync] token rejected, clearing\n");
    g_token = "";
    prefs.remove("token");
    return false;
  }
  if (status != 200) {
    g_offline = true;
    return false;
  }

#if ARDUINOJSON_VERSION_MAJOR >= 7
  JsonDocument doc;
#else
  DynamicJsonDocument doc(8192);
#endif
  if (deserializeJson(doc, payload)) {
    g_offline = true;
    return false;
  }

  snap.username = doc["user"]["display_name"].as<String>();
  snap.deviceName = doc["device"]["name"].as<String>();
  snap.serverTime = doc["server_time"].as<String>();
  // 时钟优先用服务端给的 epoch：比 NTP 可靠，也不用解析 ISO 的时区偏移。
  applyEpoch((time_t)(doc["epoch"] | 0));
  snap.balance = doc["points"]["balance"] | 0;
  snap.unread = doc["notifications"]["unread"] | 0;
  snap.badges = doc["community"]["badges"] | 0;
  snap.streak = doc["points"]["streak"] | 0;
  snap.topics = doc["community"]["topics"] | 0;
  snap.replies = doc["community"]["replies"] | 0;
  snap.likes = doc["community"]["likes_received"] | 0;
  snap.activeDays = doc["community"]["active_days"] | 0;

  // 签到状态随摘要一起下来。叶子节点为 null 说明服务端还是老版本，
  // 那就保持"不知道"，不要拿 false 去冒充"没签到"。
  if (!doc["checkin"].isNull()) {
    snap.checkinDone = doc["checkin"]["done"] | false;
    snap.checkinReward = doc["checkin"]["reward"] | 0;
    snap.checkinKnown = true;
  }

  JsonArray items = doc["notifications"]["items"].as<JsonArray>();
  snap.itemCount = 0;
  for (JsonObject row : items) {
    if (snap.itemCount >= 3) break;
    snap.items[snap.itemCount].label = row["label"].as<String>();
    snap.items[snap.itemCount].title = row["title"].as<String>();
    snap.items[snap.itemCount].isRead = row["is_read"] | false;
    snap.itemCount++;
  }
  if (snap.itemCount > 0) {
    snap.lastLabel = snap.items[0].label;
    snap.lastTitle = snap.items[0].title;
  } else {
    snap.lastLabel = "";
    snap.lastTitle = "";
  }

  // ---- 新通知判定 ----
  // 水位线第一次建立时不弹：那一堆未读是"以前就有"，不是"刚刚到"。
  // 直接把当前 id 记下来当基线，之后严格变大才算新。
  int latestId = doc["notifications"]["latest_id"] | 0;
  snap.latestId = latestId;
  if (g_seenNoticeId == 0) {
    if (latestId > 0) {
      g_seenNoticeId = (uint32_t)latestId;
      prefs.putUInt("nid", g_seenNoticeId);
      LOGF("[notice] baseline id=%u\n", g_seenNoticeId);
    }
  } else if ((uint32_t)latestId > g_seenNoticeId && snap.unread > 0) {
    g_pendingNotice = true;
    LOGF("[notice] new id=%d (seen=%u) unread=%d\n", latestId, g_seenNoticeId, snap.unread);
  }

  g_refreshSeconds = doc["refresh_seconds"] | REFRESH_FALLBACK_SECONDS;
  snap.valid = true;
  g_offline = false;
  g_fromCache = false;
  // 摘要刷新了，中文页的内容可能也变了（新碎碎念 / 新帖）。只标过期不立刻重取：
  // 翻到那两页才拉，省得每次后台刷新都白跑两趟网络。
  g_boards[0].valid = false;
  g_boards[1].valid = false;
  saveSnapshotCache();
  return true;
}

// ---------------------------------------------------------------- 渲染

void drawStat(int x, const char *label, int value) {
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString(label, x, 116, 1);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString(String(value), x, 128, 4);
}

// 未读角标：右对齐到 rightX 的红色小胶囊，里面是数字。
// 用红色实心而不是描边，是因为这块屏在桌上通常离人一米远——
// 描边在日光下看不出来，实心色块一眼就能瞥见。
void drawUnreadBadge(int rightX, int y, int count) {
  if (count <= 0) return;
  String text = count > 99 ? String("99+") : String(count);
  int w = tft.textWidth(text, 1) + 8;
  int h = 15;
  int x = rightX - w;
  tft.setTextDatum(TL_DATUM);
  tft.fillRoundRect(x, y, w, h, 4, C_ALERT);
  tft.setTextColor(C_PAPER, C_ALERT);
  tft.drawString(text, x + 4, y + 4, 1);
}

// 五屏共用的头部：左边标识，右边页码点（实心=当前）。
// 240px 宽里，一排点比一个用户名更能说明"后面还有东西"。
// 点从右往左排：末位固定贴 228，页数变了也不用重新算起始坐标。
void drawHeader() {
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("KFLOW", 12, 12, 2);
  // 未读数常驻在标识右边：不用翻到第 4 屏也知道有东西没看。
  drawUnreadBadge(104, 12, snap.unread);
  for (int i = 0; i < PAGE_COUNT; i++) {
    int cx = 228 - (PAGE_COUNT - 1 - i) * 9;
    if (i == g_page) {
      tft.fillCircle(cx, 19, 3, C_ACCENT);
    } else {
      tft.drawCircle(cx, 19, 3, 0xCE79);
    }
  }
  hline(38);
}

// 第 0 屏：积分 + 三项统计 + 最新一条。原来的整页内容，挪进 head/foot 之间。
void renderHome() {
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("K POINTS", 12, 50, 1);

  tft.setTextColor(C_INK, C_PAPER);
  tft.drawNumber(snap.balance, 14, 62, 7);

  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("streak " + String(snap.streak) + "d", 150, 76, 2);

  // 签到状态：不知道就不写（缓存里没有这一项，跨天会撒谎）。
  if (snap.checkinKnown) {
    if (snap.checkinDone) {
      drawRight("CHECKED IN", 228, 52, 1, C_ACCENT);
    } else if (snap.checkinReward > 0) {
      drawRight(String("CHECK IN +") + String(snap.checkinReward), 228, 52, 1, C_MUTED);
    } else {
      drawRight("CHECK IN", 228, 52, 1, C_MUTED);
    }
  }
  hline(112);

  drawStat(14, "UNREAD", snap.unread);
  drawStat(96, "BADGES", snap.badges);
  drawStat(178, "TOPICS", snap.topics);
  hline(166);

  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("LATEST", 12, 178, 1);
  if (snap.lastLabel.length()) {
    tft.setTextColor(C_INK, C_PAPER);
    tft.drawString(snap.lastLabel, 12, 194, 2);
    // 首版字库只有 ASCII：中文标题降级成占位，避免屏幕上出现方块。
    String line = isAscii(snap.lastTitle) ? truncate(snap.lastTitle, 216, 2) : String("(see kflow web)");
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString(line, 12, 216, 2);
  } else {
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString("All clear", 12, 198, 2);
  }
}

// 第 1 屏：社区数字。首页只放得下三项，其余的都在这里。
void renderStats() {
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("COMMUNITY", 12, 46, 4);

  const char *labels[5] = {"TOPICS", "REPLIES", "LIKES IN", "ACTIVE DAYS", "BADGES"};
  int values[5] = {snap.topics, snap.replies, snap.likes, snap.activeDays, snap.badges};
  for (int i = 0; i < 5; i++) {
    int y = 76 + i * 34;
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString(labels[i], 12, y, 1);
    drawRight(String(values[i]), 228, y - 6, 4);
  }
}

// 第 2 屏：最新三条通知。中文标题仍是占位，等中文字库再说。
void renderNotice() {
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("NOTICE", 12, 46, 4);
  drawUnreadBadge(228, 52, snap.unread);

  if (snap.itemCount == 0) {
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString("All clear", 12, 90, 2);
    return;
  }

  for (int i = 0; i < snap.itemCount; i++) {
    int y = 80 + i * 56;
    tft.setTextColor(C_ACCENT, C_PAPER);
    tft.drawString(snap.items[i].label, 12, y, 1);
    // 未读的那几条在右边点一颗红点：一屏三条，哪条是新的必须能分辨。
    if (!snap.items[i].isRead) tft.fillCircle(230, y + 5, 3, C_ALERT);
    String title = isAscii(snap.items[i].title) ? snap.items[i].title : String("(open kflow web)");
    tft.setTextColor(C_INK, C_PAPER);
    tft.drawString(truncate(title, 208, 2), 12, y + 12, 2);
    if (i < snap.itemCount - 1) hline(y + 44, 0xE71C);
  }
}

// ---------------------------------------------------------------- 中文位图

// 板上没有中文字库，中文只能由服务端画成 1-bit 位图再贴上来。
// 取一屏大约 5KB，局域网一两百毫秒；缓存 90 秒，翻页来回点不会反复请求。
bool fetchBoard(uint8_t slot) {
  BoardCache &cache = g_boards[slot];
  if (!cache.data) {
    // 优先 PSRAM：8MB 里放两块 16KB 的缓冲毫无压力，内部 RAM 留给 WiFi。
    cache.data = (uint8_t *)ps_malloc(BOARD_MAX_BYTES);
    if (!cache.data) cache.data = (uint8_t *)malloc(BOARD_MAX_BYTES);
    if (!cache.data) {
      LOGF("[board] malloc failed\n");
      cache.valid = false;
      cache.failed = true;
      return false;
    }
  }

  const char *name = slot == 0 ? "murmur" : "topic";
  size_t len = 0;
  int status = httpGetBinary(String("/api/terminal/textboard?slot=") + name, g_token, cache.data,
                             BOARD_MAX_BYTES, len);
  LOGF("[board] %s http=%d bytes=%u\n", name, status, (unsigned)len);

  cache.len = len;
  cache.fetchedAt = millis();
  // 少于 3 字节连块数都放不下，当作没取到，别让 drawBoard 去读野内存。
  cache.valid = (status == 200 && len > 2);
  cache.failed = !cache.valid;
  return cache.valid;
}

// 解板子并逐块贴图。格式见 apps/terminal/textboard.py 顶部注释：
//   u16 count，然后每块 12 字节头（x,y,w,h,stride,color）+ stride*h 字节。
void drawBoard(const uint8_t *buf, size_t len) {
  if (len < 2) return;
  uint16_t count = 0;
  memcpy(&count, buf, 2);
  size_t off = 2;
  for (uint16_t i = 0; i < count; i++) {
    if (off + BOARD_HEADER_BYTES > len) break;
    uint16_t x, y, w, h, stride, color;
    memcpy(&x, buf + off + 0, 2);
    memcpy(&y, buf + off + 2, 2);
    memcpy(&w, buf + off + 4, 2);
    memcpy(&h, buf + off + 6, 2);
    memcpy(&stride, buf + off + 8, 2);
    memcpy(&color, buf + off + 10, 2);
    off += BOARD_HEADER_BYTES;
    size_t bytes = (size_t)stride * (size_t)h;
    if (!stride || !w || !h || off + bytes > len) break;
    // drawBitmap 只画 1 位，背景保持纸色——这正是不用刷整块矩形的原因，
    // 白底不闪一下，看起来像"字直接浮上来"。
    tft.drawBitmap((int16_t)x, (int16_t)y, buf + off, (int16_t)w, (int16_t)h, color);
    off += bytes;
  }
}

void renderBoard(uint8_t slot) {
  BoardCache &cache = g_boards[slot];
  if (cache.valid && cache.data) {
    drawBoard(cache.data, cache.len);
    return;
  }
  tft.setTextColor(cache.failed ? C_INK : C_MUTED, C_PAPER);
  tft.drawString(cache.failed ? "can't load" : "loading...", 12, 92, 2);
  if (cache.failed) {
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString("tap again to retry", 12, 118, 1);
  }
}

// 翻到中文页。首次进来先铺骨架（片头那句 loading），否则取数据那一两秒
// 屏幕一动不动，看着像死了；已经有旧内容时就直接先显示旧的，取到再换。
void showBoardPage(int page, uint8_t slot) {
  g_page = page;
  g_lastInputAt = millis();
  BoardCache &cache = g_boards[slot];
  bool stale = !cache.valid || (uint32_t)(millis() - cache.fetchedAt) > BOARD_TTL_MS;
  if (stale) {
    if (!cache.len) renderPage();
    fetchBoard(slot);
  }
  renderPage();
}

// 页脚：左边常驻时钟，右边数据新鲜度（sync 本次同步 / cached 缓存 / OFFLINE）。
// 另加两条 10px 的短刻度，标出三段分界——只在坐标层可用时画：
// 没校准时点哪都算同一次点按，画上三条带反而是骗人。
void drawFooter() {
  hline(252);
  g_lastClockText = "";
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString(clockText(true), 12, 258, 2);

  String syncAt = snap.serverTime.length() >= 16 ? snap.serverTime.substring(11, 16) : String("--:--");
  String tag;
  if (g_offline) {
    tag = "OFFLINE";
  } else if (g_fromCache) {
    tag = "cached " + syncAt;
  } else {
    tag = "sync " + syncAt;
  }
  drawRight(tag, 228, 264, 1, g_offline ? C_INK : C_MUTED);

  tft.setTextColor(0xBDF7, C_PAPER);
  tft.drawString("BOOT: back  hold: rebind", 12, 290, 1);

  if (g_calValid) {
    tft.fillRect(0, ZONE_CHECKIN_END - 1, 10, 2, 0xCE79);
    tft.fillRect(0, ZONE_NEXT_END - 1, 10, 2, 0xCE79);
    drawRight("tap check-in", 228, 98, 1, 0xBDF7);
    drawRight("tap next", 228, 236, 1, 0xBDF7);
    drawRight("tap sync", 228, 290, 1, 0xBDF7);
  } else {
    // 没校准就只能单调翻页，把规则老实写在屏幕上。
    drawRight("tap: next", 228, 290, 1, 0xBDF7);
  }
  tft.drawFastHLine(0, 306, 240, C_ACCENT);
}

void renderPage() {
  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  drawHeader();
  if (g_page == 1) {
    renderStats();
  } else if (g_page == PAGE_MURMUR) {
    renderBoard(0);
  } else if (g_page == PAGE_TOPIC) {
    renderBoard(1);
  } else if (g_page == PAGE_NOTICE) {
    renderNotice();
  } else {
    renderHome();
  }
  drawFooter();
}

// ---------------------------------------------------------------- 主流程

// 把「检测到新通知」变成屏幕上的动作：记水位线、开提醒窗口、翻到通知页。
// 返回 true 表示已经切页，调用方直接渲染即可（别再画原来那页，会闪两下）。
//
// 一条例外：人正在数据页上看东西（30 秒内有过输入）时不抢屏。
// 抢屏只在"没人看"的时候才有意义；正读着碎碎念被拽走，比不提醒更烦。
// 这种情况下仍然记水位线——红点已经亮在头上了，抬头就看得见。
bool consumeNoticeSignal() {
  if (!g_pendingNotice) return false;
  g_pendingNotice = false;
  g_seenNoticeId = (uint32_t)snap.latestId;
  prefs.putUInt("nid", g_seenNoticeId);

  bool busy = (g_mode == MODE_DATA) && (millis() - g_lastInputAt < ATTENTION_HOLD_OFF_MS);
  if (busy) {
    LOGF("[notice] new arrives while busy -> badge only\n");
    return false;
  }

  g_attnUntil = millis() + ATTENTION_MS;
  g_page = PAGE_NOTICE;
  g_mode = MODE_DATA;
  g_lastInputAt = millis();
  LOGF("[notice] pop to notice page, %us\n", (unsigned)(ATTENTION_MS / 1000));
  return true;
}

void syncNow() {
  bool ok = fetchSummary();
  if (!ok) {
    // 没拿到新数据，就承认屏幕上这份是旧的：页脚会从 sync 变成 cached/OFFLINE。
    g_fromCache = snap.valid;
    g_offline = true;
  }
  if (!ok && !snap.valid) {
    screenMessage("No data", g_token.length() ? "Retry in a moment" : "Pairing required");
  } else {
    // 先消费提醒信号再渲染：这样一次刷新只画一次屏，不会先画旧页再弹新页。
    consumeNoticeSignal();
    renderPage();
  }
  g_nextSyncAt = millis() + g_refreshSeconds * 1000UL;
}

// ---------------------------------------------------------------- 分带交互

// 半透明遮罩做不了（SPI 屏没有 alpha），就画一个白底描边的小卡片，
// 停 1.3 秒再整页重绘——足够看清结果，也不会在屏上留残影。
void toastBox(const String &line1, const String &line2, uint16_t color) {
  tft.fillRect(10, 124, 220, 78, C_PAPER);
  tft.drawRect(10, 124, 220, 78, color);
  tft.drawRect(11, 125, 218, 76, color);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(color, C_PAPER);
  tft.drawString(truncate(line1, 196, 4), 20, 136, 4);
  if (line2.length()) {
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString(truncate(line2, 196, 2), 20, 172, 2);
  }
}

void nextPage() {
  int next = (g_page + 1) % PAGE_COUNT;
  // 两页中文的正文不在设备上，翻到就得先问服务端要；其余页纯本地渲染。
  if (next == PAGE_MURMUR) {
    showBoardPage(PAGE_MURMUR, 0);
    return;
  }
  if (next == PAGE_TOPIC) {
    showBoardPage(PAGE_TOPIC, 1);
    return;
  }
  g_page = next;
  g_lastInputAt = millis();
  renderPage();
}

// 上带：签到。这是终端唯一的写操作——只记"今天来过"，不发内容、不改设置。
void doCheckIn() {
  if (!g_token.length()) return;
  if (snap.checkinKnown && snap.checkinDone) {
    // 已知签过了就别白跑一趟网络，省一次请求也省一次等待。
    toastBox("ALREADY", "come back tomorrow", C_MUTED);
    delay(1100);
    renderPage();
    return;
  }

  toastBox("CHECK IN", "talking to server", C_MUTED);
  String response;
  int status = httpCall("POST", "/api/terminal/checkin", "{}", g_token, response, 8000);
  LOGF("[checkin] http=%d body=%s\n", status, response.c_str());

  if (status != 200) {
    String why = status < 0 ? String("no connection") : String("http ") + String(status);
    toastBox("NO SIGNAL", why, C_INK);
    delay(1300);
    renderPage();
    return;
  }

#if ARDUINOJSON_VERSION_MAJOR >= 7
  JsonDocument doc;
#else
  DynamicJsonDocument doc(1024);
#endif
  if (deserializeJson(doc, response)) {
    toastBox("BAD REPLY", "try again later", C_INK);
    delay(1300);
    renderPage();
    return;
  }

  bool awarded = doc["awarded"] | false;
  int points = doc["points"] | 0;
  snap.balance = doc["balance"] | snap.balance;
  snap.streak = doc["streak"] | snap.streak;
  snap.checkinDone = true;
  snap.checkinKnown = true;
  snap.checkinReward = doc["reward"] | snap.checkinReward;
  g_offline = false;

  if (awarded) {
    toastBox(String("+") + String(points) + String(" K"), "checked in today", C_ACCENT);
  } else {
    toastBox("ALREADY", "come back tomorrow", C_MUTED);
  }
  delay(1300);
  renderPage();
}

// 坐标层可用时，一次点按按 y 分带派活。x 暂时用不上，留着给以后左右滑。
void handleZoneTap(int x, int y) {
  (void)x;
  g_lastInputAt = millis();
  if (y < ZONE_CHECKIN_END) {
    doCheckIn();
  } else if (y < ZONE_NEXT_END) {
    nextPage();
  } else {
    syncNow();
  }
}

// ---------------------------------------------------------------- 待机动画

// 小 K 原本是一张静态立绘，摆在桌上不动。待机时让它"活着"分两层做，
// 两层都不重画整张立绘：
//
// 1) 呼吸——整张立绘上下浮 0~3px。听起来像整屏重贴（122KB 约 25ms），
//    但相邻两帧只差 1px，SPI 逐行扫描的中间态看不出来。代价是每秒约 3 次
//    25ms，占 CPU 不到 7%。位移只往上走：立绘底部是身体截面，往下移会啃掉
//    一截；往上移露出的顶边正好是白背景，补上去无痕。
// 2) 眨眼——只重贴眼睛那两小块（各 ~1KB）。这是唯一能让这张脸"有反应"
//    的动作，成本低到可以随时来一下。

// 幅度 2px、周期 4.4s。
//
// 原来是 3px / 2.9s，视觉上不像呼吸，像整张画一格一格往上挪——因为整屏
// 刚性平移是离散的，每 360ms 突然跳 1px，而人眼对脸部整体位移极其敏感，
// 1px 就能看出来。位移幅度没法做成亚像素，只能把档位减到 2 档、把节奏
// 放慢到接近真实呼吸（成人平静呼吸约 4~5 秒一次），让单次跳变的视觉权重
// 降下来。真实呼吸在谷底和峰顶都会停一下，所以两端各重复几步。
static const int8_t BREATH_PATTERN[] = {0, 0, 1, 1, 2, 2, 2, 2, 1, 1, 0, 0};
static const uint32_t BREATH_STEP_MS = 370;    // 12 步 ≈ 4.4 秒一次完整呼吸
static const uint32_t BLINK_CLOSED_MS = 110;   // 闭着停留：再长就像犯困
static const uint32_t BLINK_QUICK_MS = 150;    // 连眨的第二下间隔
static const uint32_t BLINK_GAP_MIN_MS = 2600;
static const uint32_t BLINK_GAP_MAX_MS = 7200;

static uint8_t g_breathIdx = 0;
static uint32_t g_breathAt = 0;
static uint8_t g_breathDy = 0;

static uint8_t g_blinkState = 0;  // 0 = 睁着，1 = 闭着
static uint8_t g_blinkBurst = 0;  // 还剩几下连眨
static uint32_t g_blinkAt = 0;    // 下一次换脸的时刻

// 最近一次整屏重贴的耗时（微秒）。呼吸是每 360ms 重传 122KB，如果这个数
// 抖动很大或者接近 360ms，说明 SPI 在和 WiFi/触摸抢总线，画面才会"顿"。
static uint32_t g_lastBreathUs = 0;

// 按 dy 上移重贴立绘，露出来的底部用原图最后一行补齐。
// 不 memcpy 整帧：直接从源数组偏移取，省掉一次 122KB 的搬运。
void drawSplashShifted(uint8_t dy) {
  uint32_t t0 = micros();
  if (dy == 0) {
    tft.pushImage(0, 0, XIAOK_SPLASH_W, XIAOK_SPLASH_H, xiaok_splash);
  } else {
    tft.pushImage(0, 0, XIAOK_SPLASH_W, XIAOK_SPLASH_H - dy, xiaok_splash + XIAOK_SPLASH_W * dy);
    const uint16_t *lastRow = xiaok_splash + XIAOK_SPLASH_W * (XIAOK_SPLASH_H - 1);
    for (uint8_t i = 0; i < dy; i++) {
      tft.pushImage(0, XIAOK_SPLASH_H - dy + i, XIAOK_SPLASH_W, 1, lastRow);
    }
  }
  g_lastBreathUs = micros() - t0;
}

// 眼睛图块的坐标是相对**未位移的原图**算出来的，而呼吸会把整张立绘上移 dy。
// 所以贴眼睛时必须减掉 dy。
//
// 第一版漏了这个减法，结果每次眨眼都把眼睛往下拽 dy 像素，下一帧整屏重贴
// 又把它推回去——呼吸 3px 时眼睛就跟着跳 3px，肉眼看着就是"屏幕在跳"。
void drawEyes(bool closed, uint8_t dy) {
  // dy 不会超过 3，而眼睛 Y 最小是 52，减完仍是正数；这里只是防一手参数乱传。
  int ly = XIAOK_EYE_L_OPEN_Y - (int)dy;
  int ry = XIAOK_EYE_R_OPEN_Y - (int)dy;
  if (ly < 0) ly = 0;
  if (ry < 0) ry = 0;
  if (closed) {
    tft.pushImage(XIAOK_EYE_L_CLOSED_X, ly, XIAOK_EYE_L_CLOSED_W, XIAOK_EYE_L_CLOSED_H,
                  xiaok_eye_l_closed);
    tft.pushImage(XIAOK_EYE_R_CLOSED_X, ry, XIAOK_EYE_R_CLOSED_W, XIAOK_EYE_R_CLOSED_H,
                  xiaok_eye_r_closed);
  } else {
    tft.pushImage(XIAOK_EYE_L_OPEN_X, ly, XIAOK_EYE_L_OPEN_W, XIAOK_EYE_L_OPEN_H,
                  xiaok_eye_l_open);
    tft.pushImage(XIAOK_EYE_R_OPEN_X, ry, XIAOK_EYE_R_OPEN_W, XIAOK_EYE_R_OPEN_H,
                  xiaok_eye_r_open);
  }
}

// 首屏被整屏重绘后必须调这个：呼吸相位归零、眨眼重新排期。
// 少了它，重绘后第一帧就会按上次的相位跳一下。
void resetIdleAnim() {
  g_breathIdx = 0;
  g_breathDy = 0;
  g_breathAt = millis() + BREATH_STEP_MS;
  g_blinkState = 0;
  g_blinkBurst = 0;
  g_blinkAt = millis() + random(900, 2600);
}

void idleAnimTick() {
#if OTA_ENABLED
  if (g_otaRunning) return;  // 升级时 SPI 让给 flash 写入
#endif
  uint32_t now = millis();

  if ((int32_t)(now - g_breathAt) >= 0) {
    g_breathAt = now + BREATH_STEP_MS;
    g_breathIdx = (g_breathIdx + 1) % (sizeof(BREATH_PATTERN) / sizeof(BREATH_PATTERN[0]));
    uint8_t dy = (uint8_t)BREATH_PATTERN[g_breathIdx];
    if (dy != g_breathDy) {
      g_breathDy = dy;
      drawSplashShifted(dy);
      // 整屏重贴会把闭着的眼睛冲回睁开态，得补一刀（补在位移后的位置上）
      if (g_blinkState) drawEyes(true, dy);
    }
  }

  if ((int32_t)(now - g_blinkAt) < 0) return;
  if (g_blinkState == 0) {
    g_blinkState = 1;
    drawEyes(true, g_breathDy);
    g_blinkAt = now + BLINK_CLOSED_MS;
    return;
  }

  g_blinkState = 0;
  drawEyes(false, g_breathDy);
  uint32_t gap = random(BLINK_GAP_MIN_MS, BLINK_GAP_MAX_MS);
  if (g_blinkBurst > 0) {
    g_blinkBurst--;
    gap = BLINK_QUICK_MS;
  } else if (random(100) < 20) {
    g_blinkBurst = 1;  // 偶尔连眨两下，像真人
    gap = BLINK_QUICK_MS;
  }
  g_blinkAt = now + gap;
}

// RGB565 两像素的通道差之和，粗比够用：只想知道"更像睁眼帧还是闭眼帧"。
static uint32_t rgbDist(uint16_t a, uint16_t b) {
  int ar = (a >> 11) & 0x1F, ag = (a >> 5) & 0x3F, ab = a & 0x1F;
  int br = (b >> 11) & 0x1F, bg = (b >> 5) & 0x3F, bb = b & 0x1F;
  return (uint32_t)(abs(ar - br) + abs(ag - bg) + abs(ab - bb));
}

// 读回眼睛区域，统计"闭眼帧"占比。眨眼只停 110ms，人眼手动敲命令
// 根本抓不住，所以这里连续采样几秒，用比例自证动画真的在跑。
// 采样循环里必须继续调 idleAnimTick：这个函数是阻塞的，不喂它动画就停了，
// 那统计永远是 0——第一版就是这么假阴性了一次。
//
// 窗口必须跟着呼吸位移走。第一版读的是固定的 XIAOK_EYE_L_OPEN_Y，而当时
// drawEyes() 也画在固定坐标，两边同错、互相验证成 err=0，把"眼睛位置没跟随
// 呼吸"这个真 bug 盖掉了。现在额外读一个固定在未位移坐标的对照窗口：
// 修复生效后那里应该是脸颊，与闭眼帧的差异会明显变大（stray_err）。
void testBlink() {
  static uint16_t buf[XIAOK_EYE_L_OPEN_W * XIAOK_EYE_L_OPEN_H];
  const int W = XIAOK_EYE_L_OPEN_W;
  const int H = XIAOK_EYE_L_OPEN_H;
  int closed = 0, total = 0;
  uint32_t openSum = 0, closedSum = 0;
  uint32_t straySum = 0;
  int strayN = 0;

  for (int i = 0; i < 130; i++) {
    idleAnimTick();
    int dyNow = g_breathDy;
    int yTrack = XIAOK_EYE_L_OPEN_Y - dyNow;
    if (yTrack < 0) yTrack = 0;

    tft.readRect(XIAOK_EYE_L_OPEN_X, yTrack, W, H, buf);
    uint32_t dOpen = 0, dClosed = 0;
    for (int p = 0; p < W * H; p++) {
      // SPI 读回的 RGB565 高低字节是反的，两种字节序都认
      uint16_t v = buf[p];
      uint16_t vs = (uint16_t)((v >> 8) | (v << 8));
      uint16_t o = xiaok_eye_l_open[p];
      uint16_t c = xiaok_eye_l_closed[p];
      dOpen += min(rgbDist(v, o), rgbDist(vs, o));
      dClosed += min(rgbDist(v, c), rgbDist(vs, c));
    }
    total++;
    if (dClosed < dOpen) {
      closed++;
      closedSum += dClosed;
    } else {
      openSum += dOpen;
    }

    // 对照窗口：仍停在未位移的 Y。dy>0 时它与闭眼帧的差异应当很大，
    // 说明眼睛确实被搬到了 Y-dy，而不是原地没动。
    if (dyNow > 0) {
      tft.readRect(XIAOK_EYE_L_OPEN_X, XIAOK_EYE_L_OPEN_Y, W, H, buf);
      uint32_t dStray = 0;
      for (int p = 0; p < W * H; p++) {
        uint16_t v = buf[p];
        uint16_t vs = (uint16_t)((v >> 8) | (v << 8));
        uint16_t c = xiaok_eye_l_closed[p];
        dStray += min(rgbDist(v, c), rgbDist(vs, c));
      }
      straySum += dStray;
      strayN++;
    }
    delay(35);
  }
  LOGF("[anim] blink samples=%d closed=%d (%d%%) open_err=%u closed_err=%u\n", total, closed,
       closed * 100 / (total ? total : 1),
       (unsigned)(openSum / (total - closed > 0 ? total - closed : 1)),
       (unsigned)(closedSum / (closed > 0 ? closed : 1)));
  LOGF("[anim] dy=%d stray_err=%u (window kept at undisplayed Y; must be >>0)\n", g_breathDy,
       (unsigned)(straySum / (strayN > 0 ? strayN : 1)));
}

// 读回立绘中央一整列，跟底图在各个位移下比对，反推当前呼吸到了第几档。
// 立绘是纯像素搬运，位移一定能在这一列上留下可测量的差。
void testBreath() {
  static uint16_t col[XIAOK_SPLASH_H];
  const int X = 120;  // 这一列穿过头发和衣服，纹理多，位移能看出来
  LOGF("[anim] breath probe x=%d\n", X);
  for (int i = 0; i < 30; i++) {
    idleAnimTick();
    tft.readRect(X, 0, 1, XIAOK_SPLASH_H, col);
    int bestDy = -1;
    uint32_t bestErr = 0xFFFFFFFF;
    for (int dy = 0; dy <= 3; dy++) {
      uint32_t err = 0;
      for (int y = 0; y < XIAOK_SPLASH_H; y++) {
        // 位移后屏幕 y 处显示的是底图 y+dy 行；越过底边用最后一行补
        int srcY = y + dy;
        if (srcY >= XIAOK_SPLASH_H) srcY = XIAOK_SPLASH_H - 1;
        uint16_t want = xiaok_splash[srcY * XIAOK_SPLASH_W + X];
        uint16_t v = col[y];
        uint16_t vs = (uint16_t)((v >> 8) | (v << 8));
        err += min(rgbDist(v, want), rgbDist(vs, want));
      }
      if (err < bestErr) {
        bestErr = err;
        bestDy = dy;
      }
    }
    LOGF("[anim] frame=%d dy=%d err=%u (firmware says %d)\n", i, bestDy, (unsigned)bestErr,
         g_breathDy);
    delay(200);
  }
}

// 把首屏 240x262 原样经串口吐出来（RGB565 大端），PC 端存 PNG。
// 这是唯一能亲眼确认"屏幕上到底长什么样"的办法：串口日志只能证明它在动，
// 证明不了位移之后有没有露白边、闭眼帧接缝自不自然。
void dumpScreen() {
  Serial.print("IMG 240 262 565\n");
  static uint16_t row[XIAOK_SPLASH_W];
  for (int y = 0; y < XIAOK_SPLASH_H; y++) {
    tft.readRect(0, y, XIAOK_SPLASH_W, 1, row);
    for (int x = 0; x < XIAOK_SPLASH_W; x++) {
      // readRect 读回的高低字节是反的，翻回去再按大端发
      uint16_t v = row[x];
      uint16_t fixed = (uint16_t)((v >> 8) | (v << 8));
      Serial.write((uint8_t)(fixed >> 8));
      Serial.write((uint8_t)(fixed & 0xFF));
    }
  }
  Serial.print("\nIMG_END\n");
}


// 首屏的未读角标。刻意只清这一小块再画：整屏重绘要重发 125KB 立绘，
// 每分钟闪一次比不显示还糟。角标落在立绘下方的空白行，压不到任何文字。
static const int SPLASH_BADGE_X = 228;
static const int SPLASH_BADGE_Y = 286;

void drawSplashBadge() {
  tft.fillRect(140, SPLASH_BADGE_Y - 2, 92, 19, C_PAPER);
  drawUnreadBadge(SPLASH_BADGE_X, SPLASH_BADGE_Y, snap.unread);
}

void drawSplash() {
  tft.fillScreen(C_PAPER);
  // swapBytes 已在 setup 里打开：RGB565 数组要高位先发
  tft.pushImage(0, 0, XIAOK_SPLASH_W, XIAOK_SPLASH_H, xiaok_splash);

  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);

  // 标题与时钟必须同行且互不侵入：tickClock 会用纸色 fillRect 擦那块区域，
  // 一旦压到标题上，每跳一分钟就把字母啃掉一块。所以这里按实测字宽选字号，
  // 而不是写死 Font 4——Font 4 一个字符 20+ px，"HI, I'M K" 会直接顶出屏幕。
  const char *title = "HI, I'M K";
  uint8_t titleFont = 4;
  if (tft.textWidth(title, 4) > SPLASH_CLOCK_X - 12 - 4) titleFont = 2;
  tft.drawString(title, 12, titleFont == 4 ? 262 : 268, titleFont);

  // 常驻时钟：靠右，坐标与 loop 里的 tickClock 必须完全一致。
  g_lastClockText = "";
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString(clockText(false), SPLASH_CLOCK_X, 268, 2);

  tft.setTextColor(C_MUTED, C_PAPER);
  String hint;
  if (g_wifiFailed) {
    // 只有真试过并失败才写 no wifi。刚上电那十几秒是"还没连"，不是"连不上"。
    hint = "no wifi";
  } else {
#if TOUCH_ENABLED || TOUCH_TAP_ENABLED
    hint = g_token.length() ? "tap: open" : "tap: pair";
#else
    hint = g_token.length() ? "BOOT: open" : "BOOT: pair";
#endif
  }
  // 收过一次真实触摸就亮一颗绿点，和提示同一行：这是"触摸有效"的现场证据。
  if (g_touchSeen) tft.fillCircle(5, 301, 3, C_ACCENT);
  tft.drawString(hint, 14, 294, 2);
  // 有未读才画角标。首屏是"随时抬头看一眼"的界面，它必须自己说明有事没看。
  drawSplashBadge();
  drawRight(String("v") + FIRMWARE_VERSION, 228, 306, 1, C_MUTED);

  // 还没校准过才提示这个入口。校准完自动消失，不占地方。
  if (!g_calValid) {
    tft.setTextColor(C_MUTED, C_PAPER);
    tft.drawString("hold BOOT: calibrate", 12, 310, 1);
  }
  // 排在最后：前面任何一次 drawString 都不会被呼吸的整屏重贴带走，
  // 因为重贴只覆盖 0..261，文字全在 262 以下。
  resetIdleAnim();
}

void showSplash() {
  drawSplash();
  g_mode = MODE_SPLASH;
  g_lastInputAt = millis();
}

// 首屏待机轮询：首屏原本只在开机时同步一次，于是"摆在桌上没人碰"的时候
// 反而是最聋的。这里补一条低频心跳——有未读时一分钟一次，没有就五分钟。
// 只改角标不整屏重绘；真来了新通知就交给 consumeNoticeSignal 弹到通知页。
void splashTick() {
  if (!g_token.length()) return;
  if ((int32_t)(millis() - g_nextSplashPoll) < 0) return;
  g_nextSplashPoll = millis() + (snap.unread > 0 ? SPLASH_POLL_ALERT_MS : SPLASH_POLL_IDLE_MS);

  int before = snap.unread;
  if (!fetchSummary()) return;
  if (consumeNoticeSignal()) {
    renderPage();  // 已经是通知页 + 数据页模式
    return;
  }
  if (snap.unread != before) drawSplashBadge();
}

// 每 60ms 读一次触摸裸值，让点按响应控制在 150ms 内。
// XPT2046 在没人按时 Z 只有个位数，真按住会跳到几百以上。
// 悬空接线的特征是 Z 恒定在 4000 上下且 X/Y 全 0。
void probeTouch() {
  if (millis() - g_lastProbeAt < 60) return;
  g_lastProbeAt = millis();

  uint16_t rx = 0, ry = 0;
  tft.getTouchRaw(&rx, &ry);
  uint16_t rz = tft.getTouchRawZ();

  probe.samples++;
  probe.lastX = rx;
  probe.lastY = ry;
  probe.lastZ = rz;
  if (rx < probe.minX) probe.minX = rx;
  if (rx > probe.maxX) probe.maxX = rx;
  if (ry < probe.minY) probe.minY = ry;
  if (ry > probe.maxY) probe.maxY = ry;
  if (rz < probe.minZ) probe.minZ = rz;
  if (rz > probe.maxZ) probe.maxZ = rz;

  if (rx == 0 && ry == 0) probe.zeroXy++;
  if (rz > TOUCH_Z_MIN && rz < TOUCH_Z_MAX) probe.pressed++;
}

// ---------------------------------------------------------------- 校准

// 为什么校准值不写死在编译期：写死意味着「改一次校准值 = 重烧一次固件」，
// 而校准天然是个反复试的过程（划偏了要重来）。存 NVS 后一次烧录能校无数次。

void touchTestStart();  // 前置声明：finishCalibrate 结束时会切过去

// 从 NVS 读校准值。返回 true 表示有可用数据，坐标层才可以启用。
bool loadTouchCal() {
  uint8_t buf[10];
  if (prefs.getBytes("tcal", buf, 10) != 10) {
    LOGF("[cal] none in nvs -> 坐标层未启用，只用压力层\n");
    return false;
  }
  memcpy(g_touchCal, buf, 10);
  // 跨度不合理就当没有：宁可用压力层，也不能拿错坐标去判区域。
  if (g_touchCal[1] <= g_touchCal[0] + CAL_MIN_SPAN ||
      g_touchCal[3] <= g_touchCal[2] + CAL_MIN_SPAN) {
    LOGF("[cal] nvs rejected: span too small\n");
    return false;
  }
  g_calValid = true;
  tft.setTouch(g_touchCal);
  LOGF("[cal] loaded x=%u..%u y=%u..%u rot=%u\n", g_touchCal[0], g_touchCal[1],
       g_touchCal[2], g_touchCal[3], g_touchCal[4]);
  return true;
}

void saveTouchCal() {
  uint8_t buf[10];
  memcpy(buf, g_touchCal, 10);
  prefs.putBytes("tcal", buf, 10);
}

void drawCalScreen() {
  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("CALIBRATE", 12, 12, 4);
  hline(46);
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("Trace all 4 edges", 12, 64, 2);
  tft.drawString("in one stroke.", 12, 86, 2);
  tft.drawString("SAMPLES", 12, 116, 1);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("0", 12, 130, 6);
  tft.fillRect(12, 196, 216, 8, 0xD69A);  // 进度条槽
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("raw x / y / z", 12, 214, 1);
  tft.drawString("c = restart", 12, 292, 1);
}

void drawCalDynamic(uint32_t elapsed) {
  // 采样计数
  tft.fillRect(12, 130, 140, 48, C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString(String(g_calHits), 12, 130, 6);

  // 进度条：走过的时间占总窗口的比例
  int32_t w = (int32_t)(216UL * elapsed / CAL_DURATION_MS);
  if (w < 0) w = 0;
  if (w > 216) w = 216;
  tft.fillRect(12, 196, w, 8, C_ACCENT);
  tft.fillRect(12 + w, 196, 216 - w, 8, 0xD69A);

  // 实时裸值：手指在动时这三个数会跳，说明采样确实在跑
  tft.fillRect(12, 226, 216, 18, C_PAPER);
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("x" + String(g_calRawX), 12, 226, 2);
  tft.drawString("y" + String(g_calRawY), 96, 226, 2);
  tft.drawString("z" + String(g_calRawZ), 180, 226, 2);
}

void startCalibrate() {
  g_mode = MODE_CALIBRATE;
  g_calStartAt = millis();
  g_calLastSampleAt = 0;
  g_calLastDrawAt = 0;
  g_calMinX = 4095;
  g_calMaxX = 0;
  g_calMinY = 4095;
  g_calMaxY = 0;
  g_calHits = 0;
  g_calRawX = 0;
  g_calRawY = 0;
  g_calRawZ = 0;
  drawCalScreen();
  LOGF("\n[cal] trace all 4 edges within %lu s\n", CAL_DURATION_MS / 1000UL);
}

void finishCalibrate() {
  bool ok = g_calHits >= 30 && g_calMaxX > g_calMinX + CAL_MIN_SPAN &&
            g_calMaxY > g_calMinY + CAL_MIN_SPAN;

  LOGF("[cal] done hits=%u x=%u..%u y=%u..%u -> %s\n", (unsigned)g_calHits,
       g_calMinX, g_calMaxX, g_calMinY, g_calMaxY, ok ? "ok" : "FAIL");

  if (!ok) {
    // 划得不够：不写 NVS，保持原来状态，免得把好数据覆盖成坏数据。
    // 提示停留 2 秒后必须重画首屏——否则模式已经回到 SPLASH，
    // 屏幕却还留着 "Cal failed"，而首屏时钟会画到这些字上面。
    screenMessage("Cal failed", "Trace all 4 edges", "Hold BOOT to retry");
    delay(2000);
    showSplash();
    return;
  }

  g_touchCal[0] = g_calMinX;
  g_touchCal[1] = g_calMaxX;
  g_touchCal[2] = g_calMinY;
  g_touchCal[3] = g_calMaxY;
  g_touchCal[4] = 1;
  saveTouchCal();
  g_calValid = true;
  tft.setTouch(g_touchCal);

  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("CALIBRATED", 12, 12, 4);
  hline(46);
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("x " + String(g_touchCal[0]) + ".." + String(g_touchCal[1]), 12, 70, 2);
  tft.drawString("y " + String(g_touchCal[2]) + ".." + String(g_touchCal[3]), 12, 94, 2);
  tft.setTextColor(C_ACCENT, C_PAPER);
  tft.drawString("saved to NVS", 12, 130, 2);
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("going to coord test", 12, 170, 2);
  delay(1200);
  touchTestStart();
}

void calibrateTick() {
  uint32_t now = millis();
  uint32_t elapsed = now - g_calStartAt;

  if (elapsed >= CAL_DURATION_MS) {
    finishCalibrate();
    return;
  }

  if (now - g_calLastSampleAt >= CAL_SAMPLE_MS) {
    g_calLastSampleAt = now;

    uint16_t rx = 0, ry = 0;
    tft.getTouchRaw(&rx, &ry);
    uint16_t rz = tft.getTouchRawZ();
    g_calRawX = rx;
    g_calRawY = ry;
    g_calRawZ = rz;

    // 只采信「确实按着」的点：压力在区间内，且不是悬空时 X/Y 全 0 的假值。
    if (rz > TOUCH_Z_MIN && rz < TOUCH_Z_MAX && !(rx == 0 && ry == 0)) {
      g_calHits++;
      if (rx < g_calMinX) g_calMinX = rx;
      if (rx > g_calMaxX) g_calMaxX = rx;
      if (ry < g_calMinY) g_calMinY = ry;
      if (ry > g_calMaxY) g_calMaxY = ry;
    }
  }

  // 屏幕每 20ms 刷一次太慢（SPI 全屏重绘会拖累采样），压到 200ms。
  if (now - g_calLastDrawAt >= 200) {
    g_calLastDrawAt = now;
    drawCalDynamic(elapsed);
  }
}

// 坐标测试：点哪画哪。校准对不对不用猜——点左上角，十字就该落在左上角。
void touchTestStart() {
  g_mode = MODE_TOUCHTEST;
  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("TOUCH TEST", 12, 12, 4);
  hline(46);
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("Tap anywhere", 12, 64, 2);
  tft.drawString("BOOT = back to K", 12, 262, 1);
  LOGF("[test] tap the screen; screen coords print here\n");
}

void touchTestTick() {
  static uint32_t lastAt = 0;
  static bool wasDown = false;

  uint32_t now = millis();
  if (now - lastAt < 60) return;
  lastAt = now;

  bool down = touchRawPressed();
  if (!down) {
    wasDown = false;
    return;
  }
  if (wasDown) return;  // 按住只算一次
  wasDown = true;

#if TOUCH_ENABLED
  uint16_t x = 0, y = 0;
  if (!tft.getTouch(&x, &y)) {
    LOGF("[test] raw pressed but getTouch() false\n");
    return;
  }
  LOGF("[test] screen x=%u y=%u\n", x, y);

  if (x > 10 && x < 230 && y > 10 && y < 310) {
    tft.drawFastHLine(x - 8, y, 17, TFT_RED);
    tft.drawFastVLine(x, y - 8, 17, TFT_RED);
  }
  tft.fillRect(12, 100, 216, 80, C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextColor(C_INK, C_PAPER);
  tft.drawString("x " + String(x), 12, 100, 4);
  tft.drawString("y " + String(y), 12, 136, 4);
#endif
}


// 向屏幕要芯片 ID。这是判断「显示总线通不通」最硬的办法：
// ILI9341 读 0x04 返回 3 字节，正常是 00 93 41；读到 00/FF 就是 SCK/MOSI/MISO/CS/DC 有问题。
void testDisplay() {
  uint8_t id[3];
  for (int i = 0; i < 3; i++) id[i] = tft.readcommand8(0x04, i);
  uint8_t pm = tft.readcommand8(0x0A, 0);  // Read Display Power Mode

  LOGF("\n[lcd] RDID(0x04)  = %02X %02X %02X  (expect 00 93 41)\n", id[0], id[1], id[2]);
  LOGF("[lcd] RDDPM(0x0A) = %02X  (expect 9C = display on)\n", pm);

  if (id[1] == 0x93 && id[2] == 0x41) {
    LOGF("[lcd] bus OK -> 总线正常，白屏另有原因（多半是 RST 或 DISPON）\n");
  } else if (id[0] == 0x00 && id[1] == 0x00 && id[2] == 0x00) {
    LOGF("[lcd] all zero -> MISO 读到常 0：SCK 或 CS 没通，或 MISO 接错\n");
  } else if (id[0] == 0xFF && id[1] == 0xFF && id[2] == 0xFF) {
    LOGF("[lcd] all FF -> 数据线悬空：MOSI/MISO 虚接，或 CS 未拉低\n");
  } else {
    LOGF("[lcd] unexpected -> 有数据但不合法：查 DC 与 SCK 是否接反\n");
  }
  LOGF("\n");
}

// 一份可复制回传的状态快照，用来判断板子到底卡在哪一层。
const char *modeName() {
  switch (g_mode) {
    case MODE_SPLASH: return "SPLASH";
    case MODE_DATA: return "DATA";
    case MODE_CALIBRATE: return "CAL";
    case MODE_TOUCHTEST: return "TEST";
  }
  return "?";
}

// 读回屏幕像素。中文页整屏都靠位图，串口能证明"字节到了"，但证明不了
// "像素画对了"——极性反了会变成一整块黑底，只有读回来才看得见。
void testInk() {
  if (g_mode != MODE_DATA || (g_page != PAGE_MURMUR && g_page != PAGE_TOPIC)) {
    LOGF("[ink] not on a CJK page (mode=%s page=%d)\n", modeName(), g_page);
    return;
  }
  uint16_t row[32];
  int ink = 0;
  int total = 0;
  // 纵向扫整页 44..244：内容有多有少，固定取一块可能正好落在空白处，
  // 那样 ink=0 只能说明采样点选错了，说明不了位图没画。
  for (int y = 44; y < 244; y += 8) {
    tft.readRect(12, y, 32, 1, row);
    for (int i = 0; i < 32; i++) {
      total++;
      if (row[i] != TFT_WHITE) ink++;
    }
  }
  // 正常落在几个百分点：全 0 是没画上去，接近 100% 是位极性反了。
  LOGF("[ink] page=%d sampled=%d ink=%d\n", g_page, total, ink);
}

// 未读角标的像素探针。C_ALERT 是整块屏上唯一的纯红，数它就知道画没画上。
// 同时统计"字节交换过的红"（0x00F8）：SPI 屏读回时字节序和写进去时不一定一致，
// 只认一种写法会把"画对了但读回来反了"误判成"没画"。
void testAlert() {
  // 缓冲按最宽的一次读取来定（120），不是按第一次用的 52。
  // 前两版一次写成 64、一次写成 96，都小于实际读取宽度，直接踩穿栈让板子重启。
  uint16_t row[128];
  int exact = 0;
  int swapped = 0;
  int nonWhite = 0;
  for (int y = 8; y < 32; y += 2) {
    tft.readRect(60, y, 120, 1, row);
    for (int i = 0; i < 120; i++) {
      if (row[i] == C_ALERT) exact++;
      if (row[i] == (uint16_t)((C_ALERT >> 8) | (C_ALERT << 8))) swapped++;
      if (row[i] != C_PAPER) nonWhite++;
    }
  }
  // 首屏角标单独扫一块：它在立绘下方，不在头部。
  int splashRed = 0;
  for (int y = 282; y < 306; y += 3) {
    tft.readRect(140, y, 92, 1, row);
    for (int j = 0; j < 92; j++) {
      if (row[j] == C_ALERT || row[j] == (uint16_t)((C_ALERT >> 8) | (C_ALERT << 8))) splashRed++;
    }
  }
  uint16_t atBadge[1];
  uint16_t atBlank[1];
  tft.readRect(96, 18, 1, 1, atBadge);   // 角标正中间
  tft.readRect(160, 18, 1, 1, atBlank);  // 同一行空白处，做对照
  int badgeW = tft.textWidth("4", 1) + 8;
  LOGF("[alert] mode=%s page=%d unread=%d badge_x=%d..%d exact=%d swapped=%d nonwhite=%d\n",
       modeName(), g_page, snap.unread, 104 - badgeW, 104, exact, swapped, nonWhite);
  LOGF("[alert] splash_red=%d px(96,18)=0x%04X px(160,18)=0x%04X\n", splashRed, atBadge[0],
       atBlank[0]);
}

void logStatus() {
  LOGF("\n--- kflow terminal ---\n");
  LOGF("fw=%s mode=%s page=%d device=%s\n", FIRMWARE_VERSION, modeName(), g_page, DEVICE_ID);
  LOGF("wifi=%d rssi=%d ip=%s failed=%d\n", (int)WiFi.status(), (int)WiFi.RSSI(),
       WiFi.localIP().toString().c_str(), g_wifiFailed ? 1 : 0);
  LOGF("token=%s len=%u\n", g_token.length() ? "yes" : "no", (unsigned)g_token.length());
  LOGF("snap.valid=%d balance=%d unread=%d\n", snap.valid ? 1 : 0, snap.balance, snap.unread);
  // 水位线与提醒窗口：unread 是"有多少没读"，seen 是"最后见过哪条"，
  // attn=1 表示此刻正处在自动亮起的那 20 秒里。
  LOGF("notice unread=%d latest=%d seen=%u attn=%d nextPoll=%lds\n", snap.unread,
       snap.latestId, g_seenNoticeId, g_attnUntil ? 1 : 0,
       (long)((int32_t)(g_nextSplashPoll - millis()) / 1000));
  LOGF("base=%s\n", g_base);
#if OTA_ENABLED
  // 分区实况。OTA 失败最常见的原因不是网络，是"分区表里根本没有第二个槽"，
  // 而那种失败发生时 Update.begin 只会回一句 no partition，看不出全貌。
  // running 应该是 ota_0/ota_1，next 必须是另一个槽；next=NONE 就说明分区表没换。
  {
    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_partition_t *next = esp_ota_get_next_update_partition(nullptr);
    LOGF("ota running=%s@0x%x size=%uK next=%s failUntil=%d\n",
         running ? running->label : "?", running ? (unsigned)running->address : 0u,
         running ? (unsigned)(running->size / 1024) : 0u, next ? next->label : "NONE",
         g_otaFailUntil ? 1 : 0);
  }
#endif
  LOGF("clock=%s now=%s cache=%d offline=%d\n", clockReady() ? "ok" : "none",
       clockText(true).c_str(), g_fromCache ? 1 : 0, g_offline ? 1 : 0);
  LOGF("touch[cal=%d compiled=%d tap=%d seen=%d] samples=%u pressed=%u zeroXy=%u\n",
       g_calValid ? 1 : 0, TOUCH_ENABLED, TOUCH_TAP_ENABLED, g_touchSeen ? 1 : 0,
       (unsigned)probe.samples, (unsigned)probe.pressed, (unsigned)probe.zeroXy);
  // cal=1 才表示坐标层真的可用；compiled=1 只说明代码编译进来了。
  if (g_calValid) {
    LOGF("touch cal x=%u..%u y=%u..%u rot=%u\n", g_touchCal[0], g_touchCal[1],
         g_touchCal[2], g_touchCal[3], g_touchCal[4]);
  } else {
    LOGF("touch cal none -> send 'c' to calibrate\n");
  }
  // nowdown=1 表示此刻认定为「按着」。手指按上去发一次、松开再发一次，两次对比即可。
  LOGF("touch nowdown=%d\n", touchRawPressed() ? 1 : 0);
  LOGF("touch last x=%u y=%u z=%u\n", probe.lastX, probe.lastY, probe.lastZ);
  LOGF("touch range x=%u..%u y=%u..%u z=%u..%u\n", probe.minX, probe.maxX, probe.minY,
       probe.maxY, probe.minZ, probe.maxZ);
  // 首屏排版实测：标题若宽过 (SPLASH_CLOCK_X - 16) 就会被降成 Font 2，
  // 这两个数字能直接证明有没有重叠，不用靠眼睛猜。
  LOGF("layout title(f4)=%d title(f2)=%d clock(f2)=%d limit=%d\n",
       tft.textWidth("HI, I'M K", 4), tft.textWidth("HI, I'M K", 2),
       tft.textWidth("88:88", 2), SPLASH_CLOCK_X - 16);
  // 呼吸的实时状态：dy 是当前位移档，draw 是最近一次整屏重贴耗时。
  // 重贴 122KB，若这个值抖动大或逼近 360ms 的步长，画面就会顿。
  LOGF("anim dy=%d draw=%ums step=%ums blink=%d\n", g_breathDy,
       (unsigned)(g_lastBreathUs / 1000), (unsigned)BREATH_STEP_MS, g_blinkState);
  // 中文页靠服务端位图。blocked=1 通常是服务端没装中文字体（503），
  // 这时板上只会显示 can't load，不会出现豆腐块。
  for (int i = 0; i < 2; i++) {
    const char *name = i == 0 ? "murmur" : "topic";
    LOGF("board[%s] valid=%d failed=%d bytes=%u len=%u heap=%u\n", name,
         g_boards[i].valid ? 1 : 0, g_boards[i].failed ? 1 : 0, (unsigned)BOARD_MAX_BYTES,
         (unsigned)g_boards[i].len, (unsigned)ESP.getFreeHeap());
  }
  LOGF("----------------------\n");
}

void enterData() {
  g_mode = MODE_DATA;
  g_lastInputAt = millis();
  tft.setTextColor(C_MUTED, C_PAPER);
  tft.drawString("syncing...", 12, 298, 2);
  if (!snap.valid || (int32_t)(millis() - g_nextSyncAt) >= 0) {
    syncNow();
  } else {
    renderPage();
  }
}

// 「现在按着没有」——只看压力，不看坐标，所以不需要校准。
// X/Y 同时为 0 是 T_DIN 悬空的典型读数，此时 Z 不可信，一律当未按；
// Z 超过 TOUCH_Z_MAX 也说明线没通（悬空时恒在 4000 上下），同样不算。
bool touchRawPressed() {
  if (probe.lastX == 0 && probe.lastY == 0) return false;
  return probe.lastZ > TOUCH_Z_MIN && probe.lastZ < TOUCH_Z_MAX;
}

// 触摸点按。两层判据，任意一层命中就算一次 tap：
//   TOUCH_ENABLED=1     走校准后的坐标，同时把坐标带出去（分带交互全靠它）
//   TOUCH_TAP_ENABLED=1 只认压力边沿（够用来"点一下跳页"）
//
// outX/outY 拿不到坐标时置 -1：调用方据此判断"这次点按知不知道该点在哪"，
// 而不是拿 (0,0) 去猜——(0,0) 是个合法坐标，猜错就会误判成签到。
//
// 压力这层带一道 armed 门闩：上电时如果本来就是"按着"的状态（触摸线悬空
// 就是这个样子），永不触发；必须先看到一次松手才允许计为点按。
// 当初整块关掉触摸，就是为了防这个误跳过首屏——门闩比"关掉"更细。
bool touchTapped(int *outX = nullptr, int *outY = nullptr) {
  static bool armed = false;
  static bool wasDown = false;
  static uint32_t lastTapAt = 0;

  if (outX) *outX = -1;
  if (outY) *outY = -1;

#if TOUCH_ENABLED || TOUCH_TAP_ENABLED
  uint32_t now = millis();
#endif

#if TOUCH_ENABLED
  // 校准过就走坐标层，并且直接 return：再落到下面的压力层会让一次触摸算两次。
  if (g_calValid) {
    uint16_t x = 0, y = 0;
    if (tft.getTouch(&x, &y) && now - lastTapAt > TAP_DEBOUNCE_MS) {
      lastTapAt = now;
      if (outX) *outX = (int)x;
      if (outY) *outY = (int)y;
      return true;
    }
    return false;
  }
#endif

#if TOUCH_TAP_ENABLED
  static uint8_t streak = 0;
  bool down = touchRawPressed();
  if (!down) {          // 松手：解除消抖，允许下一次点按
    armed = true;
    wasDown = false;
    streak = 0;
    return false;
  }
  if (!armed || wasDown) return false;  // 手一直按着只算一次
  // 连续 N 次采样都超阈值才算按下：噪声是单点毛刺，手指按住会持续几十到几百毫秒。
  if (++streak < TOUCH_TAP_STREAK) return false;
  streak = 0;
  wasDown = true;
  if (now - lastTapAt < TAP_DEBOUNCE_MS) return false;
  lastTapAt = now;
  return true;
#else
  return false;
#endif
}

ButtonEvent pollButton() {
  static bool wasDown = false;
  static uint32_t downAt = 0;
  static bool longFired = false;
  ButtonEvent event = BTN_NONE;

  bool down = digitalRead(PIN_BUTTON) == LOW;
  if (down && !wasDown) {
    downAt = millis();
    longFired = false;
  }
  if (down && !longFired && millis() - downAt > LONG_PRESS_MS) {
    longFired = true;
    event = BTN_LONG;
  }
  if (!down && wasDown && !longFired && millis() - downAt > 40) {
    event = BTN_SHORT;
  }
  wasDown = down;
  return event;
}

void handleRebind() {
  // 先让服务端松绑：只清本地令牌的话，重新配对会被 409「设备已绑定」卡死。
  if (g_token.length() && WiFi.status() == WL_CONNECTED) {
    String ignored;
    httpCall("POST", "/api/terminal/unbind", "", g_token, ignored, 5000);
  }
  prefs.remove("token");
  g_token = "";
  screenMessage("Unbound", "Rebooting to pair again");
  delay(1200);
  ESP.restart();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  // 待机动画的眨眼间隔是随机的。不播种的话每次上电都是同一串节奏，
  // 摆两天就会发现"它每次都是这时候眨"。esp_random 走真随机源。
  randomSeed(esp_random());

  LOGF("\n[boot] kflow terminal fw=%s device=%s\n", FIRMWARE_VERSION, DEVICE_ID);

  tft.init();
  tft.setRotation(0);
  tft.fillScreen(C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setSwapBytes(true);

  prefs.begin("kflow", false);
  g_token = prefs.getString("token", "");

  // 服务地址优先取 NVS（串口 u 写过就以它为准），没有才用编译期默认。
  // 取回来先做一次形状检查：NVS 里可能是上次手滑写坏的半截字符串。
  String savedBase = prefs.getString("base", "");
  if (savedBase.startsWith("http://") || savedBase.startsWith("https://")) {
    strncpy(g_base, savedBase.c_str(), sizeof(g_base) - 1);
    g_base[sizeof(g_base) - 1] = 0;
    LOGF("[base] nvs=%s\n", g_base);
  }

  // 校准值从 NVS 读回，有就立刻生效。没有可用数据时 g_calValid 保持 false，
  // 触摸退回压力层（点哪都算同一次点按），首屏不会被误跳。
  if (!loadTouchCal()) {
    // setTouch 要的是非 const 指针，所以先拷进运行时数组。
    memcpy(g_touchCal, TOUCH_CAL_FALLBACK, 10);
    tft.setTouch(g_touchCal);
    LOGF("[cal] no calibration -> tap layer only\n");
  }
  // 先把上次的数据读进内存：这样断网也能进数据页看到最后一眼。
  loadSnapshotCache();
  // 通知水位线：上次见到的最新 id。0 表示还没有基线，首轮同步时建立。
  g_seenNoticeId = prefs.getUInt("nid", 0);

  // 时区先设好，与有没有网无关；SNTP 等连上 WiFi 再启动。
  clockSetTimezone();

  // 先画小 K，再连网：首屏通电即现，一帧都不等网络。
  // 这时还没联网，提示为 "no wifi"，连上后重画一次换成 "tap to ..."。
  LOGF("[ui] splash token=%s\n", g_token.length() ? "yes" : "no");
  showSplash();

  if (!connectWifi(15000, false)) {
    LOGF("[wifi] failed ssid=%s (will retry quietly)\n", WIFI_SSID);
    drawSplash();  // 首次确实失败了，才把提示改成 no wifi
  } else {
    clockBegin();  // 有网了再启动 SNTP
    drawSplash();  // 联网成功：把 no wifi 换成 tap to pair/open

    // 已配对就静默预热一次：首屏的时钟靠这次拿到的 epoch 才有数，
    // 顺便把缓存刷到最新。失败无副作用，页面不会重绘成别的。
    if (g_token.length() > 0) {
      LOGF("[boot] warmup sync\n");
      if (fetchSummary()) {
        drawSplash();  // 时钟从 --:-- 变成真实时间
      }
#if OTA_ENABLED
      // 自报家门只发一次，放这里而不是 loop：loop 里发就成了心跳。
      // 这条的作用是让服务端记着的 firmware 跟上"它现在真的跑什么"。
      otaReport("ok");
#endif
    }
  }

  // 开机不抢屏：角标已经把这批未读摆在首屏上了，再弹一次通知页是重复打扰。
  // 水位线照常推到最新——否则下一次轮询又会把它当成"刚到"，四十秒后弹一遍。
  g_pendingNotice = false;
  if (snap.latestId > 0 && (uint32_t)snap.latestId > g_seenNoticeId) {
    g_seenNoticeId = (uint32_t)snap.latestId;
    prefs.putUInt("nid", g_seenNoticeId);
  }
  // 首屏第一次轮询往后推 45 秒：开机这段时间刚同步过，没必要马上再问。
  g_nextSplashPoll = millis() + 45000;

#if OTA_ENABLED
  // 开机不立刻查版本：先让首屏和预热同步跑完，再谈升级。
  // 不设这一句的话 millis() 从 0 开始，第一轮 loop 就会撞上检查条件。
  g_otaNextCheckAt = millis() + OTA_BOOT_DELAY_MS;
#endif
  // 注意：从此刻起 loop() 接管，掉线只会静默重连，不会再整屏重绘。
}

void loop() {
#if DEBUG_SERIAL
  // 串口指令：c 进校准，r 清零探针，d 读屏 ID（判断显示总线），s 立即同步，
  // t 进数据页，p 翻一页（中文页会顺带拉一次位图，用来验证 textboard 通不通），
  // g 读回正文像素，a 读回未读角标像素，k 统计眨眼比例，m 反推呼吸位移，
  // b 强制闭眼，n 整屏回传，w 扫 2.4GHz，u 改服务地址，
  // o 查一次 OTA，其它任意字符回状态报告。
  if (Serial.available()) {
    int c = Serial.peek();
    while (Serial.available()) Serial.read();
    if (c == 'c' || c == 'C') {
      startCalibrate();
      return;
    } else if (c == 'r' || c == 'R') {
      probe = TouchProbe();
      g_lastProbeAt = 0;
      LOGF("[probe] reset. press the screen a few times, then send any key.\n");
    } else if (c == 'd' || c == 'D') {
      testDisplay();
    } else if (c == 'o' || c == 'O') {
#if OTA_ENABLED
      // 手动查一次并升级。绕过 15 秒静置判断和 24 小时间隔：
      // 人在板子边上敲这条指令，就是明确要现在升。
      LOGF("[ota] manual trigger\n");
      otaOnce();
#else
      LOGF("[ota] compiled out (OTA_ENABLED=0)\n");
#endif
    } else if (c == 'g' || c == 'G') {
      // 读回中文页的像素：验证位图真的画上去了。
      testInk();
    } else if (c == 'a' || c == 'A') {
      // 读回未读角标的像素：红色是屏上唯一的红，数出来就说明画上了。
      testAlert();
    } else if (c == 'k' || c == 'K') {
      // 读回眼睛区域，看待机动画到底有没有在眨眼。
      testBlink();
    } else if (c == 'm' || c == 'M') {
      // 读回立绘一列，反推呼吸位移到了第几档。
      testBreath();
    } else if (c == 'b' || c == 'B') {
      // 强制闭眼并按住 8 秒，好让 n 把闭眼帧 dump 出来看接缝。
      g_blinkState = 1;
      drawEyes(true, g_breathDy);
      g_blinkAt = millis() + 8000;
      LOGF("[anim] hold closed 8s\n");
    } else if (c == 'n' || c == 'N') {
      // 整屏回传，PC 端存图。
      dumpScreen();
    } else if (c == 'w' || c == 'W') {
      // 扫一遍 2.4GHz 频段：看清目标 SSID 到底在不在、什么加密、多强。
      scanWifi();
    } else if (c == 'u' || c == 'U') {
      // 改服务地址（写 NVS）。上面那句已经把缓冲清空了，所以这里等的是
      // 紧接着发进来的这一行。
      serialSetBase();
    } else if (c == 't' || c == 'T') {
      // 远程进数据页。手不在板子边上时，靠这条指令就能把页面点出来。
      if (g_mode == MODE_DATA) {
        g_page = 0;
        renderPage();
      } else {
        enterData();
      }
      logStatus();
    } else if (c == 'p' || c == 'P') {
      // 远程翻页。刻意不走 enterData：那条路可能触发一次阻塞同步，
      // 而这里只想尽快把下一页画出来。
      if (g_mode != MODE_DATA) {
        g_mode = MODE_DATA;
        g_lastInputAt = millis();
      }
      nextPage();
      logStatus();
    } else if (c == 's' || c == 'S') {
      // 手动同步一次：验证网络与对时通路，不用等 300 秒刷新。
      // 在首屏时不切页，只取数据重画首屏（时钟会立刻更新）；
      // 但真来了新通知就照常弹——这条路径也要能验证主动提醒。
      LOGF("[sync] manual\n");
      if (g_mode == MODE_DATA) {
        syncNow();
      } else {
        fetchSummary();
        if (consumeNoticeSignal()) {
          renderPage();
        } else {
          drawSplash();
        }
      }
      logStatus();
    } else {
      logStatus();
    }
  }
#endif

  // 校准模式自己按 20ms 采样，这里再跑 probeTouch 只是重复占 SPI 总线。
  if (g_mode == MODE_CALIBRATE) {
    calibrateTick();
    return;
  }

  probeTouch();  // 无论什么模式都在采样：触摸没打开时也要能诊断

#if OTA_ENABLED
  // OTA 自己判断该不该动：有令牌、不是校准模式、距上次输入超过 15 秒。
  // 放在模式分发之前，好让它看到的是"这一轮真实的 g_lastInputAt"；
  // 真正的门闩在 otaTick 内部，这里只负责每轮给它一次机会。
  otaTick();
#endif

  // 时钟增量刷新：只重画那一小块，整屏不闪。切页时 drawSplash/renderSnapshot
  // 已经把 g_lastClockText 清空，所以换页后这里会立刻补画一次。
  // 必须带上模式判断，否则数据页的时钟会画到校准屏和测试屏上。
  if (g_mode == MODE_SPLASH) {
    tickClock(SPLASH_CLOCK_X, 268, 2, false, C_INK);
  } else if (g_mode == MODE_DATA && snap.valid) {
    tickClock(12, 258, 2, true, C_INK);
  }

  if (g_mode == MODE_TOUCHTEST) {
    if (pollButton() != BTN_NONE) {  // 任意一次按键都回首屏
      showSplash();
      return;
    }
    touchTestTick();
    return;
  }

  ButtonEvent button = pollButton();
  if (button == BTN_LONG) {
    if (g_mode == MODE_SPLASH) {
      // 首屏长按 = 进校准，不用开电脑发串口命令。
      // 放在 WiFi 断线判断之前：触摸线松了、网也掉了的时候，这是唯一能自救的入口。
      startCalibrate();
      return;
    }
    if (g_mode == MODE_DATA) {
      handleRebind();
    }
  }

  int tapX = -1, tapY = -1;
  bool tapped = touchTapped(&tapX, &tapY);
  if (tapped) g_touchSeen = true;
  if (tapped || button == BTN_SHORT) g_lastInputAt = millis();

  if (WiFi.status() != WL_CONNECTED) {
    g_offline = true;
    g_wifiOk = false;
    static uint32_t nextWifiTry = 0;
    // 静默重连：绝不整屏重绘，否则首屏会被 "Connecting" 每 15 秒盖一次。
    if ((int32_t)(millis() - nextWifiTry) >= 0) {
      nextWifiTry = millis() + WIFI_RETRY_MS;
      if (connectWifi(12000, false)) {
        // 连上就要把 OFFLINE 摘掉，否则页脚会一直标着离线——
        // g_offline 只有 syncNow 成功才会被清，首屏模式压根不触发同步。
        g_offline = false;
        if (!clockReady()) clockBegin();  // 掉线期间没对上，重连后再试一次
        if (g_mode == MODE_DATA) {
          syncNow();
        } else {
          drawSplash();  // 把 "no wifi" 换成 "tap to ..."
        }
      }
    }
    delay(200);
    return;
  }

  if (g_mode == MODE_SPLASH) {
    if (tapped || button == BTN_SHORT) {
      if (g_token.length() == 0) {
        runPairing();     // 内部阻塞，配对成功后返回
        if (g_token.length() == 0) {
          showSplash();   // 没配上，回到首屏等下一次点按
          return;
        }
      }
      enterData();
    } else {
      splashTick();   // 静置时也要知道外面发生了什么
      idleAnimTick(); // 呼吸 + 眨眼：只在首屏跑，数据页不闪
      delay(60);      // 短睡眠保持触摸采样频率，点按才跟手
    }
    return;
  }

  // 数据页：点屏幕按三带分活（上签到 / 中翻页 / 下刷新）；
  // BOOT 短按固定回小 K——它不随分带变，所以永远有一条确定的路能退出；
  // 静置太久也会自己回首屏。
  if (tapped) {
    g_attnUntil = 0;  // 人已经动了，提醒窗口立刻作废，别再抢屏
    if (tapY >= 0) {
      handleZoneTap(tapX, tapY);  // 坐标层可用：真的知道点在哪
    } else {
      nextPage();                 // 没校准：不知道点在哪，只做最无害的那件事
    }
    return;
  }
  if (button == BTN_SHORT) {
    g_attnUntil = 0;
    showSplash();
    return;
  }
  // 主动提醒到点：如果还停在通知页就退回首屏；人已经翻去别处就不打扰。
  if (g_attnUntil && (int32_t)(millis() - g_attnUntil) >= 0) {
    g_attnUntil = 0;
    if (g_page == PAGE_NOTICE) {
      showSplash();
      return;
    }
  }
  if (millis() - g_lastInputAt > IDLE_TO_SPLASH_SECONDS * 1000UL) {
    showSplash();
    return;
  }
  if ((int32_t)(millis() - g_nextSyncAt) >= 0) {
    syncNow();
  } else {
    delay(60);  // 同上：等刷新的空档里也要保持触摸采样
  }
}
