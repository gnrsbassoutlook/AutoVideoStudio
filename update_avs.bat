@echo off
chcp 65001 >nul
title AutoVideoStudio 自动更新脚本

:: 切换到当前批处理文件所在目录
cd /d "%~dp0"

echo ==========================================
echo   AutoVideoStudio GitHub 自动更新脚本
echo ==========================================

:: 检查 Git 环境
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 未检测到 Git 命令，请确保已安装 Git 并配置了系统环境变量！
    echo.
    pause
    exit /b 1
)

:: 检查是否为 Git 仓库
if not exist ".git" (
    echo.
    echo [ERROR] 当前目录尚未关联 Git 仓库，请先执行 git clone。
    echo.
    pause
    exit /b 1
)

:: 获取当前分支
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"

echo.
echo [*] 正在检查远程仓库是否有新版本...
git fetch origin %BRANCH% >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 连接远程仓库失败，请检查网络或代理设置！
    echo.
    pause
    exit /b 1
)

:: 获取 Commit ID
for /f "delims=" %%l in ('git rev-parse HEAD') do set "LOCAL_HASH=%%l"
for /f "delims=" %%r in ('git rev-parse origin/%BRANCH%') do set "REMOTE_HASH=%%r"

set "LOCAL_SHORT=%LOCAL_HASH:~0,7%"
set "REMOTE_SHORT=%REMOTE_HASH:~0,7%"

echo 当前分支: %BRANCH%
echo 本地版本: %LOCAL_SHORT%
echo 远程最新: %REMOTE_SHORT%

:: 判断是否已是最新
if "%LOCAL_HASH%"=="%REMOTE_HASH%" (
    echo.
    echo ==========================================
    echo [OK] 代码已是最新版本，无需重复拉取！
    echo ==========================================
    echo.
    echo 按任意键退出窗口...
    pause >nul
    exit /b 0
)

:: 展示更新日志
echo.
echo ==================== 待更新的提交记录 ====================
git log --pretty=format:"%%h ^| %%ad ^| %%s" --date=short HEAD..origin/%BRANCH%
echo.
echo ==========================================================
echo.
echo [*] 检测到远程有新版本更新！

:: 检查本地是否存在未提交的修改，避免 pull 冲突中断
set "HAS_MODIFIED=0"
for /f "delims=" %%m in ('git status --porcelain') do set "HAS_MODIFIED=1"

if "%HAS_MODIFIED%"=="1" (
    echo [!] 警告：检测到本地文件有修改，直接更新可能导致冲突中断！
    echo     输入 Y 并回车：强制放弃本地修改，完全以远程最新代码为准（推荐）
    echo     输入 N 并回车：尝试保留本地修改直接合并（可能发生冲突）
    set /p "CHOICE=请选择 [Y/N]: "
    if /i "%CHOICE%"=="Y" (
        echo [*] 正在重置本地修改...
        git reset --hard HEAD
    )
)

echo.
echo 请按任意键确认，开始拉取并合并最新代码...
pause >nul

echo.
echo [*] 正在拉取远程最新代码...
git pull origin %BRANCH%
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 更新失败！如果提示本地冲突，可先手动执行 git reset --hard origin/%BRANCH%
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] 更新成功！当前已是最新版本 (%REMOTE_SHORT%)。

:: 更新依赖
if exist "requirements.txt" (
    echo.
    echo [*] 正在检查并更新依赖包...

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
    echo [*] 依赖检查完成！
)

echo.
echo 按任意键退出窗口...
pause >nul
exit /b 0