@echo off
:: Принудительно включаем UTF-8 для консоли
chcp 65001 >nul
setlocal enabledelayedexpansion

title Transcode98 Dependency Checker
mode con: cols=80 lines=30
color 07

echo ==========================================
echo    TRANSCODE98 - ПРОВЕРКА ЗАВИСИМОСТЕЙ
echo ==========================================
echo.

set FAIL=0

:: 1. Проверка Python
python -V >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Python не найден в PATH.
    set FAIL=1
) else (
    for /f "tokens=*" %%v in ('python -V 2^>^&1') do echo [+] %%v
)

:: 2. Проверка tkinterdnd2
python -c "import tkinterdnd2" >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] Библиотека tkinterdnd2 отсутствует.
    set FAIL=1
) else (
    echo [+] Библиотека tkinterdnd2 установлена
)

:: 3. Проверка ffmpeg и ffprobe
where ffmpeg >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] ffmpeg не найден в PATH.
    set FAIL=1
) else (
    echo [+] ffmpeg найден
)

where ffprobe >nul 2>&1
if !errorlevel! neq 0 (
    echo [X] ffprobe не найден в PATH.
    set FAIL=1
) else (
    echo [+] ffprobe найден
)

:: 4. Проверка кодеков (только если ffmpeg вообще найден)
ffmpeg -version >nul 2>&1
if !errorlevel! equ 0 (
    echo.
    echo Проверка кодеков в FFmpeg...
    
    ffmpeg -hide_banner -encoders 2>&1 | findstr /C:"libsvtav1" >nul
    if !errorlevel! neq 0 ( echo [X] Кодек libsvtav1 ^(AV1^) отсутствует & set FAIL=1 ) else ( echo [+] libsvtav1 ^(AV1^) )
    
    ffmpeg -hide_banner -encoders 2>&1 | findstr /C:"libvpx-vp9" >nul
    if !errorlevel! neq 0 ( echo [X] Кодек libvpx-vp9 ^(VP9^) отсутствует & set FAIL=1 ) else ( echo [+] libvpx-vp9 ^(VP9^) )
    
    ffmpeg -hide_banner -encoders 2>&1 | findstr /C:"libx265" >nul
    if !errorlevel! neq 0 ( echo [X] Кодек libx265 ^(HEVC^) отсутствует & set FAIL=1 ) else ( echo [+] libx265 ^(HEVC^) )
    
    ffmpeg -hide_banner -encoders 2>&1 | findstr /C:"libopus" >nul
    if !errorlevel! neq 0 ( echo [X] Кодек libopus отсутствует & set FAIL=1 ) else ( echo [+] libopus )
)

echo.
if !FAIL! neq 0 (
    color 0C
    echo ==========================================
    echo   ИТОГ: ЗАВИСИМОСТИ НЕ НАЙДЕНЫ.
    echo ==========================================
) else (
    color 0A
    echo ==========================================
    echo   ИТОГ: ВСЕ ЗАВИСИМОСТИ НА МЕСТЕ.
    echo ==========================================
)

echo.
echo Для выхода нажмите любую клавишу...
pause >nul