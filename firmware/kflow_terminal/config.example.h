// 复制本文件为 config.h，填入你自己的网络与服务地址。
// config.h 已被 .gitignore 忽略，不要把真实密码提交进仓库。
#pragma once

#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASS "your-wifi-password"

// KFlow 服务地址：必须是终端能访问到的地址。
// 本地调试用电脑的局域网 IP，不要写 127.0.0.1（那是电脑自己）。
// 这里只是出厂默认值：设备会优先读 NVS 里的 base 键，串口发 u 可改并持久化，
// 所以 DHCP 换了 IP 不用重烧。
#define KFLOW_BASE "http://192.168.1.10:9000"

// 设备标识：6-64 位 [A-Za-z0-9._:-]，全局唯一。换一块板子就换一个。
#define DEVICE_ID "esp32s3-kflow-desk"

#define FIRMWARE_VERSION "0.9.1"

// OTA：设备自己检查、自己下载、自己换掉自己。
//
// 前提是分区表得有两个 app 槽。用 FlashSize=16M + PartitionScheme=default
// 得到 default_16MB（app0/app1 各 6.25MB）。huge_app 只有一个槽，OTA 起不来。
//
// 关掉它就退回"只能插线烧"的老路子，其余功能不受影响。
#define OTA_ENABLED 1

// 开机后多久第一次查新版本。太快会和首屏联网、配对抢同一条 TCP。
#define OTA_BOOT_DELAY_MS (90UL * 1000UL)

// 之后每隔多久查一次。
#define OTA_CHECK_INTERVAL_MS (24UL * 3600UL * 1000UL)

// 升级失败后的冷却时间。失败通常是网络或分区问题，立即重试只会连着失败。
#define OTA_RETRY_AFTER_FAIL_MS (6UL * 3600UL * 1000UL)

// 服务端下发 refresh_seconds 失效时的兜底刷新间隔。
#define REFRESH_FALLBACK_SECONDS 300

// 背光亮度 0-255（PWM），首版固定常亮。
#define BACKLIGHT_LEVEL 200

// 触摸分两层，各管一件事：
//
//   TOUCH_TAP_ENABLED  「有没有按下去」——只看压力，不看坐标，不需要校准。
//                       没校准时点一下屏幕 = 翻到下一页（不知道点在哪，只能单调）。
//
//   TOUCH_ENABLED      把坐标层编译进来（「按在哪里」）。
//                       注意它只管编译，**实际能不能用取决于有没有校准数据**：
//                       校准值存在 NVS，开机读回；没有就自动退回压力层。
//                       串口发 c 进校准模式，划一圈四边即可，不用重烧。
//                       校准后数据页按三段分带：上签到 / 中翻页 / 下刷新。
//
#define TOUCH_TAP_ENABLED 1
#define TOUCH_ENABLED 1

// 压力判据（XPT2046 裸值）。实测：安静基线 2~100（含毛刺），真按住几百到几千。
// 取 150 高于毛刺峰值；再叠 TOUCH_TAP_STREAK 连续确认，噪声不会误触发。
// 悬空接线的特征是 Z 恒定 ~4000 且 X/Y 全 0——这两种都不算触摸。
#define TOUCH_Z_MIN 150
#define TOUCH_Z_MAX 3950

// 连续多少次采样超阈值才算按下去（每次采样 60ms，2 次约 120ms）
#define TOUCH_TAP_STREAK 2

// 数据页静置多少秒后自动回到小 K 首屏（像屏保）
#define IDLE_TO_SPLASH_SECONDS 60
