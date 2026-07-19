# Install Engineering Manager (`em`) on Windows.
# Run in PowerShell:
#   irm https://raw.githubusercontent.com/enamulhaque028/ai-orchestration/main/install.ps1 | iex
# Or:
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$RepoGit = "git+https://github.com/enamulhaque028/ai-orchestration.git"
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"

function Write-Ok($msg) { Write-Host "OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "!   $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "ERR $msg" -ForegroundColor Red }

function Test-PythonOk([string]$PythonExe) {
    try {
        $ver = & $PythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])"
        $parts = $ver.Trim().Split(".")
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        return ($major -gt 3) -or (($major -eq 3) -and ($minor -ge 11))
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        "py -3.13",
        "py -3.12",
        "py -3.11",
        "python",
        "python3"
    )
    foreach ($c in $candidates) {
        try {
            if ($c -like "py *") {
                $exe = (Get-Command py -ErrorAction SilentlyContinue)
                if (-not $exe) { continue }
                $check = Invoke-Expression "$c -c `"import sys; print(sys.executable)`""
                if (Test-PythonOk $c.Split(" ")[0]) {
                    # Prefer invoking via py launcher with version
                    return $c
                }
            } else {
                $cmd = Get-Command $c -ErrorAction SilentlyContinue
                if ($cmd -and (Test-PythonOk $cmd.Source)) {
                    return $cmd.Source
                }
            }
        } catch { }
    }
    # Explicit py -3
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $out = & py -3 -c "import sys; print('%d.%d' % sys.version_info[:2]); print(sys.executable)"
            $lines = $out -split "`n"
            $ver = $lines[0].Trim()
            $parts = $ver.Split(".")
            if (([int]$parts[0] -gt 3) -or (([int]$parts[0] -eq 3) -and ([int]$parts[1] -ge 11))) {
                return "py -3"
            }
        } catch { }
    }
    return $null
}

function Ensure-Python {
    $py = Find-Python
    if ($py) {
        Write-Ok "Python found ($py)"
        return $py
    }
    Write-Warn "Python 3.11+ not found."
    Write-Host "Install from https://www.python.org/downloads/ (enable 'Add python.exe to PATH'), then re-run."
    Write-Host "Or: winget install Python.Python.3.12"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Warn "Attempting: winget install Python.Python.3.12"
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
        $py = Find-Python
        if ($py) {
            Write-Ok "Python found after winget ($py)"
            return $py
        }
    }
    throw "Python 3.11+ is required"
}

function Ensure-Pipx([string]$PythonCmd) {
    $pipx = Get-Command pipx -ErrorAction SilentlyContinue
    if ($pipx) {
        Write-Ok "pipx found ($($pipx.Source))"
        return
    }
    Write-Warn "Installing pipx…"
    if ($PythonCmd -like "py *") {
        Invoke-Expression "$PythonCmd -m pip install --user pipx"
    } else {
        & $PythonCmd -m pip install --user pipx
    }
    $env:Path = "$LocalBin;" + $env:Path
    python -m pipx ensurepath 2>$null
    pipx ensurepath 2>$null
    $pipx = Get-Command pipx -ErrorAction SilentlyContinue
    if (-not $pipx) {
        # Refresh path from user env
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
        $pipx = Get-Command pipx -ErrorAction SilentlyContinue
    }
    if (-not $pipx) { throw "pipx install failed. See https://pipx.pypa.io/" }
    Write-Ok "pipx installed"
}

function Ensure-Path {
    New-Item -ItemType Directory -Force -Path $LocalBin | Out-Null
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if ($userPath -notlike "*$LocalBin*") {
        [Environment]::SetEnvironmentVariable("Path", "$LocalBin;$userPath", "User")
        Write-Ok "Added $LocalBin to User PATH"
        Write-Warn "Open a new PowerShell window so PATH updates apply everywhere"
    } else {
        Write-Ok "User PATH already includes $LocalBin"
    }
    $env:Path = "$LocalBin;" + $env:Path
    try { pipx ensurepath | Out-Null } catch { }
}

function Install-Em {
    Write-Host "Installing em…"
    $listed = pipx list 2>$null | Out-String
    if ($listed -match "(?m)^\s*package em\b" -or $listed -match "\bem\b.*0\.") {
        pipx install --force $RepoGit
    } else {
        pipx install $RepoGit
    }
    Write-Ok "em installed"
}

function Verify-Em {
    $env:Path = "$LocalBin;" + $env:Path
    $em = Get-Command em -ErrorAction SilentlyContinue
    if (-not $em) {
        Write-Err "em not found on PATH in this session. Open a new terminal and run: em doctor"
        return
    }
    Write-Ok "em ready: $($em.Source)"
    Write-Host ""
    em doctor
}

function Setup-TelegramOptional {
    if ($env:EM_SKIP_TELEGRAM -eq "1") { return }
    if (-not [Environment]::UserInteractive) {
        Write-Host "Skipping Telegram setup (non-interactive). Later: em config telegram"
        return
    }
    Write-Host ""
    Write-Host "Telegram remote control (optional — each developer uses their own bot)"
    $ans = Read-Host "Set up Telegram now? [y/N]"
    if ($ans -notmatch '^[yY]') {
        Write-Host "Skipped. Configure later with: em config telegram"
        return
    }
    $token = Read-Host "Bot token (from @BotFather)"
    if (-not $token) {
        Write-Warn "No token entered — skip. Run later: em config telegram"
        return
    }
    $chat = Read-Host "Your chat id (optional, can set later)"
    $env:Path = "$LocalBin;" + $env:Path
    if ($chat) {
        em config telegram --token $token --chat-id $chat
    } else {
        em config telegram --token $token
    }
}

Write-Host "Engineering Manager (em) installer for Windows"
Write-Host "https://github.com/enamulhaque028/ai-orchestration"
Write-Host ""

$python = Ensure-Python
Ensure-Pipx $python
Ensure-Path
Install-Em
Verify-Em
Setup-TelegramOptional

Write-Host ""
Write-Ok "Done. Try: em --help"
Write-Host "If em is not found, open a new PowerShell window."
