@echo off

cd /d C:\AI\alarm_sound

:loop

python alarm_sound.py

echo Alarm Sound stopped. Restart in 10 sec...
timeout /t 10

goto loop