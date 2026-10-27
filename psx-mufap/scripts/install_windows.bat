@echo off
rem Windows set-up for Day-Trader-PSX (Command Prompt). Safe to run again.
rem   install_windows.bat            data folder, settings, and the daily update at 07:00 Mon-Fri
rem   install_windows.bat 08:30      the same, at another time (your computer's clock)
rem What it does:
rem   1. finds Python 3 (the "py" launcher, else "python")
rem   2. creates your data folder, %USERPROFILE%\pkmarket, with a starter config.json
rem   3. adds a Task Scheduler task "PSX daily update" that runs daily.py on weekdays, and runs it
rem      as soon as the laptop wakes up if it was asleep at that time
rem Nothing here places an order. Remove the task with:  schtasks /Delete /TN "PSX daily update" /F
setlocal
set "HERE=%~dp0"
set "AT=%~1"
if "%AT%"=="" set "AT=07:00"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 isn't installed. Get it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
  echo open a new Command Prompt and run this again.
  exit /b 1
)
for /f "delims=" %%i in ('%PY% -c "import sys; print(sys.executable)"') do set "PYEXE=%%i"
if not defined PYEXE (
  echo "%PY%" didn't start Python ^(the Microsoft Store shortcut?^). Install Python from https://www.python.org/downloads/
  exit /b 1
)
echo Python: %PYEXE%

echo.
echo 1/2 data folder and settings
"%PYEXE%" "%HERE%pkdata.py" init || exit /b 1

echo.
echo 2/2 daily update at %AT%, Monday to Friday
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a = New-ScheduledTaskAction -Execute '%PYEXE%' -Argument ('\"%HERE%daily.py\" --log \"' + $env:USERPROFILE + '\pkmarket\daily.log\"') -WorkingDirectory '%HERE%';" ^
  "$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '%AT%';" ^
  "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries;" ^
  "Register-ScheduledTask -TaskName 'PSX daily update' -Action $a -Trigger $t -Settings $s -Force | Out-Null"
if errorlevel 1 (
  echo Couldn't add the scheduled task; you can still run the update by hand: "%PYEXE%" "%HERE%daily.py"
) else (
  echo Added "PSX daily update". See it in Task Scheduler; test it now with:  schtasks /Run /TN "PSX daily update"
)

echo.
echo Next:
echo   Your watchlist:     "%PYEXE%" "%HERE%watchlist.py" set OGDC PPL MARI HUBC LUCK MEBL --fetch
echo   The menu:           "%PYEXE%" "%HERE%pkm.py"
echo   The first update:   "%PYEXE%" "%HERE%daily.py"
echo   The dashboard:      %USERPROFILE%\pkmarket\dashboard.html  (rebuilt by every update)
echo   Live dashboard:     "%PYEXE%" "%HERE%dashboard.py" serve --allow-live   then open http://127.0.0.1:8787
endlocal
