#!/bin/bash
cd "$(dirname "$0")"

echo "=========================================="
echo " 🚀 AutoVideoStudio GitHub 自动推送脚本"
echo "=========================================="

# 检查是否已初始化 git
if [ ! -d ".git" ]; then
    echo "📦 正在初始化 Git 仓库..."
    git init
    git branch -M main
    git remote add origin https://github.com/gnrsbassoutlook/AutoVideoStudio.git
fi

# 确保远程分支正确
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if [ -z "$REMOTE_URL" ]; then
    git remote add origin https://github.com/gnrsbassoutlook/AutoVideoStudio.git
fi

echo ""
echo "📊 当前文件改动状态："
git status -s

echo ""
read -p "👉 请输入 Commit 说明 (直接回车默认: Auto update): " msg
if [ -z "$msg" ]; then
    msg="Auto update: $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo ""
echo "⏳ 正在提交并推送到 GitHub..."
git add .
git commit -m "$msg"
git push -u origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 推送成功！代码已同步至 GitHub。"
else
    echo ""
    echo "⚠️ 推送可能遇到冲突，正在尝试拉取合并后重新推送..."
    git pull origin main --rebase
    git push -u origin main
fi

echo ""
read -n 1 -s -r -p "按任意键退出窗口..."
echo ""