@echo off
rem Arranque local en Windows: doble clic o "iniciar.bat" en la terminal. Opciones: -Demo, -IA, -SinWorker, -Puerto 8080
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\iniciar.ps1" %*
if errorlevel 1 pause
