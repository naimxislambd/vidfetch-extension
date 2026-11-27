# setup.ps1 - ONE-TIME installer for VidFetch. Run it once, never again.
#
#   - copies VidFetch to a permanent folder (%LOCALAPPDATA%\VidFetch), so you can
#     delete the downloaded zip/folder afterwards
#   - installs / locates Python, yt-dlp and ffmpeg (all automatic)
#   - makes the helper start hidden with Windows
#   - registers a tiny "native host" so the extension can restart the helper
#     itself if it ever stops
#   - starts the helper right now

$ErrorActionPreference = 'Continue'
$ExtensionId = 'oihhdlcimlagcmblkchbceaabippnahg'   # pinned by "key" in manifest.json
$Port = 8766

function Stop-Helper {
    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    } catch { }
    Start-Sleep -Milliseconds 600
}

function Test-Interpreter([string]$exe) {
    if ([string]::IsNullOrWhiteSpace($exe)) { return $false }
    if ($exe -match 'WindowsApps') { return $false }
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    & $exe -c "import sys" 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Test-Ytdlp([string]$exe) {
    & $exe -c "import yt_dlp" 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Write-Utf8NoBom([string]$path, [string]$text) {
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding $false))
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   VidFetch  -  one-time setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- 0. move into a permanent home ----------------------------------------
$src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$here = Join-Path $env:LOCALAPPDATA 'VidFetch'

if ($src.TrimEnd('\') -ne $here.TrimEnd('\')) {
    Write-Host "  Installing to  $here" -ForegroundColor Green
    Stop-Helper
    New-Item -ItemType Directory -Force -Path $here | Out-Null
    # keep the user's saved folder + history if this is an update
    robocopy $src $here /E /NFL /NDL /NJH /NJS /NP `
        /XF config.json history.json python-path.txt helper.log `
        /XD __pycache__ | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Host "  Could not copy the files to $here" -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
}
Set-Location $here

# ---- 1. find Python -------------------------------------------------------
$candidates = @()

$cached = Join-Path $here 'python-path.txt'
if (Test-Path -LiteralPath $cached) {
    $candidates += (Get-Content -LiteralPath $cached -ErrorAction SilentlyContinue | Select-Object -First 1)
}

foreach ($root in @(
    (Join-Path $env:USERPROFILE '.workbuddy-ai\binaries\python'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python')
)) {
    if (Test-Path -LiteralPath $root) {
        $candidates += Get-ChildItem -LiteralPath $root -Recurse -Filter 'python.exe' `
                        -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    }
}

foreach ($name in @('py', 'python', 'python3')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $candidates += $cmd.Source }
}

$py = $null
$needsInstall = $false
foreach ($c in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if (-not (Test-Interpreter $c)) { continue }
    if (Test-Ytdlp $c) { $py = $c; $needsInstall = $false; break }
    if (-not $py) { $py = $c; $needsInstall = $true }
}

if (-not $py) {
    Write-Host "  Python is not installed." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install it once, then run this setup again:"
    Write-Host "    https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  IMPORTANT: tick 'Add python.exe to PATH' on the first screen." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

# the `py` launcher has no pythonw.exe next to it - resolve the real interpreter
$real = (& $py -c "import sys;print(sys.executable)" 2>$null | Select-Object -First 1)
if ($real -and (Test-Path -LiteralPath $real)) { $py = $real }
Write-Host "  python   $py"

if ($needsInstall) {
    Write-Host "  yt-dlp   installing..." -ForegroundColor Yellow
    & $py -m pip install --quiet --upgrade yt-dlp
    if (-not (Test-Ytdlp $py)) {
        Write-Host "  Could not install yt-dlp. Run manually:" -ForegroundColor Red
        Write-Host "    `"$py`" -m pip install -U yt-dlp"
        Read-Host "Press Enter to close"
        exit 1
    }
} else {
    # fresh copy now; after this the helper keeps it current by itself
    & $py -m pip install --quiet --upgrade --disable-pip-version-check yt-dlp 2>&1 | Out-Null
}
$ver = (& $py -c "import yt_dlp;print(yt_dlp.version.__version__)" 2>&1) -join ''
Write-Host "  yt-dlp   $ver  (updates itself from now on)"
Set-Content -LiteralPath $cached -Value $py -Encoding ASCII

# ---- 2. ffmpeg (auto-install) ---------------------------------------------
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ff) {
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        Write-Host "  ffmpeg   installing (one time, can take a minute)..." -ForegroundColor Yellow
        & winget install -e --id Gyan.FFmpeg --silent `
            --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
        $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path','User') + ';' +
                    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links')
        $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
    }
}
if ($ff) {
    Write-Host "  ffmpeg   $($ff.Source)"
} else {
    Write-Host "  ffmpeg   could not be installed automatically." -ForegroundColor Yellow
    Write-Host "           Audio (MP3) needs it. Install once from https://www.gyan.dev/ffmpeg/builds/"
    Write-Host "           (or run:  winget install Gyan.FFmpeg ), then run setup.bat again."
}

# ---- 3. autostart ----------------------------------------------------------
$pythonw = Join-Path (Split-Path -Parent $py) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $py }
$helperPy = Join-Path $here 'helper.py'

try {
    $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'VidFetch helper.lnk'
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = $pythonw
    $sc.Arguments = '"' + $helperPy + '"'
    $sc.WorkingDirectory = $here
    $sc.WindowStyle = 7
    $sc.Description = 'VidFetch local download helper'
    $sc.Save()
    Write-Host "  startup  helper starts hidden with Windows" -ForegroundColor Green
} catch {
    Write-Host "  startup  could not create shortcut: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ---- 4. native host (lets the extension restart the helper) ---------------
try {
    $hostBat  = Join-Path $here 'native-host.bat'
    $hostJson = Join-Path $here 'com.vidfetch.helper.json'
    Write-Utf8NoBom $hostBat ("@echo off`r`n`"$py`" `"" + (Join-Path $here 'native_host.py') + "`"`r`n")

    $manifest = [ordered]@{
        name            = 'com.vidfetch.helper'
        description     = 'VidFetch - starts the local download helper'
        path            = $hostBat
        type            = 'stdio'
        allowed_origins = @("chrome-extension://$ExtensionId/")
    }
    Write-Utf8NoBom $hostJson ($manifest | ConvertTo-Json)

    foreach ($base in @(
        'HKCU:\Software\Google\Chrome\NativeMessagingHosts',
        'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts',
        'HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts'
    )) {
        $key = Join-Path $base 'com.vidfetch.helper'
        New-Item -Path $key -Force | Out-Null
        Set-ItemProperty -Path $key -Name '(default)' -Value $hostJson
    }
    Write-Host "  self-heal  extension can restart the helper if it ever stops" -ForegroundColor Green
} catch {
    Write-Host "  self-heal  could not register: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ---- 5. start the helper hidden right now ---------------------------------
Stop-Helper
Start-Process -FilePath $pythonw -ArgumentList ('"' + $helperPy + '"') `
    -WorkingDirectory $here -WindowStyle Hidden

$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if ($ok) {
    Write-Host "  helper   running (hidden)" -ForegroundColor Green
} else {
    Write-Host "  helper   did not answer. Check helper.log in $here" -ForegroundColor Red
}

# ---- 6. add the extension (the one thing a script cannot do) --------------
Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  Last step - add the button to your browser (once)" -ForegroundColor Cyan
Write-Host "------------------------------------------------------------" -ForegroundColor Cyan
Write-Host ""
Write-Host "   1. Open   chrome://extensions"
Write-Host "   2. Turn on 'Developer mode' (top right)"
Write-Host "   3. If an OLD VidFetch is listed, click 'Remove' on it"
Write-Host "   4. Click 'Load unpacked' and choose this folder:"
Write-Host ""
Write-Host "        $(Join-Path $here 'extension')" -ForegroundColor White
Write-Host ""
Write-Host "   5. Open a YouTube video - the icon is beside the Like button"
Write-Host ""
Write-Host "  After this you never need to run setup again." -ForegroundColor Green
Write-Host "  You can delete the folder you downloaded - everything lives in $here" -ForegroundColor Green
Write-Host "  (do NOT delete $here itself)"
Write-Host ""

try { Set-Clipboard -Value (Join-Path $here 'extension'); Write-Host "  (extension folder path copied to your clipboard)" } catch { }
$go = Read-Host "  Open the extensions page now? (y/n)"
if ($go -match '^(y|yes)$') {
    try { Start-Process "chrome://extensions" } catch { }
}
Write-Host ""
Read-Host "Press Enter to close"
