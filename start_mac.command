#!/bin/bash
cd "$(dirname "$0")"

echo "======================================"
echo " 正在检查并启动 AutoVideoStudio WebUI "
echo "======================================"

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "【错误】未检测到 python3，请先安装 Python！"
    read -p "按回车键退出..."
    exit 1
fi

# 安装依赖
pip3 install -r requirements.txt -q

# 启动服务
python3 app.py