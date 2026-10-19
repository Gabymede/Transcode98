# install_all.ps1
# Запуск: powershell -ExecutionPolicy Bypass -File .\install_all.ps1

param(
    [switch]$NonInteractive
)

# -------------------------------------------------------------------
# ГЛОБАЛЬНЫЙ ПЕРЕХВАТЧИК
# -------------------------------------------------------------------
trap {
    Write-Host "`n=============================================" -ForegroundColor Red
    Write-Host " [!!!] КРИТИЧЕСКАЯ ОШИБКА [!!!]" -ForegroundColor Red
    Write-Host "=============================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host "Строка: $($_.InvocationInfo.ScriptLineNumber)" -ForegroundColor DarkGray
    if (-not $NonInteractive) { Read-Host "Нажмите Enter..." }
    exit 1
}

$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"   # ускоряет Invoke-WebRequest

function Write-Step ($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok   ($m) { Write-Host "[+] $m" -ForegroundColor Green }
function Write-Warn ($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Write-Err  ($m) { Write-Host "[X] $m" -ForegroundColor Red }
function Write-Dbg  ($m) { Write-Host "    -> $m" -ForegroundColor DarkGray }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-Command ($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# Обновить PATH текущей сессии из Machine + User (без фильтрации Test-Path,
# чтобы не терять %USERPROFILE%\...-записи; Windows развернёт их при вызове)
function Update-SessionPath {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $items = (@($m, $u) -join ';') -split ';' | Where-Object { $_ }
    $env:Path = ($items | Select-Object -Unique) -join ';'
    Write-Dbg "PATH обновлён для текущей сессии."
}

# Обёртка над нативной командой — проверяет $LASTEXITCODE (try/catch его не ловит)
function Invoke-Checked {
    param(
        [scriptblock]$Command,
        [string]$What
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$What завершился с кодом $LASTEXITCODE"
    }
}

# -------------------------------------------------------------------
# БАННЕР + ПРАВА
# -------------------------------------------------------------------
Write-Host "=============================================" -ForegroundColor White
Write-Host " Transcode98: Установка зависимостей" -ForegroundColor White
Write-Host "=============================================" -ForegroundColor White

if (Test-Admin) {
    Write-Host "[i] Права администратора: есть (machine-scope установка)." -ForegroundColor DarkGray
} else {
    Write-Host "[i] Права администратора: нет (user-scope установка)." -ForegroundColor DarkGray
}

# -------------------------------------------------------------------
# УСТАНОВКА WINGET (если отсутствует)
# -------------------------------------------------------------------
function Get-WinGetUrls {
    $arch = switch ($env:PROCESSOR_ARCHITECTURE) {
        'ARM64' { 'arm64' }
        'AMD64' { 'x64' }
        default { 'x64' }
    }
    $uiVer = "2.8.6"
    return @{
        VCLibs = "https://aka.ms/Microsoft.VCLibs.$arch.14.00.Desktop.appx"
        UIXaml = "https://github.com/microsoft/microsoft-ui-xaml/releases/download/v$uiVer/Microsoft.UI.Xaml.2.8.$arch.appx"
        WinGet = "https://github.com/microsoft/winget-cli/releases/latest/download/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle"
    }
}

function Install-WinGetPackage {
    $u = Get-WinGetUrls
    $dir = $env:TEMP
    $vclibs = Join-Path $dir "VCLibs.appx"
    $uixaml = Join-Path $dir "UIXaml.appx"
    $winget = Join-Path $dir "WinGet.msixbundle"

    try {
        Write-Dbg "Скачивание VCLibs..."
        Invoke-WebRequest -Uri $u.VCLibs -OutFile $vclibs -UseBasicParsing
        Write-Dbg "Скачивание UI.Xaml..."
        Invoke-WebRequest -Uri $u.UIXaml -OutFile $uixaml -UseBasicParsing
        Write-Dbg "Скачивание WinGet..."
        Invoke-WebRequest -Uri $u.WinGet -OutFile $winget -UseBasicParsing

        Write-Dbg "Установка VCLibs..."
        Add-AppxPackage -Path $vclibs -ForceUpdateFromAnyVersion -ErrorAction Stop
        Write-Dbg "Установка UI.Xaml..."
        Add-AppxPackage -Path $uixaml -ForceUpdateFromAnyVersion -ErrorAction Stop
        Write-Dbg "Установка WinGet..."
        Add-AppxPackage -Path $winget `
            -DependencyPath @($vclibs, $uixaml) `
            -ForceUpdateFromAnyVersion -ErrorAction Stop
    }
    finally {
        Remove-Item $vclibs, $uixaml, $winget -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-WinGet {
    if (Test-Command winget) {
        Write-Ok "WinGet уже установлен."
        & winget --version | Out-Null
        return
    }

    Write-Warn "WinGet не найден. Пробую установить..."

    # 1) Попытка без прав администратора (per-user; работает на многих системах)
    try {
        Install-WinGetPackage
        Update-SessionPath
        if (Test-Command winget) {
            Write-Ok "WinGet установлен (per-user)."
            return
        }
    } catch {
        Write-Warn "Установка без прав администратора не удалась: $($_.Exception.Message)"
    }

    # 2) Требуется повышение прав
    if (-not (Test-Admin)) {
        Write-Warn "Для установки WinGet нужны права администратора."
        Write-Host "Перезапуск с повышением прав..." -ForegroundColor Yellow
        Start-Sleep -Seconds 2

        $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        if ($NonInteractive) { $argList += " -NonInteractive" }
        Start-Process powershell -Verb RunAs -ArgumentList $argList
        exit
    }

    # 3) Уже админ — ставим
    Install-WinGetPackage
    Update-SessionPath

    if (-not (Test-Command winget)) {
        throw "WinGet установлен, но команда всё ещё недоступна. Перезапустите терминал/ПК."
    }
    Write-Ok "WinGet успешно установлен."
}

# -------------------------------------------------------------------
# ОБЩАЯ ОБЁРТКА ДЛЯ WINGET
# -------------------------------------------------------------------
function Invoke-WinGetInstall {
    param(
        [string]$Id,
        [string[]]$ExtraArgs = @()
    )
    $args = @(
        "install", "--id", $Id, "-e", "--silent",
        "--accept-source-agreements", "--accept-package-agreements"
    ) + $ExtraArgs
    & winget @args
    if ($LASTEXITCODE -ne 0) {
        # -1978335189 (0x8A15002B) — "уже установлено / нет применимого обновления"
        if ($LASTEXITCODE -eq -1978335189) {
            Write-Dbg "winget: уже установлено."
            return
        }
        throw "winget install $Id завершился с кодом $LASTEXITCODE"
    }
}

# ===================================================================
# ШАГ 1. WinGet (обязательно ПЕРВЫМ — нужен для Python и FFmpeg)
# ===================================================================
Write-Step "Шаг 1. WinGet"
Ensure-WinGet

# ===================================================================
# ШАГ 2. Python 3.12
# ===================================================================
Write-Step "Шаг 2. Python 3.12"

# Проверяем именно `py -3.12`, а не `python`, чтобы не поймать
# Store-стаб или чужую версию Python.
$pyOk = $false
if (Test-Command py) {
    $ver = & py -3.12 --version 2>&1
    if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3\.12") {
        $pyOk = $true
        Write-Ok "Python 3.12 доступен: $ver"
    }
}

if (-not $pyOk) {
    Write-Warn "Python 3.12 не найден. Устанавливаю..."
    $scope = if (Test-Admin) { "machine" } else { "user" }
    Invoke-WinGetInstall -Id "Python.Python.3.12" -ExtraArgs @("--scope", $scope)
    Update-SessionPath

    if (-not (Test-Command py)) {
        throw "py launcher не найден после установки Python. Перезапустите терминал."
    }
    $ver = & py -3.12 --version 2>&1
    if (-not ($ver -match "Python 3\.12")) {
        throw "Python 3.12 установлен, но `py -3.12` его не видит (вывод: $ver). Перезапустите терминал."
    }
    Write-Ok "Python 3.12 установлен: $ver"
}

# ===================================================================
# ШАГ 3. tkinterdnd2
# ===================================================================
Write-Step "Шаг 3. tkinterdnd2"
try {
    Write-Host "Обновление pip..."
    Invoke-Checked { & py -3.12 -m pip install --upgrade pip } "pip upgrade"
    Write-Host "Установка tkinterdnd2..."
    Invoke-Checked { & py -3.12 -m pip install tkinterdnd2 } "pip install tkinterdnd2"
    Write-Ok "tkinterdnd2 установлен."
} catch {
    Write-Err "Ошибка при установке tkinterdnd2: $($_.Exception.Message)"
    $overallOk = $false
}

# ===================================================================
# ШАГ 4. FFmpeg + FFprobe
# ===================================================================
Write-Step "Шаг 4. FFmpeg + FFprobe"

# ВАЖНО: проверка через Get-Command, а не через `& ffmpeg -version` —
# иначе на системе без ffmpeg ловим CommandNotFoundException
# (trap или устаревший $LASTEXITCODE от предыдущей команды).
if (Test-Command ffmpeg) {
    Write-Ok "FFmpeg уже установлен."
} else {
    Write-Warn "FFmpeg не найден. Устанавливаю Gyan.FFmpeg..."
    Invoke-WinGetInstall -Id "Gyan.FFmpeg"
    Update-SessionPath

    if (-not (Test-Command ffmpeg)) {
        throw "FFmpeg установлен, но не виден в PATH. Перезапустите терминал/ПК."
    }
    Write-Ok "FFmpeg и FFprobe установлены."
}

# ===================================================================
# ФИНАЛЬНАЯ ПРОВЕРКА
# ===================================================================
Write-Step "Финальная проверка"
if ($null -eq $overallOk) { $overallOk = $true }

foreach ($cmd in @("py", "ffmpeg", "ffprobe")) {
    if (Test-Command $cmd) {
        Write-Ok "$cmd найден"
    } else {
        Write-Err "$cmd отсутствует"
        $overallOk = $false
    }
}

# `python` может указывать на Store-стаб или другую версию — не считаем
# это фатальным, но проверяем и предупреждаем.
$pyAll = & python --version 2>&1
if ($pyAll -match "Python 3\.12") {
    Write-Ok "python (команда) => Python 3.12"
} elseif ($pyAll -match "Python") {
    Write-Warn "python => $pyAll (не 3.12). Используйте `py -3.12` для запуска Transcode.py."
} else {
    Write-Warn "python недоступен как команда. Используйте `py -3.12`."
}

& py -3.12 -c "import tkinterdnd2" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "tkinterdnd2 импортируется без ошибок"
} else {
    Write-Err "tkinterdnd2 не импортируется"
    $overallOk = $false
}

if ($overallOk) {
    Write-Host "`n=============================================" -ForegroundColor Green
    Write-Host " ВСЁ ГОТОВО. Можно запускать Transcode.py" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
} else {
    Write-Host "`nЕСТЬ ПРОБЛЕМЫ. Проверьте вывод выше." -ForegroundColor Red
}

if (-not $NonInteractive) {
    Write-Host "`nНажмите Enter, чтобы закрыть окно..."
    Read-Host
}