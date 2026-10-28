# 社区交互更新（2026-10-23）

## 提及与评论

论坛正文/回复与碎碎念正文/评论都仅把作者当前关注、实际存在、双方无屏蔽关系的账号识别为 @。未关注或不存在的名字保留为普通文字，不生成主页链接，也不发送提及通知。服务端返回 `mention_usernames`，前端不再仅凭正则自动造链接。论坛代码块和行内代码不识别 @。

两边共用 `community-editor.js` 的 Emoji 和关注用户选择器。论坛回复还支持最多四张自己的图片或 GIF、纯图片回复与粘贴图片；上传前后均可移除，服务端核验图片所有权。通知可定位具体评论，跨页时自动取对应回复页。

碎碎念评论预览只在图片集合/上传状态变化时重绘，避免手机点击移除按钮时因为焦点切换而丢失点击；移除按钮位于上传状态提示上层。碎碎念复制分享链接采用小 K 成功反馈。

## 论坛发布与背景

论坛发布弹窗使用独立滚动字段区，发布/取消操作保留在底部。Emoji、提及工具放在 Markdown 编辑器外部，不挤占双栏预览。移动端按可视视口高度约束弹窗。

个人主页和个人中心采用清晰的独立封面区；资料文字在主题表面上显示，不再为整张背景覆盖白色蒙层。沿用白天、黑夜、毛玻璃、通透和漫画主题色。

## 投票

发帖时勾选「在文章末尾添加投票」，设置问题、2–10 个不同选项和单选/多选。登录账号可参与一次，重复相同请求不重复计票，不能改投；结果显示参与人数和各选项票数，不公开投票人名单。删除或关闭帖子后不能继续投票。

## 碎碎念日期与新回复

板块默认查看北京时间今天的内容，可选择闭区间起止日期，固定每页 10 条，显示总数、总页数和上一页/下一页。置顶仅在当前筛选范围内优先展示。

「只看有新回复」不受日期限制，返回自己发布或参与过、且在上次阅读后有其他人新评论的碎碎念，排除已删除或被屏蔽的评论。评论加载后通过 POST 提交实际看到的评论 ID，晚到的新回复不会被提前标为已读。

新版界面请求 `/api/murmurs?page=1&start=YYYY-MM-DD&end=YYYY-MM-DD`，或 `page=1&unread=1`；旧的无 page/date 参数游标接口保持兼容，个人中心旧入口仍可读取历史内容。

时间范围默认今天，下拉提供近 1、3、7、30 天（包含今天，按北京时间自然日计算）。点击「自定义」或下拉中的自定义选项后才展开日期输入，点「应用筛选」生效；收起时丢弃未应用的日期。新回复模式不限日期，关闭后恢复原日期范围，每页仍只加载 10 条。

## 设置和私信

个人中心新增「设置」（`/account/settings`），只向本人展示账号、邮箱、密码是否已设置、注册时间和 IP 属地（省份，如「广东」，不展示完整 IP）。密码明文/哈希均不返回。修改前原生弹窗提醒，需验证当前密码和两次新密码，成功后同步管理员密码并撤销其他设备及旧式登录会话。

IP 属地由 `apps/accounts/geoip.py` 解析：本机/内网地址直接判定、不外发；公网地址先查百度开放接口，IPv6 或无结果时回退 ip-api，结果按 IP 缓存 7 天。归属地专用的取 IP 逻辑在 `settings_views.location_ip`：直连来源是本机/内网（Cloudflare Tunnel 或本机反代）时，优先读 Cloudflare 写入的 `CF-Connecting-IP`，其次 `X-Forwarded-For` 第一段；公网直连时只认 `REMOTE_ADDR`，转发头一律忽略。这条路径仅用于展示，验证码与终端配对的限流仍走 `client_ip`（`TRUST_X_FORWARDED_FOR` 控制），因此无需为了显示省份改动 `.env`。

主管理员修改密码后，数据库中的新密码优先于初始环境变量密码。请记住新密码；修改不会重写 `.env`。

用户菜单、个人中心和其他用户主页提供「私信」入口（`/messages`）。支持一对一文字/Emoji、未读提醒、会话列表、每次最多 30 条消息及历史翻页、发送幂等和每分钟 15 条限制。只有双方可读取消息，双向屏蔽会阻止发送，不能给自己或系统生成账号发信。私信不会调用小 K AI，也不自动向用户发运营消息。

## 迁移与检查

新增 accounts 0009、forum 0009、murmurs 0006、messaging 0001、notifications 0003。部署前备份，再执行 `manage.py migrate`，更新静态文件并重启 Web。现有 AI/显影 worker 的运行方式不变。

```text
python manage.py test apps.accounts apps.murmurs apps.community_ai apps.notifications apps.forum apps.core apps.learn apps.messaging --noinput
node scripts/test_community_editor.cjs
node scripts/test_murmur_filters.cjs
node scripts/test_account_settings_ui.cjs
node scripts/test_guide_onboarding.cjs
node scripts/test_xiaok.cjs
python manage.py check
python manage.py makemigrations --check --dry-run
```

自动检查包括权限、私信隔离、投票重复提交/选项校验、图片所有权、日期跨午夜与分页、新回复已读边界、密码同步/其他设备撤销，以及 DOM stub 对 @ 链接、Emoji 和上传移除的验证。DOM stub 不等同于浏览器视觉验收。

## 界面样式

共享的 `community-editor.css` 提供轻量工具栏与提及浮层；浮层在编辑器之外定位，保留键盘选择和窄屏边界处理。`community-ui.css` 统一前台按钮、弹窗操作区与日期筛选，不影响后台管理样式。个人主页/个人中心使用清晰封面、跨封面头像和独立资料区；私信使用头像会话列表、未读标记、左右消息气泡及移动端单列切换。以上界面跟随 light、dark、vibrancy、comic 四个主题变量。
