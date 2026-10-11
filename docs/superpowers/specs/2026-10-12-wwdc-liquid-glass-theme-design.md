# KFlow 前台 WWDC 2025 Liquid Glass 第三皮肤

## 目标

将 `glass` 主题从当前的 Midnight Frost 调整为受 Apple WWDC 2025 启发的 Liquid Glass 视觉：中文为主、英文作辅助说明、强烈但克制的彩色高亮、全屏在线背景图、Bento 卡片层次和轻量动态效果。

白天主题与黑夜主题保持原样。主题切换仍为 `light -> dark -> glass -> light`，并沿用现有 `localStorage` 记忆。主题影响范围与黑夜主题一致：覆盖全部前台页面，不覆盖任何后台页面。

## 不变项

- 不改页面路由、业务数据、接口、文案结构、表单行为和现有页面分布。
- 不改 `static/admin*.html`、后台样式、后台脚本或后台主题表现。
- 不把现有页面重排成新的 WWDC 展示页；WWDC 只作为视觉语言，不新增与 KFlow 业务无关的内容。
- 现有页面中没有统一 `.menu-item` DOM，因此不强行重写 HTML；运行时将现有卡片、列表行、按钮和导航项映射为等价的 Bento / menu-item 视觉状态。

## 视觉系统

### 背景

- 玻璃主题使用一张稳定的 Unsplash 静态在线图作为全屏背景，`cover` 铺满视口，固定定位，叠加深色渐变和 `blur`，避免背景细节干扰文字。
- 叠加少量 SVG 网格、噪点和漂浮粒子；粒子数量有限、透明度低，避免页面变得杂乱。
- 内容层使用半透明，不使用不透明深色大底；无背景图或网络失败时回退到渐变背景。

### Liquid Glass 三层结构

每个玻璃表面由同一组作用层组成，限定在 `:root[data-theme="glass"]`：

1. `::before`：色调遮罩，使用独立的蓝、紫、红、橙光斑，不把不同高亮色互相做渐变过渡。
2. `::after`：顶部和边缘光泽高亮，使用细线、内阴影和高光角度模拟液态玻璃边缘。
3. `.glass-distortion`：由运行时创建的 SVG filter，包含 `feTurbulence + feDisplacementMap`，以低强度作用在玻璃背景层；不影响文字和交互命中区域。

统一参数：`backdrop-filter: blur(24px) saturate(165%)`、白色 10%–22% 细边框、内侧 1px 高光、柔和外阴影。浏览器不支持滤镜时回退为半透明平面和边框。

### 色彩与排版

- 正文和核心数字使用白色；辅助说明使用低饱和白色。
- 红、橙、紫分别作为独立高亮色：单个组件只使用一种高亮色，不做红到橙、橙到紫的跨色渐变。
- 中文核心信息使用大号粗体，英文使用小号、较高字距的辅助标签，例如 `COMMUNITY STATS`、`LIVE DATA`。
- 玻璃主题按需加载 Inter / Poppins 和中文系统无衬线回退；加载失败不影响首屏。

## 组件映射

在不改变布局的前提下，把现有页面组件映射为 Bento 单元：

| 现有组件 | Liquid Glass 处理 |
| --- | --- |
| `.card`、`.panel`、`.hero-wrap`、`.community-intro` | 主 Bento 表面，加入三层玻璃和悬停升起 |
| `.side-card`、`.rankings-panel`、`.store-card` | 次级 Bento 表面，使用更低不透明度和独立色点 |
| `.topic-row`、`.rankings-list li`、`.menu-item` 等列表项 | 等价菜单项，悬停时显示局部光泽和色调遮罩 |
| `.btn`、`.view-tab`、`.store-tab` | 胶囊玻璃控件，激活态使用单一高亮色 |
| `.topbar`、`.forum-header`、下拉菜单、通知面板 | 浮层玻璃，保留原有尺寸、位置和折叠行为 |
| 统计数字、状态徽章、进度条 | 白色大数字 + 独立红/橙/紫信号色，不使用跨色渐变 |

卡片悬停统一使用 `transform: translateY(-4px) scale(1.012)` 和阴影过渡；移动端关闭缩放，只保留边框和光泽变化。

## CDN 与运行时

新增前台共享 `glass-runtime.js`，但只在玻璃主题激活时加载远程资源：

- TailwindCSS v3 Play CDN：关闭 preflight，给现有玻璃表面补充受控 utility class；不改变白天/黑夜基础样式。
- Font Awesome 5 Free：用于主题新增的装饰性图标和状态符号；原有 SVG 结构图标保留其尺寸与语义，避免布局跳动。
- Google Fonts Inter / Poppins：作为英文辅助信息字体，系统字体作为回退。
- Apache ECharts 5：按需加载；仅当页面存在已有数据可视化容器时初始化透明背景图表，线条、坐标轴和提示框使用白色或单一高亮色。没有图表数据的页面不虚构业务图表。

`theme.js` 在 `applyTheme()` 后派发 `kflow:themechange` 事件。运行时监听该事件，首次进入 `glass` 时加载资源并初始化效果，离开 `glass` 时只移除玻璃增强类，不破坏白天/黑夜主题。

## 动效与可访问性

- 使用粒子缓慢漂移、卡片光泽跟随鼠标、主题切换淡入淡出；所有效果支持 `prefers-reduced-motion: reduce`，此时停止位移和粒子动画。
- 玻璃表面文字对比度保持可读，按钮继续使用原有键盘焦点和 `aria` 状态。
- 在线资源失败、浏览器不支持 `backdrop-filter`、SVG filter 或 Canvas 时，页面仍显示可读的半透明卡片。
- 动效层设为 `pointer-events: none`，不改变现有点击区域。

## 验证

1. `light -> dark -> glass -> light` 循环，刷新后主题记忆正确。
2. 1920px、1440px、768px、390px 宽度下检查布局不重排、不横向溢出。
3. 检查首页、社区、论坛、排行榜、统计、学习、积分、商城、产品、登录、服务状态等前台页面的玻璃表现。
4. 检查后台页面没有加载玻璃资源，视觉与行为不变。
5. 检查 CDN 失败和 `prefers-reduced-motion` 回退。
6. 运行 Django check、迁移检查、JS 语法检查、`git diff --check`，并执行现有测试集记录与本次改动相关的结果。
