#!/bin/bash
cd "$(dirname "$0")"

echo "=========================================="
echo " 🔄 AutoVideoStudio GitHub 自动更新脚本"
echo "=========================================="

if [ ! -d ".git" ]; then
    echo "❌ 当前目录尚未关联 Git 仓库，请先运行 push.command 或 git clone。"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

echo "⏳ 正在从远程仓库拉取最新代码..."
git pull origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 更新成功！代码已是最新版本。"
    if [ -f "requirements.txt" ]; then
        echo "📦 正在检查并更新依赖包..."
        pip3 install -r requirements.txt -q
    fi
else
    echo ""
    echo "❌ 更新失败，请检查网络或是否存在本地文件冲突！"
fi

echo ""
read -n 1 -s -r -p "按任意键退出窗口..."
echo ""