# KFlow 社区首页实施计划

> 设计来源：`docs/superpowers/specs/2026-09-04-kflow-forum-home-design.md`

## 任务 1：建立公开页面路由

修改 `apps/core/pages.py` 与 `apps/core/urls.py`，将 `/forum` 映射到 `static/forum.html`。在 `apps/core/tests.py` 增加页面状态码、关键文本、CSRF Cookie 和静态资源引用测试。

验证：

```bash
.venv/bin/python manage.py test apps.core.tests
```

## 任务 2：实现论坛页面结构与视觉

新增 `static/forum.html` 和 `static/forum.css`，实现：

- KFlow Community 顶部导航；
- 桌面三栏布局；
- 左侧社区分类；
- 中央主题信息流；
- 右侧公告、热门话题、贡献者与统计；
- 平板两栏和手机单栏响应式布局；
- 键盘焦点、状态语义和无脚本降级内容。

## 任务 3：实现浏览器端交互

新增 `static/forum.js`，使用固定示例数据实现：

- 关键词搜索；
- 分类筛选；
- 最新、热门、精华视图；
- 空状态和筛选重置；
- 未开放功能的非阻塞 Toast；
- 移动端导航展开与状态同步。

## 任务 4：接入 KFlow 首页

修改 `static/index.html`，在顶部导航增加指向 `/forum` 的“社区”入口，不改变现有导航和账号逻辑。

## 任务 5：完整验证

执行：

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test apps.core.tests
```

启动本地 Django 后，用浏览器验证桌面与移动端布局、搜索、分类、排序、空状态和 Toast，并检查控制台错误。
