#!/bin/bash
# AutoVideoStudio - 从 GitHub 拉取 (Mac / Linux)
# 列出远程最近 20 条提交, 输入序号选择要同步到哪一条
cd "$(dirname "$0")" || exit 1

REPO_SSH="git@github.com:gnrsbassoutlook/AutoVideoStudio.git"
REPO_HTTPS="https://github.com/gnrsbassoutlook/AutoVideoStudio.git"
BRANCH="main"
LIST_MAX=20

hold() { echo ""; read -n 1 -s -r -p "按任意键退出窗口..."; echo ""; }

echo "=========================================="
echo "  AutoVideoStudio  -  从 GitHub 拉取"
echo "=========================================="

if ! command -v git >/dev/null 2>&1; then
    echo ""
    echo "  [错误] 未检测到 git, 请先安装 Git."
    hold; exit 1
fi

if [ ! -d ".git" ]; then
    echo ""
    echo "  [错误] 当前目录不是 Git 仓库, 请先 git clone."
    hold; exit 1
fi

CUR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ -n "$CUR" ] && [ "$CUR" != "HEAD" ]; then BRANCH="$CUR"; fi

echo ""
echo "  检测远程通道 ..."
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
echo "  正在获取远程最新提交 ..."
if ! git fetch origin "$BRANCH" 2>/dev/null; then
    echo "  获取失败, 请检查网络或仓库权限."
    hold; exit 1
fi

REMOTE_REF="origin/$BRANCH"
SHALIST=$(git log --pretty=format:"%h" -n "$LIST_MAX" "$REMOTE_REF")
if [ -z "$SHALIST" ]; then
    echo "  远程没有提交记录."
    hold; exit 1
fi
CNT=$(printf '%s\n' "$SHALIST" | wc -l | tr -d ' ')
NOW=$(git rev-parse --short HEAD 2>/dev/null)

echo ""
echo "  远程 $REMOTE_REF 最近 $CNT 条提交  (1 = 最新)"
echo "  --------------------------------------------------------------"
git log --pretty=format:"%h   %ad   %an   %s" --date=format:"%m-%d %H:%M" -n "$LIST_MAX" "$REMOTE_REF" \
    | nl -ba -w3 -s '. '
echo "  --------------------------------------------------------------"

CURIDX=$(printf '%s\n' "$SHALIST" | grep -n "^${NOW}$" | cut -d: -f1)
echo ""
echo "  本地当前: $NOW"
if [ -n "$CURIDX" ]; then
    echo "             = 上面第 $CURIDX 条"
else
    echo "             (不在远程前 $CNT 条之内)"
fi

echo ""
read -p "  请输入序号 1-$CNT (回车 = 1 最新, Q = 取消): " PICK
case "$PICK" in
    Q|q) echo ""; echo "  已取消, 本地代码未做任何改动."; hold; exit 0 ;;
esac
[ -z "$PICK" ] && PICK=1

if ! printf '%s' "$PICK" | grep -Eq '^[0-9]+$' || [ "$PICK" -lt 1 ] || [ "$PICK" -gt "$CNT" ]; then
    echo "  输入无效, 只能输入 1 到 $CNT 之间的数字."
    hold; exit 1
fi

TARGET=$(printf '%s\n' "$SHALIST" | sed -n "${PICK}p")
echo ""
echo "  已选择: $TARGET"
echo "          $(git log --pretty=format:'%ad   %an   %s' --date=format:'%m-%d %H:%M' -n 1 "$TARGET")"
echo ""

if [ "$TARGET" = "$NOW" ]; then
    echo "  本地已经停在这个提交上, 无需更新."
    hold; exit 0
fi

OLD=$NOW

if [ -n "$(git status --porcelain)" ]; then
    echo "  检测到本地有未提交改动, 正在自动 stash 暂存 ..."
    if ! git stash push -u -m "avs-autostash"; then
        echo "  stash 失败, 已取消更新."
        hold; exit 1
    fi
    echo "  已存为 stash, 需要取回时执行: git stash pop"
    echo ""
fi

if git merge-base --is-ancestor HEAD "$TARGET"; then
    echo "  快进同步到 $TARGET ..."
    git merge --ff-only "$TARGET"
    RET=$?
else
    echo "  [警告] 所选提交不在本地历史前方, 同步会丢弃本地多出的提交."
    read -p "  确认请输入 YES (其它任意内容取消): " ANS
    if [ "$ANS" != "YES" ] && [ "$ANS" != "yes" ]; then
        echo ""; echo "  已取消, 本地代码未做任何改动."; hold; exit 0
    fi
    git reset --hard "$TARGET"
    RET=$?
fi

if [ "$RET" -ne 0 ]; then
    echo ""
    echo "  同步失败, 请检查是否存在冲突."
    hold; exit 1
fi

echo ""
echo "  同步完成."
echo "  --------------------------------------------------------------"
echo "  更新前: $OLD"
echo "  更新后: $TARGET"
echo ""
echo "  本次变动的文件:"
git diff --name-status "$OLD" "$TARGET"
echo "  --------------------------------------------------------------"

if [ -f "requirements.txt" ]; then
    echo ""
    read -p "  是否同时更新 Python 依赖? (Y/n): " DEP
    if [ "$DEP" != "n" ] && [ "$DEP" != "N" ]; then
        echo ""
        echo "  正在更新依赖 ..."
        if [ -x "venv/bin/pip" ]; then
            venv/bin/pip install -r requirements.txt -q
        elif [ -x ".venv/bin/pip" ]; then
            .venv/bin/pip install -r requirements.txt -q
        elif command -v python3 >/dev/null 2>&1; then
            python3 -m pip install -r requirements.txt -q
        else
            pip install -r requirements.txt -q
        fi
    fi
fi

hold
exit 0
