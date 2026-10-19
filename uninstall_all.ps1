# uninstall_all.ps1
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\uninstall_all.ps1
#   powershell -ExecutionPolicy Bypass -File .\uninstall_all.ps1 -RemoveWinGet
#   powershell -ExecutionPolicy Bypass -File .\uninstall_all.ps1 -NonInteractive

param(
    [switch]$RemoveWinGet,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"
$script:failed = $false

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
function Test-Command ($n) { return [bool](Get-Command $n -ErrorAction SilentlyContinue) }

function Update-SessionPath {
    $m = [Environment]::GetEnvironmentVariable("Path","Machine")
    $u = [Environment]::GetEnvironmentVariable("Path","User")
    $env:Path = ((@($m,$u) -join ';') -split ';' | Where-Object { $_ } | Select-Object -Unique) -join ';'
}

function Invoke-WingetUninstall {
    param([string]$Id)

    if (-not (Test-Command winget)) {
        Write-Warn "winget not available."
        return $false
    }

    # attempt 1: plain
    & winget uninstall --id $Id -e --silent --accept-source-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { return $true }
    if ($LASTEXITCODE -eq -1978335212) {   # 0x8A150014 - not installed
        Write-Dbg "winget: '$Id' is not installed."
        return $false
    }

    # attempt 2: --scope user
    Write-Dbg "Retry with --scope user..."
    & winget uninstall --id $Id -e --silent --accept-source-agreements --scope user 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { return $true }

    # attempt 3: --scope machine
    Write-Dbg "Retry with --scope machine..."
    & winget uninstall --id $Id -e --silent --accept-source-agreements --scope machine 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { return $true }

    Write-Warn "winget uninstall '$Id' failed (last exit code $LASTEXITCODE)."
    return $false
}

# Remove stale PATH entries that point to Python 3.12 / FFmpeg locations
# which no longer exist. Only removes entries that (a) no longer exist AND
# (b) match a known pattern. Existing entries are never touched.
function Remove-StalePathEntries {
    $patterns = @('Python312', 'Python\Python3', 'Gyan.FFmpeg', 'ffmpeg')
    $removed = @()

    foreach ($scope in @('Machine', 'User')) {
        $raw = [Environment]::GetEnvironmentVariable("Path", $scope)
        if (-not $raw) { continue }

        $parts = $raw -split ';' | Where-Object { $_ }
        $kept  = @()

        foreach ($p in $parts) {
            $isStale = $false
            if (-not (Test-Path $p -ErrorAction SilentlyContinue)) {
                foreach ($pat in $patterns) {
                    if ($p -like "*$pat*") { $isStale = $true; break }
                }
            }
            if ($isStale) { $removed += "[$scope] $p" }
            else          { $kept    += $p }
        }

        if ($removed.Count -gt 0 -and $kept.Count -ne $parts.Count) {
            $newVal = ($kept -join ';')
            try {
                [Environment]::SetEnvironmentVariable("Path", $newVal, $scope)
                Write-Dbg "Cleaned $scope PATH."
            } catch {
                Write-Warn "Cannot write $scope PATH: $($_.Exception.Message)"
            }
        }
    }

    if ($removed.Count -eq 0) {
        Write-Ok "No stale PATH entries."
    } else {
        $removed | ForEach-Object { Write-Dbg "removed: $_" }
        Write-Ok "Removed $($removed.Count) stale PATH entries."
    }
    Update-SessionPath
}

# ===================================================================
try {
    Write-Host "=============================================" -ForegroundColor White
    Write-Host " Transcode98: Uninstall dependencies" -ForegroundColor White
    Write-Host "=============================================" -ForegroundColor White

    if (Test-Admin) {
        Write-Host "[i] Admin: yes (machine-scope uninstall enabled)." -ForegroundColor DarkGray
    } else {
        Write-Host "[i] Admin: no (user-scope uninstall only)." -ForegroundColor DarkGray
        Write-Warn "Run as Administrator for a complete uninstall."
    }

    # -------------------------------------------------------------------
    # STEP 1. tkinterdnd2  (BEFORE removing Python)
    # -------------------------------------------------------------------
    Write-Step "1. Remove tkinterdnd2"
    if (Test-Command py) {
        & py -3.12 -m pip uninstall -y tkinterdnd2 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "tkinterdnd2 removed."
        } else {
            Write-Warn "pip uninstall tkinterdnd2 failed or package not installed."
        }
    } else {
        Write-Warn "py launcher not found. Skipping (Python likely already removed)."
    }

    # -------------------------------------------------------------------
    # STEP 2. Python 3.12
    # -------------------------------------------------------------------
    Write-Step "2. Remove Python 3.12"
    $pyRemoved = Invoke-WingetUninstall -Id "Python.Python.3.12"
    if ($pyRemoved) {
        Write-Ok "Python 3.12 removed via winget."
    } else {
        Write-Warn "Python 3.12 was not removed by winget."
        Write-Warn "If it was installed manually (python.org), remove it via:"
        Write-Dbg   "Settings -> Apps -> Installed apps -> Python 3.12 -> Uninstall"
    }

    # -------------------------------------------------------------------
    # STEP 3. FFmpeg
    # -------------------------------------------------------------------
    Write-Step "3. Remove FFmpeg"
    $ffRemoved = Invoke-WingetUninstall -Id "Gyan.FFmpeg"
    if ($ffRemoved) {
        Write-Ok "FFmpeg removed via winget."
    } else {
        Write-Warn "FFmpeg was not removed by winget (maybe not installed)."
    }

    # -------------------------------------------------------------------
    # STEP 4. WinGet (optional, opt-in)
    # -------------------------------------------------------------------
    Write-Step "4. WinGet"
    if ($RemoveWinGet) {
        if (Test-Admin) {
            Write-Warn "Removing WinGet (Microsoft.DesktopAppInstaller)..."
            Get-AppxPackage -Name "Microsoft.DesktopAppInstaller" -AllUsers -ErrorAction SilentlyContinue |
                ForEach-Object {
                    try {
                        Remove-AppxPackage -Package $_.PackageFullName -AllUsers -ErrorAction Stop
                        Write-Dbg "Removed $($_.PackageFullName)"
                    } catch {
                        Write-Warn "Failed to remove $($_.PackageFullName): $($_.Exception.Message)"
                    }
                }
            Write-Ok "WinGet removal attempted."
        } else {
            Write-Warn "WinGet removal requires Administrator. Skipped."
            $script:failed = $true
        }
    } else {
        Write-Dbg "WinGet kept (use -RemoveWinGet to remove)."
        Write-Dbg "Note: WinGet is a system component on Windows 11; removing it is not recommended."
    }

    # -------------------------------------------------------------------
    # STEP 5. Clean stale PATH entries
    # -------------------------------------------------------------------
    Write-Step "5. Clean PATH"
    Remove-StalePathEntries

    # -------------------------------------------------------------------
    # FINAL VERIFICATION
    # -------------------------------------------------------------------
    Write-Step "Verification"
    $stillThere = @()
    if (Test-Command py)  { $stillThere += "py" }
    if (Test-Command ffmpeg)  { $stillThere += "ffmpeg" }
    if (Test-Command ffprobe) { $stillThere += "ffprobe" }

    if ($stillThere.Count -eq 0) {
        Write-Ok "py / ffmpeg / ffprobe are no longer available."
    } else {
        Write-Warn "Still available in this session: $($stillThere -join ', ')"
        Write-Dbg   "Close and reopen the terminal, or reboot, to refresh PATH."
    }

    if (-not $script:failed) {
        Write-Host "`n=============================================" -ForegroundColor Green
        Write-Host " DONE." -ForegroundColor Green
        Write-Host "=============================================" -ForegroundColor Green
    } else {
        Write-Host "`nFinished with warnings. See above." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "`n=============================================" -ForegroundColor Red
    Write-Host " [!!!] ERROR [!!!]" -ForegroundColor Red
    Write-Host "=============================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    if ($_.InvocationInfo) {
        Write-Host "Line: $($_.InvocationInfo.ScriptLineNumber)" -ForegroundColor DarkGray
    }
    $script:failed = $true
}
finally {
    if (-not $NonInteractive) {
        Write-Host "`nPress Enter to close this window..." -ForegroundColor Cyan
        Read-Host
    }
}

if ($script:failed) { exit 1 } else { exit 0 }