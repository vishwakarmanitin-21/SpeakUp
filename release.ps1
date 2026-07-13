<#
.SYNOPSIS
    One-command release for SpeakUp: build -> GitHub release -> installed copy.

.DESCRIPTION
    Removes the risk of a half-done release. Runs every step that has to happen
    for "the app" to actually be updated everywhere, in order, and aborts loudly
    if any step fails:

      1. Run the test suite            (skip with -SkipTests)
      2. Rebuild the exe (PyInstaller) -> dist\SpeakUp.exe
      3. Upload it to the GitHub release for the current version (creates the
         release if it doesn't exist yet)          (skip with -NoRelease)
      4. Overwrite the installed copy you actually launch, closing the running
         app first and relaunching it if it was open (skip with -NoInstall)

    The version/tag is read from src\version.py (single source of truth), so the
    GitHub release always matches the code — bump __version__ and the release
    targets the new tag automatically.

.EXAMPLE
    .\release.ps1
        Full release: tests, build, GitHub upload, update local copy.

.EXAMPLE
    .\release.ps1 -SkipTests -NoRelease
        Just rebuild and refresh the local installed copy (fast local iteration).
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,   # don't run pytest first
    [switch]$NoRelease,   # don't touch the GitHub release
    [switch]$NoInstall,   # don't update the locally installed copy
    [switch]$Relaunch     # relaunch the app even if it wasn't running
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host $msg -ForegroundColor Green }
function Warn($msg) { Write-Host $msg -ForegroundColor Yellow }

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "venv Python not found at $py — create the virtualenv first." }

# --- Version (single source of truth) -------------------------------------- #
$verMatch = Select-String -Path (Join-Path $root 'src\version.py') `
                          -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $verMatch) { throw "Could not read __version__ from src\version.py" }
$version = $verMatch.Matches[0].Groups[1].Value
$tag = "v$version"
Ok "Releasing SpeakUp $tag"

# --- Warn if the exe would not match GitHub's source ----------------------- #
$dirty = git status --porcelain
if ($dirty) {
    Warn "WARNING: you have uncommitted changes. The exe will include them, but"
    Warn "         GitHub's source won't until you commit + push:"
    git status --short
}
$unpushed = git log --oneline '@{u}..HEAD' 2>$null
if ($unpushed) {
    Warn "WARNING: unpushed commits — push so GitHub's code matches this exe:"
    $unpushed | ForEach-Object { Warn "         $_" }
}

# --- 1. Tests -------------------------------------------------------------- #
if ($SkipTests) {
    Warn "Skipping tests (-SkipTests)"
} else {
    Step "Running tests"
    & $py -m pytest tests/ -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed — aborting release." }
}

# --- 2. Build -------------------------------------------------------------- #
Step "Building exe (PyInstaller)"
& $py -m PyInstaller SpeakUp.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
$exe = Join-Path $root 'dist\SpeakUp.exe'
if (-not (Test-Path $exe)) { throw "Build did not produce $exe" }
Ok ("Built {0} ({1:N1} MB)" -f $exe, ((Get-Item $exe).Length / 1MB))

# --- 3. GitHub release ----------------------------------------------------- #
if ($NoRelease) {
    Warn "Skipping GitHub release (-NoRelease)"
} else {
    Step "Publishing to GitHub release $tag"
    gh release view $tag *> $null
    if ($LASTEXITCODE -ne 0) {
        Warn "No release for $tag yet — creating it from main."
        gh release create $tag --title "SpeakUp $tag" --notes "SpeakUp $tag" --target main
        if ($LASTEXITCODE -ne 0) { throw "gh release create failed." }
    }
    gh release upload $tag $exe --clobber
    if ($LASTEXITCODE -ne 0) { throw "gh release upload failed." }
    Ok "Uploaded exe to GitHub release $tag."
}

# --- 4. Installed copy ----------------------------------------------------- #
if ($NoInstall) {
    Warn "Skipping installed-copy update (-NoInstall)"
} else {
    Step "Updating installed copy"
    $dest = Join-Path $env:LOCALAPPDATA 'Programs\SpeakUp\SpeakUp.exe'
    $destDir = Split-Path $dest
    if (-not (Test-Path $destDir)) {
        Warn "Installed folder not found ($destDir) — skipping. (App not installed here?)"
    } else {
        $wasRunning = $false
        $proc = Get-Process -Name SpeakUp -ErrorAction SilentlyContinue
        if ($proc) {
            $wasRunning = $true
            Write-Host "Closing running SpeakUp..."
            $proc | Stop-Process -Force
            Start-Sleep -Milliseconds 800
        }
        Copy-Item $exe $dest -Force
        Ok "Updated $dest"
        if ($Relaunch -or $wasRunning) {
            Write-Host "Relaunching SpeakUp..."
            Start-Process $dest
        }
    }
}

Step "Done"
Ok "SpeakUp ${tag}: build + GitHub release + installed copy are all in sync."
