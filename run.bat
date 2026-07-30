@echo off
REM ============================================================
REM  Citrinitas - One-Click Launcher
REM ============================================================
chcp 65001 > nul

setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
REM  Remove trailing backslash to prevent \" from breaking PowerShell quotes
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%\"

echo.
echo ============================================================
echo    Citrinitas v1.2.0
echo ============================================================
echo.

REM ============================================================
REM  Step 1: Clean up stale processes
REM ============================================================
echo [1/8] Cleaning up stale processes...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\port_cleanup.ps1" -Port 8080
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Could not free port 8080.
    goto error_exit
)
echo   OK

REM 1b. Kill any leftover qdrant.exe
taskkill /F /IM qdrant.exe 2>NUL
timeout /t 1 /nobreak >NUL


REM ============================================================
REM  Step 2: Check Python environment
REM ============================================================
echo.
echo [2/8] Checking Python environment...

if not exist "venv\Scripts\python.exe" (
    echo   [ERROR] Virtual environment not found.
    echo   Please run: install.ps1
    goto error_exit
)

echo   Verifying packages...
venv\Scripts\python.exe -c "import nicegui, qdrant_client, openai, pypdf, docx, watchdog, jieba, yaml, dotenv, paddle, paddleocr" 2>NUL
if %ERRORLEVEL% NEQ 0 (
    echo   [WARNING] Some packages are missing.
    echo   Please run: install.ps1
)

echo   All packages OK


REM ============================================================
REM  Step 3: Config change detection
REM ============================================================
echo.
echo [3/8] Checking config changes...
set "CFG_FILE=%PROJECT_DIR%\pipe_cfg.yaml"
set "CFG_STAMP=%TEMP%\citrinitas_pipe_cfg_stamp.txt"

if not exist "%CFG_FILE%" (
    echo   [!] pipe_cfg.yaml missing. Please run install.ps1.
    goto skip_cfg_check
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\cfg_check.ps1" -CfgFile "%CFG_FILE%" -StampFile "%CFG_STAMP%"

:skip_cfg_check


REM ============================================================
REM  Step 4: Check Ollama
REM ============================================================
echo.
echo [4/8] Checking Ollama...

where ollama >NUL 2>NUL
if %ERRORLEVEL% NEQ 0 (
    echo   [!] Ollama not installed. Vector embedding will not work.
    echo   Install from: https://ollama.com
    goto skip_ollama_check
)

ollama list >NUL 2>NUL
if %ERRORLEVEL% NEQ 0 (
    echo   [!] Ollama installed but not running. Start Ollama first.
    echo   Vector embedding will not work without Ollama.
    goto skip_ollama_check
)

echo   Ollama is running
echo   Checking embed model...
ollama list 2>NUL | findstr /C:"qwen3-embedding" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo   [!] Embed model not found. Please run: ollama pull qwen3-embedding:4b
) else (
    echo   Embed model ready: qwen3-embedding
)

:skip_ollama_check


REM ============================================================
REM  Step 5: Start Qdrant
REM ============================================================
echo.
echo [5/8] Starting Qdrant...

REM Try to start Qdrant (detects, starts if needed, health checks)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\qdrant_helper.ps1" -Action start -ProjectDir "%PROJECT_DIR%" -MaxRetries 30 -RetryDelay 2
if %ERRORLEVEL% EQU 0 goto skip_qdrant

REM start failed - Qdrant not found, ask user to install
echo   [!] Qdrant not found on this system.
echo   Citrinitas needs Qdrant for vector search.
echo.
set "QDRANT_INSTALL=Y"
if /i "!QDRANT_INSTALL!"=="Y" goto do_install_qdrant
goto skip_qdrant

:do_install_qdrant
echo   Installing Qdrant to %PROJECT_DIR%\qdrant\ ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\qdrant_helper.ps1" -Action install -ProjectDir "%PROJECT_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo   [ERROR] Auto-install failed. Please install manually.
    echo   Visit: https://github.com/qdrant/qdrant/releases
    goto error_exit
)

REM Install succeeded, try start again
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\qdrant_helper.ps1" -Action start -ProjectDir "%PROJECT_DIR%" -MaxRetries 30 -RetryDelay 2
if %ERRORLEVEL% EQU 0 goto skip_qdrant

echo   [ERROR] Failed to start Qdrant after install.
echo   Check qdrant.log for details:
if exist "%PROJECT_DIR%\qdrant.log" (
    powershell -NoProfile -Command "Get-Content '%PROJECT_DIR%\qdrant.log' -Tail 20"
)
goto error_exit

:skip_qdrant


REM ============================================================
REM  Step 6: Watch folder info
REM ============================================================
echo.
echo [6/8] Inbox folder: enabled
echo   Drop files into data\inbox\ and they will be auto-ingested.
echo.
echo   Configuration summary:
echo   Web UI:      http://127.0.0.1:8080
echo   Qdrant:      http://127.0.0.1:6333
echo   Embed model: qwen3-embedding:4b
echo   Config:      pipe_cfg.yaml (tuneables) + .env (secrets)


REM ============================================================
REM  Step 7: Qdrant health check before launch
REM ============================================================
echo.
echo [7/8] Health checking Qdrant...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\qdrant_helper.ps1" -Action health -MaxRetries 3 -RetryDelay 2
if %ERRORLEVEL% EQU 0 goto qdrant_ok

REM Qdrant not responding, try to restart
echo   [WARNING] Qdrant is not responding.
echo   Attempting to restart Qdrant...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\qdrant_helper.ps1" -Action start -ProjectDir "%PROJECT_DIR%" -MaxRetries 15 -RetryDelay 2
if %ERRORLEVEL% EQU 0 goto qdrant_ok

REM Restart failed
echo   [ERROR] Failed to restart Qdrant.
echo   Check qdrant.log for details (last 20 lines):
if exist "%PROJECT_DIR%\qdrant.log" (
    powershell -NoProfile -Command "Get-Content '%PROJECT_DIR%\qdrant.log' -Tail 20"
)
goto error_exit

:qdrant_ok
echo   Qdrant OK.


REM ============================================================
REM  Step 8: Start Web UI
REM ============================================================
echo.
echo [8/8] Starting Web UI...
echo.
echo ============================================================
echo   ✅  所有服务就绪，正在启动 Web UI
echo   📍 http://127.0.0.1:8080
echo   📍 浏览器将会自动打开
echo   📍 按 Ctrl+C 停止所有服务
echo ============================================================
echo.

venv\Scripts\python.exe main.py
set EXIT_CODE=%errorlevel%

echo.
echo   Web UI stopped.

REM ============================================================
REM  Graceful shutdown
REM ============================================================
echo.
echo Shutting down services...

tasklist /FI "IMAGENAME eq qdrant.exe" 2>NUL | find /I "qdrant.exe" >NUL
if %ERRORLEVEL% EQU 0 (
    echo   Stopping Qdrant...
    taskkill /FI "IMAGENAME eq qdrant.exe" /F 2>NUL
    echo   Qdrant stopped.
) else (
    echo   Qdrant already stopped.
)

echo.
echo ============================================================
echo   All services stopped. Goodbye!
echo ============================================================
exit /b 0


REM ============================================================
REM  Error handler
REM ============================================================
:error_exit
echo.
echo ============================================================
echo   Script exited with an error. See messages above.
echo ============================================================
exit /b 1
