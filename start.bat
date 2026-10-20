@echo off
title Ritmos — Spatial Rhythm Observer
echo ============================================================
echo   🔬 RITMOS — SPATIAL RHYTHM OBSERVER (Fases 1-5)
echo ============================================================
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    echo Usando entorno virtual venv...
    cd server
    ..\venv\Scripts\python.exe main.py
) else (
    echo No se encontro venv, intentando con python del sistema...
    cd server
    python main.py
)
pause
