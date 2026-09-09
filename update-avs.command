#!/bin/zsh
# AutoVideoStudio Mac 更新脚本，查看最近20条提交再确认更新
cd "$(dirname "$0")"

echo "=========================================="
echo " 🔄 AutoVideoStudio GitHub 自动更新脚本"
echo "=========================================="

if [ ! -d ".git" ]; then
    echo "❌ 当前目录尚未关联 Git 仓库，请先执行 git clone。"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

echo ""
echo "==================== 本地最近20个提交记录 ===================="
git log --pretty=format:"%h | %ad | %s" --date=short -n 20
echo "=============================================================="
echo ""
echo "当前本地 commit: $(git rev-parse --short HEAD)"
echo ""
read -n 1 -s -r -p "⚠️ 按任意键确认，开始拉取远程最新代码..."

echo ""
echo "⏳ 正在从远程仓库拉取最新代码..."
git pull origin main
RET=$?

if [ $RET -eq 0 ]; then
    echo ""
    echo "🎉 更新成功！代码已是最新版本。"
    echo "👉 更新后 commit: $(git rev-parse --short HEAD)"
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
