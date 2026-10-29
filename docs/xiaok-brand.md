# 小 K 站点接入

2026-10-22：把 `static/xiaok/` 中已生成的素材接入正式本地页面。使用银白、灰蓝、黑色与半透明面板，分别适配明暗主题。角色图片使用原文件，不做水平镜像；外貌规则和生成提示词见 `output/xiaok/`。

## 接入位置

- 首页：正式的纯文字首屏、社区介绍和三个既有发帖/指南/电子书入口，按用户反馈移除大幅人物立绘。角色保留在欢迎引导及需要时出现的状态组件中。
- 欢迎弹窗：举拳应援的 `chibi-cheer-full-v1.png`（完整全身、透明背景、3:4 竖版），保留跳过、Esc、点击遮罩、焦点恢复与一次性引导记录；配色由青绿调整为灰蓝。
- 首页作品流、论坛筛选结果、碎碎念空状态：超 Q 欢迎形象，保留原发帖、清除筛选、重试等操作。
- 论坛成功反馈和碎碎念发布成功：超 Q 点赞 `chibi-done-v2.png`，配透明毛玻璃提示，分别适配明暗主题；失败提示继续显示错误文字。
- 17 个带共享导航的公开页面：右下角小 K 入口，叉号把角色收成「小 K」小按钮；点击该按钮随时展开，并按本次浏览记住展开/收起状态。图片链接读取官方账号；「新手引导」按钮显式重开欢迎弹窗，已有账号也可以使用。

入口不会自动发帖、评论或请求 AI。网站源码中未发现截图里黄色小鸭的实现，本次新增的是网站自己的小 K 入口。

## 官方主页链接

`GET /api/community/official` 无需登录，仅返回官方账号的 `username`、`display_name`、`profile_url`；未配置时 `account` 为 null。不返回后台目标粉丝数量、邮箱、管理员信息或 AI 配置。

前端用 encodeURIComponent 编码用户名构造个人主页路径，不直接采用接口传回的任意 URL；显示名称仅用于普通文本和可访问名称。后台重新选择官方账号后，下次加载会采用新账号。

未配置账号或接口加载失败时，入口链接到 `/guide`。设置位置为后台「用户管理」的官方账号配置。不会自动创建或提升账号权限。

## 前端与验证

`xiaok-theme.css` 负责首页布局、空状态、成功反馈和浮动入口，规则限定在页面/组件类名；`xiaok.js` 提供共享插图、纯文字反馈和官方身份读取；`window.KflowGuide.openWelcome()` 显式重开欢迎弹窗。

HTML 显式引用共享 JS/CSS，使用内容哈希缓存机制；PNG 使用稳定的 v1/v2 文件名，原素材不覆盖。状态图预留尺寸并延迟加载。图片失败时保留入口与反馈文字；弹窗打开时隐藏浮动入口，窄屏缩小入口。

本地组件体验页：`/static/xiaok/feedback-preview.html`，按钮调用实际空状态与提示组件，纯前端展示，不发帖、不修改数据库。也可以用 `/forum?q=KFLOW_EMPTY_DEMO_20261022` 触发无匹配结果；清除筛选即可回到正常列表。

```powershell
node scripts/test_guide_onboarding.cjs
node scripts/test_xiaok.cjs
.venv/Scripts/python.exe manage.py test apps.accounts.test_brand apps.accounts.test_onboarding --noinput
.venv/Scripts/python.exe manage.py check
```

没有数据迁移；部署需要包含 PNG、共享 CSS/JS 和公开身份接口，并重启 Web。AI worker 无需因页面变化重启。DOM stub 检查不代替浏览器视觉验收；可从实际首页浏览，并通过右下角「新手引导」查看弹窗。
