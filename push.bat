@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo " 🚀 AutoVideoStudio GitHub 自动推送脚本"
echo ==========================================

:: 优先SSH地址，Windows需要配置Git SSH密钥
set REMOTE_SSH=git@github.com:gnrsbassoutlook/AutoVideoStudio.git
:: 如果不想用SSH，取消下一行注释，注释上面一行
:: set REMOTE_SSH=https://github.com/gnrsbassoutlook/AutoVideoStudio.git

if not exist ".git" (
    echo 📦 正在初始化 Git 仓库...
    git init
    git branch -M main
    git remote add origin %REMOTE_SSH%
)

for /f "delims=" %%a in ('git remote get-url origin 2^>nul') do set REMOTE_URL=%%a
if "!REMOTE_URL!"=="" (
    git remote add origin %REMOTE_SSH%
) else if NOT "!REMOTE_URL!"=="%REMOTE_SSH%" (
    echo 🔄 更新origin远程地址为: %REMOTE_SSH%
    git remote set-url origin %REMOTE_SSH%
)

echo.
echo 📊 当前文件改动状态：
git status -s
for /f "delims=" %%i in ('git status -s') do set STATUS_OUT=%%i

echo.
:: 工作区无修改直接退出，不执行提交推送
if "!STATUS_OUT!"=="" (
    echo ✅ 检测到 working tree clean，没有文件改动，无需提交推送。
    echo.
    pause >nul
    exit /b
)

set "msg="
set /p msg=👉 请输入 Commit 说明 (直接回车默认: Auto update):
if "!msg!"=="" (
    for /f %%a in ('powershell Get-Date -Format "yyyy-MM-dd HH:mm:ss"') do set msg=Auto update: %%a
)

echo.
echo ⏳ 正在提交并推送到 GitHub...
git add .
git commit -m "!msg!" --allow-empty
git push -u origin main
if %errorlevel% equ 0 (
    echo.
    echo 🎉 推送成功！代码已同步至 GitHub。
) else (
    echo.
    echo ⚠️ 推送可能遇到冲突，正在尝试拉取合并后重新推送...
    git pull origin main --rebase
    if %errorlevel% neq 0 (
        echo ❌ rebase合并失败，请手动解决冲突！
    ) else (
        git push -u origin main
    )
)

echo.
pause
