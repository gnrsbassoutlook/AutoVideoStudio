#!/bin/bash
# AutoVideoStudio - 推送到 GitHub (Mac / Linux)
cd "$(dirname "$0")" || exit 1

REPO_SSH="git@github.com:gnrsbassoutlook/AutoVideoStudio.git"
REPO_HTTPS="https://github.com/gnrsbassoutlook/AutoVideoStudio.git"
BRANCH="main"

hold() { echo ""; read -n 1 -s -r -p "按任意键退出窗口..."; echo ""; }

echo "=========================================="
echo "  AutoVideoStudio  -  推送到 GitHub"
echo "=========================================="

if ! command -v git >/dev/null 2>&1; then
    echo ""
    echo "  [错误] 未检测到 git, 请先安装 Git."
    hold; exit 1
fi

CUR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ -n "$CUR" ] && [ "$CUR" != "HEAD" ]; then BRANCH="$CUR"; fi

if [ ! -d ".git" ]; then
    echo ""
    echo "  未检测到 Git 仓库, 正在初始化 ..."
    git init
    git branch -M "$BRANCH"
fi

echo ""
echo "  [1/4] 检测远程通道 ..."
if git ls-remote "$REPO_SSH" HEAD >/dev/null 2>&1; then
    REMOTE="$REPO_SSH"
    echo "        SSH 可用"
else
    REMOTE="$REPO_HTTPS"
    echo "        SSH 不可用, 自动回退 HTTPS"
fi

RU=$(git remote get-url origin 2>/dev/null)
if [ -z "$RU" ]; then
    git remote add origin "$REMOTE"
elif [ "$RU" != "$REMOTE" ]; then
    echo "        已更新 origin 地址"
    git remote set-url origin "$REMOTE"
fi

echo ""
echo "  [2/4] 拉取远程最新状态 ..."
git fetch origin "$BRANCH" >/dev/null 2>&1
BEHIND=$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null)
[ -z "$BEHIND" ] && BEHIND=0
if [ "$BEHIND" -gt 0 ]; then
    echo "        本地落后 $BEHIND 个提交, 先自动变基 ..."
    if ! git pull --rebase --autostash origin "$BRANCH"; then
        echo "        变基失败, 请手动处理冲突后重试."
        hold; exit 1
    fi
fi

echo ""
echo "  [3/4] 当前改动:"
echo "  --------------------------------------------------------------"
git status -s
echo "  --------------------------------------------------------------"

if [ -z "$(git status --porcelain)" ]; then
    echo ""
    echo "  没有需要提交的改动, 无需推送."
    hold; exit 0
fi

echo ""
read -p "  请输入 Commit 说明 (直接回车 = 自动时间戳): " MSG
if [ -z "$MSG" ]; then MSG="Auto update: $(date '+%Y-%m-%d %H:%M:%S')"; fi

echo ""
echo "  [4/4] 提交并推送到 $BRANCH ..."
git add -A
if ! git commit -m "$MSG"; then
    echo "  提交失败, 已停止."
    hold; exit 1
fi

if ! git push -u origin "$BRANCH"; then
    echo ""
    echo "  推送被拒绝, 尝试拉取合并后重试 ..."
    if git pull --rebase --autostash origin "$BRANCH"; then
        if ! git push -u origin "$BRANCH"; then
            echo "  推送仍然失败, 请检查网络或仓库权限."
            hold; exit 1
        fi
    else
        echo "  合并失败, 请手动解决冲突."
        hold; exit 1
    fi
fi

echo ""
echo "  推送成功."
hold
exit 0
