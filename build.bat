@echo off
setlocal

set "ROOT=%~dp0"
set "APP_NAME=Larix_Nexus"

tasklist /FI "IMAGENAME eq %APP_NAME%.exe" /NH | findstr /I /C:"%APP_NAME%.exe" >nul
if not errorlevel 1 (
  echo ERROR: Close %APP_NAME%.exe before rebuilding.
  pause
  exit /b 1
)

if exist "%ROOT%build" rmdir /S /Q "%ROOT%build"
if exist "%ROOT%dist" rmdir /S /Q "%ROOT%dist"

py -m PyInstaller "%ROOT%main.py" ^
  --onefile ^
  --clean ^
  --noconsole ^
  --name "%APP_NAME%" ^
  --icon "%ROOT%icon\logo_transparent_multi.ico" ^
  --add-data "%ROOT%icon;icon"

if errorlevel 1 (
  echo ERROR: Build failed.
  pause
  exit /b 1
)

echo Build completed: "%ROOT%dist\%APP_NAME%.exe"
pause
