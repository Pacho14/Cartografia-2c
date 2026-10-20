@echo off
title Ritmos — Conectar Celular / iPhone
echo ============================================================
echo   📱 INICIANDO CONEXION SEGURA HTTPS PARA CELULAR / IPHONE
echo ============================================================
echo.
echo Iniciando tunel seguro de alta velocidad (Cloudflare Edge)...
echo.
cd /d "%~dp0"
if exist "cloudflared.exe" (
    echo Abre en Safari de tu iPhone la direccion https://... que saldra abajo:
    echo (No requiere contrasenas ni pantallas de espera, conecta de inmediato)
    echo.
    cloudflared.exe tunnel --url http://127.0.0.1:8000
) else (
    echo Usando localtunnel...
    npx localtunnel --port 8000
)
pause
