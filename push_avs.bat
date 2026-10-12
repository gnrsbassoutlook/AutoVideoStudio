@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title AutoVideoStudio - 推送到 GitHub

rem 把 Windows 系统目录提到 PATH 最前, 防止 find / findstr 被 Git Bash 的同名程序顶替
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"

rem ===================== 配置区 =====================
set "REPO_SSH=git@github.com:gnrsbassoutlook/AutoVideoStudio.git"
set "REPO_HTTPS=https://github.com/gnrsbassoutlook/AutoVideoStudio.git"
set "BRANCH=main"
rem ==================================================

echo ==========================================
echo   AutoVideoStudio  -  推送到 GitHub
echo ==========================================

git --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [错误] 未检测到 git, 请先安装 Git for Windows.
    echo.
    pause
    exit /b 1
)

rem ---- 当前分支 ----
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "CURB=%%b"
if defined CURB if not "!CURB!"=="HEAD" set "BRANCH=!CURB!"

if not exist ".git" (
    echo.
    echo   未检测到 Git 仓库, 正在初始化 ...
    git init
    git branch -M !BRANCH!
)

echo.
echo   [1/4] 检测远程通道 ...
set "REMOTE="
git ls-remote "!REPO_SSH!" HEAD >nul 2>&1
if not errorlevel 1 (
    set "REMOTE=!REPO_SSH!"
    echo         SSH 可用
) else (
    set "REMOTE=!REPO_HTTPS!"
    echo         SSH 不可用, 自动回退 HTTPS
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    git remote add origin "!REMOTE!"
) else (
    for /f "delims=" %%u in ('git remote get-url origin') do set "CURU=%%u"
    if /i not "!CURU!"=="!REMOTE!" (
        echo         已更新 origin 地址
        git remote set-url origin "!REMOTE!"
    )
)

echo.
echo   [2/4] 拉取远程最新状态 ...
git fetch origin !BRANCH! 2>nul
set "BEHIND=0"
for /f "delims=" %%c in ('git rev-list --count HEAD..origin/!BRANCH! 2^>nul') do set "BEHIND=%%c"
if !BEHIND! GTR 0 (
    echo         本地落后 !BEHIND! 个提交, 先自动变基 ...
    git pull --rebase --autostash origin !BRANCH!
    if errorlevel 1 (
        echo.
        echo         变基失败, 请手动处理冲突后重试.
        pause
        exit /b 1
    )
)

echo.
echo   [3/4] 当前改动:
echo   --------------------------------------------------------------
git status -s
echo   --------------------------------------------------------------

set "HASCHG="
for /f "delims=" %%i in ('git status --porcelain') do set "HASCHG=1"
if not defined HASCHG (
    echo.
    echo   没有需要提交的改动, 无需推送.
    echo.
    pause
    exit /b 0
)

echo.
set "MSG="
set /p "MSG=  请输入 Commit 说明 (直接回车 = 自动时间戳): "
if not defined MSG set "MSG=Auto update: !date! !time!"

echo.
echo   [4/4] 提交并推送到 !BRANCH! ...
git add -A
git commit -m "!MSG!"
if errorlevel 1 (
    echo.
    echo   提交失败, 已停止.
    pause
    exit /b 1
)

git push -u origin !BRANCH!
if errorlevel 1 (
    echo.
    echo   推送被拒绝, 尝试拉取合并后重试 ...
    git pull --rebase --autostash origin !BRANCH!
    if errorlevel 1 (
        echo   合并失败, 请手动解决冲突.
        pause
        exit /b 1
    )
    git push -u origin !BRANCH!
    if errorlevel 1 (
        echo   推送仍然失败, 请检查网络或仓库权限.
        pause
        exit /b 1
    )
)

echo.
echo   推送成功.
echo.
pause
exit /b 0
