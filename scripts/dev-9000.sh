#!/bin/bash
# 本地开发服务器（9000）。
#
# 用法：./scripts/dev-9000.sh
# 停止：Ctrl + C
#
# 为什么要有这个脚本：`runserver --noreload` 改了 Python 代码不会重载，
# 而页面 HTML 是每次从磁盘读的 —— 于是会出现「面板是新的、接口是旧的」，
# 表现为点了按钮只提示「保存失败 / 发送失败」。改完后端代码就用它重启。

cd /Users/mac/CODE/kfc-homepage || exit 1
export DEBUG=0
export SITE_BASE_URL="http://127.0.0.1:9000"
exec .venv/bin/python manage.py runserver 127.0.0.1:9000 --noreload
