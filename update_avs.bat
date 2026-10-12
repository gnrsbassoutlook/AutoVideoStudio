@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title AutoVideoStudio - 从 GitHub 拉取

rem 把 Windows 系统目录提到 PATH 最前, 防止 find / findstr 被 Git Bash 的同名程序顶替
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%PATH%"

rem ===================== 配置区 =====================
set "REPO_SSH=git@github.com:gnrsbassoutlook/AutoVideoStudio.git"
set "REPO_HTTPS=https://github.com/gnrsbassoutlook/AutoVideoStudio.git"
set "BRANCH=main"
set "LIST_MAX=20"
rem ==================================================

set "TMPL=%TEMP%\avs_remote_list.txt"
set "TMPS=%TEMP%\avs_remote_sha.txt"

echo ==========================================
echo   AutoVideoStudio  -  从 GitHub 拉取
echo ==========================================

git --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [错误] 未检测到 git, 请先安装 Git for Windows.
    echo.
    pause
    exit /b 1
)

if not exist ".git" (
    echo.
    echo   [错误] 当前目录不是 Git 仓库, 请先 git clone.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "CURB=%%b"
if defined CURB if not "!CURB!"=="HEAD" set "BRANCH=!CURB!"

echo.
echo   检测远程通道 ...
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
echo   正在获取远程最新提交 ...
git fetch origin !BRANCH! 2>nul
if errorlevel 1 (
    echo   获取失败, 请检查网络或仓库权限.
    pause
    exit /b 1
)

git log --pretty=format:"%%h   %%ad   %%an   %%s" --date=format:"%%m-%%d %%H:%%M" -n !LIST_MAX! "origin/!BRANCH!" > "%TMPL%"
git log --pretty=format:"%%h" -n !LIST_MAX! "origin/!BRANCH!" | findstr /n "^" > "%TMPS%"

set "CNT=0"
for /f "usebackq delims=" %%x in ("%TMPS%") do set /a CNT+=1
if !CNT! EQU 0 (
    echo   远程没有提交记录.
    pause
    exit /b 1
)

for /f "delims=" %%h in ('git rev-parse --short HEAD 2^>nul') do set "NOW=%%h"

echo.
echo   远程 origin/!BRANCH! 最近 !CNT! 条提交  (1 = 最新)
echo   --------------------------------------------------------------
findstr /n "^" "%TMPL%"
echo.
echo   --------------------------------------------------------------

set "CURIDX="
for /f "usebackq tokens=1,2 delims=:" %%i in ("%TMPS%") do (
    if "%%j"=="!NOW!" set "CURIDX=%%i"
)
echo.
echo   本地当前: !NOW!
if defined CURIDX (
    echo              = 上面第 !CURIDX! 条
) else (
    echo              (不在远程前 !CNT! 条之内)
)

echo.
set "PICK="
set /p "PICK=  请输入序号 1-!CNT! (回车 = 1 最新, Q = 取消): "
if /i "!PICK!"=="Q" goto CANCEL
if not defined PICK set "PICK=1"

echo !PICK!| findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
    echo   输入无效, 只能输入 1 到 !CNT! 之间的数字.
    pause
    exit /b 1
)
if !PICK! GTR !CNT! (
    echo   超出范围, 只能输入 1 到 !CNT! 之间的数字.
    pause
    exit /b 1
)

set "TARGET="
for /f "usebackq tokens=1,2 delims=:" %%i in ("%TMPS%") do (
    if "%%i"=="!PICK!" set "TARGET=%%j"
)
if not defined TARGET (
    echo   解析提交失败.
    pause
    exit /b 1
)

echo.
echo   已选择:
findstr /n "^" "%TMPL%" | findstr /b "!PICK!:"
echo.

if "!TARGET!"=="!NOW!" (
    echo   本地已经停在这个提交上, 无需更新.
    goto ENDIT
)

for /f "delims=" %%o in ('git rev-parse --short HEAD') do set "OLD=%%o"

set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    echo   检测到本地有未提交改动, 正在自动 stash 暂存 ...
    git stash push -u -m "avs-autostash"
    if errorlevel 1 (
        echo   stash 失败, 已取消更新.
        pause
        exit /b 1
    )
    echo   已存为 stash, 需要取回时执行: git stash pop
    echo.
)

git merge-base --is-ancestor HEAD !TARGET!
if not errorlevel 1 (
    echo   快进同步到 !TARGET! ...
    git merge --ff-only !TARGET!
) else (
    echo   [警告] 所选提交不在本地历史前方, 同步会丢弃本地多出的提交.
    set "ANS="
    set /p "ANS=  确认请输入 YES (其它任意内容取消): "
    if /i not "!ANS!"=="YES" goto CANCEL
    git reset --hard !TARGET!
)

if errorlevel 1 (
    echo.
    echo   同步失败, 请检查是否存在冲突.
    pause
    exit /b 1
)

echo.
echo   同步完成.
echo   --------------------------------------------------------------
echo   更新前: !OLD!
echo   更新后: !TARGET!
echo.
echo   本次变动的文件:
git diff --name-status !OLD! !TARGET!
echo   --------------------------------------------------------------

if exist "requirements.txt" (
    echo.
    set "DEP="
    set /p "DEP=  是否同时更新 Python 依赖? (Y/n): "
    if /i not "!DEP!"=="n" (
        echo.
        echo   正在更新依赖 ...
        if exist "venv\Scripts\pip.exe" (
            venv\Scripts\pip.exe install -r requirements.txt -q
        ) else if exist ".venv\Scripts\pip.exe" (
            .venv\Scripts\pip.exe install -r requirements.txt -q
        ) else (
            python -m pip install -r requirements.txt -q 2>nul || pip install -r requirements.txt -q
        )
    )
)

goto ENDIT

:CANCEL
echo.
echo   已取消, 本地代码未做任何改动.

:ENDIT
del "%TMPL%" >nul 2>&1
del "%TMPS%" >nul 2>&1
echo.
pause
exit /b 0
