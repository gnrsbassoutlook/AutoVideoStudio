@echo off
chcp 936 >nul 2>&1
setlocal
cd /d "%~dp0"
title 剪映专业版 - 5.9 版本锁定守护

set "EXE=%~dp0JianyingPro59Guard.exe"
set "PYFILE=%~dp0JianyingPro59Guard.py"

rem ================= 1. 提升为管理员 =================
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   正在申请管理员权限, 请在 UAC 提示中点击 [是] ...
    echo.
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    exit /b
)

rem ================= 2. 选择运行方式 =================
if exist "%EXE%" goto RUNEXE

rem --- 没有 exe, 退回 Python 源码模式 ---
set "PYX="
where py >nul 2>nul && set "PYX=py -3"
if not defined PYX (where python >nul 2>nul && set "PYX=python")
if not defined PYX (
    if exist "%LocalAppData%\Programs\Python" (
        for /d %%P in ("%LocalAppData%\Programs\Python\Python3*") do (
            if exist "%%P\python.exe" set "PYX=%%P\python.exe"
        )
    )
)
if not defined PYX (
    echo.
    echo   ==========================================================
    echo     未检测到 JianyingPro59Guard.exe, 也未检测到 Python 环境.
    echo.
    echo     请把 JianyingPro59Guard.exe 与本文件放在同一目录,
    echo     或安装 Python 3.8 及以上版本:
    echo        https://www.python.org/downloads/
    echo   ==========================================================
    echo.
    pause
    exit /b 1
)
if not exist "%PYFILE%" (
    echo   找不到 JianyingPro59Guard.py, 请确认与本文件在同一目录.
    pause
    exit /b 1
)

if "%~1"=="" goto NOROOT_PY
if exist "%~1\" goto WITHROOT_PY
%PYX% "%PYFILE%" %*
goto ENDIT

:WITHROOT_PY
%PYX% "%PYFILE%" --root "%~1"
goto ENDIT

:NOROOT_PY
%PYX% "%PYFILE%"
goto ENDIT

rem --- exe 模式 ---
:RUNEXE
if "%~1"=="" goto NOROOT_EXE
if exist "%~1\" goto WITHROOT_EXE
"%EXE%" %*
goto ENDIT

:WITHROOT_EXE
"%EXE%" --root "%~1"
goto ENDIT

:NOROOT_EXE
"%EXE%"

:ENDIT
if errorlevel 1 (
    echo.
    echo   程序返回码非 0, 可能存在异常, 请查看上方提示.
    pause
)
endlocal
