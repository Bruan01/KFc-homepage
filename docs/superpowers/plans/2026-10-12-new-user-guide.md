# KFlow 新手指南实现计划

## 目标

实现已确认的独立 `/guide` 单页新手旅程，覆盖所有公开页面类别，排除管理员后台；使用静态 HTML、独立 CSS 和轻量 JavaScript，不新增 API 或数据库迁移。

## 实现步骤

### 1. 接入 Django 页面路由

修改：

- `apps/core/pages.py`
- `apps/core/urls.py`

工作：

- 将 `guide` 映射到 `static/guide.html`。
- 增加 `/guide` GET 页面路由。
- 保持既有管理员路径判断和静态文件安全检查不变。

验证：

- Django 可解析 `/guide`。
- `/admin/*` 逻辑不受影响。

### 2. 编写新手指南页面结构与内容

新增：

- `static/guide.html`

工作：

- 沿用 `forum-page`、社区头部、`header.js`、`notifications.js`、`csrf.js` 和 `icons.js`。
- 添加“发现”分组中的新手指南入口和当前页面标识。
- 创建首屏路线图、进度摘要、九个新手章节和结束行动区。
- 每个章节包含新手解释、建议动作、真实页面入口及完成按钮。
- 覆盖首页、论坛、登录、账户、个人主页、排行榜、统计、教程、术语、显影、产品、积分、商店、成就、等级、服务状态和 Cardloom。
- 不出现管理员页面、管理员 API 或后台入口。

### 3. 实现专属视觉系统与响应式布局

新增：

- `static/guide.css`

工作：

- 建立“新手入站地图”视觉层，包括路线节点、章节标记、进度轨道、页面入口卡片和建议动作提示。
- 复用社区页面的颜色、字体、圆角和阴影变量；用独立的 `guide-*` 类隔离样式。
- 桌面端使用固定目录 + 内容主栏；移动端使用顶部横向章节导航。
- 添加 hover、focus-visible、进入动画和减少动画模式。
- 确保窄屏没有横向溢出，并保证长文本和路径可读。

### 4. 实现目录、滚动和完成进度

新增：

- `static/guide.js`

工作：

- 使用 `IntersectionObserver` 更新当前章节和目录状态。
- 支持目录点击滚动、键盘操作和移动端导航。
- 使用稳定的 localStorage key 保存已完成章节和最近章节。
- 更新顶部与侧栏的完成数量。
- 提供“全部重置”操作，并处理 localStorage 不可用的降级情况。
- 遵循 `prefers-reduced-motion`。

### 5. 把新手指南加入公开导航

修改现有带社区导航的公开页面模板，使“发现”菜单包含 `/guide`：

- `static/forum.html`
- `static/tutorials.html`
- `static/glossary.html`
- `static/achievements.html`
- `static/levels.html`
- `static/rankings.html`
- `static/stats.html`
- `static/external-project.html`
- `static/points.html`
- `static/store.html`
- `static/products.html`
- `static/account.html`

如果某页面导航结构已存在轻微差异，保持该页面现有顺序和文案，仅增加同一入口，避免无关重排。

### 6. 验证与回归检查

命令验证：

- `python manage.py check`
- 现有测试套件。
- `git diff --check`

内容检查：

- 检查 `/guide` 页面中的所有目标路径均存在于当前路由。
- 检查页面文案不包含 `/admin`、后台登录或后台管理入口。
- 检查导航中的新手指南链接均为 `/guide`。

浏览器检查：

- 桌面端首屏、目录跟随、章节完成和真实入口打开行为。
- 移动端布局、横向目录、长文本和按钮可用性。
- 刷新后进度保留，重置后恢复初始状态。
- 键盘 Tab 焦点和减少动画行为。

## 交付结果

- 可访问的 `/guide` 页面。
- 公开导航中的“新手指南”入口。
- 独立的页面样式和交互脚本。
- 路由、内容范围和浏览器行为验证结果。

