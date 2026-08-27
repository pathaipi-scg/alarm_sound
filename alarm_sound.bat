@echo off

cd /d C:\AI\alarm_sound

call .venv\scripts\activate

:loop

python alarm_sound_v11.py

echo Alarm Sound stopped. Restart in 10 sec...
timeout /t 10

goto loop