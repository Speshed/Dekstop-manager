@echo off
if exist "%~dp0dist\Larix_Nexus.exe" del "%~dp0dist\Larix_Nexus.exe"
py -m PyInstaller main.py ^
    --onefile ^
    --name Larix_Nexus ^
    --noconsole ^
    --icon "%~dp0icon\logo_transparent_multi.ico" ^
    --add-data "%~dp0icon;icon"
pause
