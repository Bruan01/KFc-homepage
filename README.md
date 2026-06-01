# KFlow Homepage

企业产品官网 + 后台管理（单机版，无第三方依赖）。

## 功能
- 官网展示已发布产品
- 产品详情（简介、更新日志、哈希）
- 代码包下载（记录下载次数）
- 后台登录、产品新增/编辑/删除
- 代码包上传并绑定产品

## 目录
- `server.py`：后端服务（API + 静态站点）
- `static/`：前端页面与样式
- `uploads/`：上传的代码包
- `data/homepage.db`：SQLite 数据库

## 启动
```bash
cd homepage
python3 server.py
```

默认地址：`http://127.0.0.1:8088`

## 管理后台
- 登录页：`/admin/login`
- 默认账号：`admin`
- 默认密码：`admin123`

建议生产前通过环境变量覆盖：
```bash
ADMIN_USERNAME=your_admin ADMIN_PASSWORD=your_password PORT=8088 python3 server.py
```

## 上传限制
- 类型：`.zip`, `.rar`, `.7z`, `.tar`, `.gz`, `.tgz`
- 大小：最大 500MB

## 说明
- 仅对 `published` 状态的产品开放下载。
- 删除产品会同时删除其上传包文件。
