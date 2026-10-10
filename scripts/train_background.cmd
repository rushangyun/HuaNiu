@echo off
REM 夜间挂机训练 YOLO（VOC）—— 脱离终端运行，关窗口/关机后不受影响。
REM
REM 用法（Git Bash 里）：
REM   cmd.exe //c start "" "D:\workbuddy document\2026-10-09-13-21-03\scripts\train_background.cmd"
REM
REM 为什么用 .cmd 而不是直接在 bash 里 & ：
REM   我的 shell 结束（或换模型 Hy4->Hy3）后，挂在它下面的后台进程会被回收。
REM   Windows 的 start 会新开一个窗口，进程归属于新窗口，因此能真正脱离。
REM
REM 为什么要循环重试：
REM   上次训练在 epoch 35 崩了（瞬时 FileNotFoundError），一整夜白跑。
REM   这里最多重试 5 次，每次都 --resume 接着训，崩溃不再浪费整晚。

setlocal

REM 跳到项目根目录（本文件在 scripts\ 下）
cd /d "%~dp0\.."

set PY=%CD%\.venv\Scripts\python.exe
set LOGDIR=%CD%\training\logs
set LOG=%LOGDIR%\train.log

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [%date% %time%] 开始训练（断点续跑模式）>> "%LOG%"

set /a ATTEMPT=0
set MAX_ATTEMPTS=5

:loop
set /a ATTEMPT+=1
echo [%date% %time%] 第 %ATTEMPT%/%MAX_ATTEMPTS% 次运行 >> "%LOG%"

"%PY%" training\train.py --resume --name voc_yolov8n --project runs/train >> "%LOG%" 2>&1

if %ERRORLEVEL%==0 (
    echo [%date% %time%] 训练正常结束 >> "%LOG%"
    goto done
)

echo [%date% %time%] 异常退出 code=%ERRORLEVEL%，准备重试 >> "%LOG%"

if %ATTEMPT% GEQ %MAX_ATTEMPTS% (
    echo [%date% %time%] 已达最大重试次数，停止 >> "%LOG%"
    goto done
)

REM 等一下再重试，避免瞬时故障连续触发
timeout /t 20 /nobreak >nul
goto loop

:done
echo [%date% %time%] 流程结束 >> "%LOG%"
endlocal
