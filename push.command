#!/bin/bash
cd "$(dirname "$0")"
echo "=========================================="
echo " 🚀 AutoVideoStudio GitHub 自动推送脚本"
echo "=========================================="

# 【重要】优先使用SSH地址，需要本机配置GitHub SSH密钥
REMOTE_SSH="git@github.com:gnrsbassoutlook/AutoVideoStudio.git"
# 如果不想用SSH，取消下面这行注释，注释上面REMOTE_SSH，换回https
# REMOTE_SSH="https://github.com/gnrsbassoutlook/AutoVideoStudio.git"

# 检查是否已初始化 git
if [ ! -d ".git" ]; then
    echo "📦 正在初始化 Git 仓库..."
    git init
    git branch -M main
    git remote add origin "${REMOTE_SSH}"
fi

# 确保远程分支地址正确
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if [ -z "$REMOTE_URL" ]; then
    git remote add origin "${REMOTE_SSH}"
elif [ "${REMOTE_URL}" != "${REMOTE_SSH}" ]; then
    echo "🔄 更新origin远程地址为: ${REMOTE_SSH}"
    git remote set-url origin "${REMOTE_SSH}"
fi

echo ""
echo "📊 当前文件改动状态："
git status -s
STATUS_OUT=$(git status -s)
echo ""

# 👉 核心修复：工作区无修改直接退出，不执行提交推送，避免触发github鉴权弹窗
if [ -z "${STATUS_OUT}" ]; then
    echo "✅ 检测到 working tree clean，没有文件改动，无需提交推送。"
    echo ""
    read -n 1 -s -r -p "按任意键退出窗口..."
    echo ""
    exit 0
fi

read -p "👉 请输入 Commit 说明 (直接回车默认: Auto update): " msg
if [ -z "$msg" ]; then
    msg="Auto update: $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo ""
echo "⏳ 正在提交并推送到 GitHub..."
git add .

# 允许无变更也不崩溃（防御性）
git commit -m "$msg" --allow-empty

git push -u origin main
PUSH_RET=$?
if [ ${PUSH_RET} -eq 0 ]; then
    echo ""
    echo "🎉 推送成功！代码已同步至 GitHub。"
else
    echo ""
    echo "⚠️ 推送可能遇到冲突，正在尝试拉取合并后重新推送..."
    git pull origin main --rebase
    REBASE_RET=$?
    if [ ${REBASE_RET} -ne 0 ]; then
        echo "❌ rebase合并失败，请手动解决冲突！"
    else
        git push -u origin main
    fi
fi

echo ""
read -n 1 -s -r -p "按任意键退出窗口..."
echo ""
