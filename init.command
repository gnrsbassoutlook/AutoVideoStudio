#!/bin/bash
# ==============================================================
#  AutoVideoStudio · macOS 初始化脚本
# --------------------------------------------------------------
#  作用：git clone 之后，一次性给本目录下所有 *.command / *.sh
#        加上可执行权限，并清除 macOS 的「隔离/来源」扩展属性，
#        免去逐个 chmod + xattr 和跨版本的 Gatekeeper 拦截。
#
#  用法：访达里双击 init.command（或右键 → 打开）
#        也可以终端执行：./init.command
#
#  只处理 macOS 脚本，不影响 .bat / .exe / .py 等其他文件。
# ==============================================================

set -u

cd "$(dirname "$0")" || { echo "✗ 无法进入脚本所在目录"; exit 1; }
ROOT="$(pwd)"

if [ "$(uname)" != "Darwin" ]; then
    echo "✗ 这是 macOS 专用脚本，当前系统：$(uname)"
    exit 1
fi

echo "=============================================="
echo " AutoVideoStudio · macOS 初始化"
echo " 目录：${ROOT}"
echo "=============================================="
echo ""
echo "① 赋予可执行权限  ② 清除隔离属性（quarantine）"
echo "----------------------------------------------"

total=0
fixed=0
failed=0

while IFS= read -r -d '' f; do
    rel="${f#./}"
    [ "$rel" = "init.command" ] && continue
    mark=""
    total=$((total + 1))

    # ① 可执行权限
    if chmod +x "$f" 2>/dev/null; then
        fixed=$((fixed + 1))
    else
        failed=$((failed + 1))
        printf "  ✗ %s  （权限修改失败，试试 sudo ./init.command）\n" "$rel"
        continue
    fi

    # ② 清除隔离属性（quarantine 才是触发 Gatekeeper 弹窗的元凶）
    #    注：com.apple.provenance 是 macOS 15 起由系统即时回写的审计属性，
    #        删不掉也不影响双击运行，故不处理。
    for attr in com.apple.quarantine com.apple.FinderInfo; do
        xattr -d "$attr" "$f" 2>/dev/null && mark=" ${mark}(已清除 ${attr})"
    done

    printf "  ✓ %s  %s%s\n" "$rel" "$(ls -l "$f" | cut -c1-10)" "$mark"
done < <(find . -path ./.git -prune -o -type f \( -name '*.command' -o -name '*.sh' \) -print0)

# 目录级兜底：整包清一遍隔离属性
xattr -r -d com.apple.quarantine "$ROOT" >/dev/null 2>&1

echo "----------------------------------------------"
if [ "$total" -eq 0 ]; then
    echo "  未找到任何 .command / .sh 文件，无需处理。"
else
    echo "  共扫描 ${total} 个脚本，成功处理 ${fixed} 个，失败 ${failed} 个。"
fi

# 顺带体检：脚本里有 Windows 换行符会导致 bad interpreter / \r 报错
crlf=0
while IFS= read -r -d '' f; do
    if LC_ALL=C grep -qU $'\r' "$f" 2>/dev/null; then
        printf "  ⚠ %s 含 CRLF 换行，建议转成 LF（可能需要 dos2unix）\n" "${f#./}"
        crlf=$((crlf + 1))
    fi
done < <(find . -path ./.git -prune -o -type f \( -name '*.command' -o -name '*.sh' \) -print0)

echo ""
echo "完成。现在可以双击 start-avs_mac.command 启动了。"
echo ""
read -r -p "按回车键关闭此窗口…" _
exit 0
