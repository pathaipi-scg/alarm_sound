@echo off
setlocal
cd /d "%~dp0"
set "ALARM_SOUND_ENV_FILE=%~dp0config\.env.sb11"
if not exist "%ALARM_SOUND_ENV_FILE%" (
    echo Missing environment profile: %ALARM_SOUND_ENV_FILE%
    exit /b 1
)
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0alarm_sound_v11.py"
) else (
    python "%~dp0alarm_sound_v11.py"
)
exit /b %errorlevel%
