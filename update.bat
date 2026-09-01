@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo  🔄 AutoVideoStudio GitHub 自动更新脚本
echo ==========================================

if not exist ".git" (
    echo ❌ 当前目录尚未关联 Git 仓库，请先运行 push.bat。
    pause
    exit /b
)

echo ⏳ 正在从远程仓库拉取最新代码...
git pull origin main

if %errorlevel% equ 0 (
    echo.
    echo 🎉 更新成功！代码已是最新版本。
    if exist "requirements.txt" (
        echo 📦 正在检查并更新依赖包...
        pip install -r requirements.txt -q
    )
) else (
    echo.
    echo ❌ 更新失败，请检查网络或本地文件冲突！
)

echo.
pause