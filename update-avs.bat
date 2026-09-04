@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo  🔄 AutoVideoStudio GitHub 自动更新脚本
echo ==========================================

if not exist ".git" (
    echo ❌ 当前目录尚未关联 Git 仓库，请先 git clone。
    pause
    exit /b
)

echo.
echo ==================== 本地最近20个提交记录 ====================
git log --pretty=format:"%%h ^| %%ad ^| %%s" --date=short -n 20
echo ==============================================================
for /f %%i in ('git rev-parse --short HEAD') do set LOCAL_COMMIT=%%i
echo 当前本地 commit: %LOCAL_COMMIT%
echo.
echo 按任意键确认，开始拉取远程最新代码...
pause >nul

echo.
echo ⏳ 正在从远程仓库拉取最新代码...
git pull origin main
if %errorlevel% equ 0 (
    echo.
    echo 🎉 更新成功！代码已是最新版本。
    for /f %%i in ('git rev-parse --short HEAD') do set NEW_COMMIT=%%i
    echo 👉 更新后 commit: %NEW_COMMIT%
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
