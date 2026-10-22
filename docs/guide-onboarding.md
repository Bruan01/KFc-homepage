# 新手指南与首次引导

新手指南 `/guide` 公开可读；首页「发现」菜单和首屏「新手指南」按钮均可进入。2026-10-22 更新为 11 章，补充碎碎念、Emoji、图片、本地草稿、关注/取消关注、列表隐私、@ 提醒、通知定位和可选的小 K AI 回复，并核对注册、激活、积分、下载与显影说明。保留旧章节 ID 和 `kflow:guide:progress:v1`，旧阅读进度继续有效，新增章节需要自行标记完成。

## 引导规则

- 访客首次访问首页，看到屏幕中央的欢迎弹窗，提供「阅读指南」「先逛逛」。提示在显示时就记忆，不要求完成阅读或注册；浏览其他页面不触发访客欢迎。
- 访客记忆保存在当前浏览器的 localStorage，无法使用时尝试 sessionStorage。两者均不可用时仍允许正常浏览，无法保证跨页面记住选择。清除站点数据或更换浏览器后可能再次提示。
- 实际进入 `/guide` 才记录「已打开」。点击链接但取消导航不算阅读，也不将所有章节标记完成。旧版指南中保存的章节阅读进度也视作已打开。
- 成功完成邮箱注册时，为新账号建立 `GuideOnboarding` 记录。访客已打开指南时，注册请求携带 `guide_visited: true`，账号直接记录 visited；仅跳过访客欢迎的，新账号仍可收到一次注册欢迎。
- 新用户随后进入带共享导航的社区页面时，前端领取一次提示；在切换设备后也不会再次展示。已有账号不补发欢迎，新账号的管理员模式不显示此提示。已打开指南的浏览器会将访问状态同步给当前账号。
- 关闭欢迎不影响固定入口。使用原生 dialog 模态弹窗居中显示，背景遮罩，打开时聚焦「阅读指南」，键盘焦点限制在弹窗内。支持「先逛逛」、右上角关闭、Esc 和点击遮罩退出，退出后恢复页面滚动和原焦点（无原焦点时返回导航）。点击「阅读指南」进入指南；所有关闭方式均记住选择，不发积分。

## 状态与接口

`user_guide_onboarding` 每个账号最多一条记录：pending → shown → dismissed；任何状态均可进入 visited，visited 不被之后到达的 shown/dismissed 请求覆盖。无记录的已有账号不显示欢迎。

- `GET /api/user/guide-onboarding`：返回 `state`、`should_prompt`、`claimed`（GET 为 false）。
- `POST /api/user/guide-onboarding`：JSON `{ "action": "shown" | "dismissed" | "visited" }`，仅操作当前登录账号，必须通过 CSRF。shown 用条件更新领取提示，只有领取成功的标签页显示。
- 响应禁止缓存。关闭/访问保存失败不阻断浏览；账号提示领取成功后服务器已经记住 shown，不依赖随后关闭请求才能去重。指南章节阅读进度仍只保存在浏览器，与账号的「已打开」状态分开。

静态共享页面显式引用 `guide-onboarding.js/css`，走现有内容哈希缓存机制；脚本等待 `kflowAuthReady`，先判定登录态再决定访客/账号引导。弹窗使用半透明毛玻璃材质、柔和描边和阴影，分别适配明暗主题；不支持背景模糊或偏好减少透明度时使用实色面板，偏好减少动效时关闭按钮颜色过渡。

## 更新与验证

发布前备份现有 SQLite，再执行 `manage.py migrate`（accounts.0008），重启 Web。无需修改旧账号、积分或内容数据。

```powershell
.venv/Scripts/python.exe manage.py test apps.accounts.test_onboarding apps.accounts.tests apps.core apps.learn --noinput
node scripts/test_guide_onboarding.cjs
node --check static/guide-onboarding.js
```

前端检查脚本通过 DOM stub 验证状态与交互，不代替浏览器视觉验收。人工验证可用无痕窗口访问首页，再分别测试跳过、打开指南、新账号注册和同账号换浏览器登录。
