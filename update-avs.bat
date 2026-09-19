@echo off
chcp 65001 >nul
title AutoVideoStudio 自动更新脚本

:: 切换到当前批处理文件所在目录
cd /d "%~dp0"

echo ==========================================
echo  🔄 AutoVideoStudio GitHub 自动更新脚本
echo ==========================================

:: 检查是否配置了 Git 环境
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo ❌ 未检测到 Git 命令，请确保已安装 Git 并配置了系统环境变量！
    echo.
    pause
    exit /b 1
)

:: 检查是否为 Git 仓库
if not exist ".git" (
    echo.
    echo ❌ 当前目录尚未关联 Git 仓库，请先执行 git clone。
    echo.
    pause
    exit /b 1
)

echo.
echo ==================== 本地最近20个提交记录 ====================
git log --pretty=format:"%%h ^| %%ad ^| %%s" --date=short -n 20
echo.
echo ==============================================================
echo.

:: 获取并显示当前短 commit
for /f "delims=" %%i in ('git rev-parse --short HEAD') do set "CURR_COMMIT=%%i"
echo 当前本地 commit: %CURR_COMMIT%
echo.
echo ⚠️ 请按任意键确认，开始拉取远程最新代码...
pause >nul

echo.
echo ⏳ 正在从远程仓库拉取最新代码...
git pull origin main
if %errorlevel% equ 0 (
    echo.
    echo 🎉 更新成功！代码已是最新版本。
    for /f "delims=" %%j in ('git rev-parse --short HEAD') do set "NEW_COMMIT=%%j"
    echo 👉 更新后 commit: %NEW_COMMIT%

    :: 检查并更新 Python 依赖
    if exist "requirements.txt" (
        echo.
        echo 📦 正在检查并更新依赖包...

        :: 优先使用项目目录下的虚拟环境(若存在)
        if exist "venv\Scripts\pip.exe" (
            venv\Scripts\pip.exe install -r requirements.txt -q
        ) else if exist ".venv\Scripts\pip.exe" (
            .venv\Scripts\pip.exe install -r requirements.txt -q
        ) else (
            where python >nul 2>nul
            if %errorlevel% equ 0 (
                python -m pip install -r requirements.txt -q
            ) else (
                pip install -r requirements.txt -q
            )
        )
    )
) else (
    echo.
    echo ❌ 更新失败，请检查网络或是否存在本地文件冲突！
)

echo.
echo 按任意键退出窗口...
pause >nul
exit /b 0