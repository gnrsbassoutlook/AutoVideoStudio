@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo  🚀 AutoVideoStudio GitHub 自动推送脚本
echo ==========================================

if not exist ".git" (
    echo 📦 正在初始化 Git 仓库...
    git init
    git branch -M main
    git remote add origin https://github.com/gnrsbassoutlook/AutoVideoStudio.git
)

echo.
echo 📊 当前文件改动状态：
git status -s

echo.
set /p msg=👉 请输入 Commit 说明 (直接回车默认: Auto update): 
if "%msg%"=="" (
    set msg=Auto update: %date% %time%
)

echo.
echo ⏳ 正在提交并推送到 GitHub...
git add .
git commit -m "%msg%"
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo 🎉 推送成功！代码已同步至 GitHub。
) else (
    echo.
    echo ⚠️ 推送可能遇到冲突，正在尝试拉取合并后重新推送...
    git pull origin main --rebase
    git push -u origin main
)

echo.
pause