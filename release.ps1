<#
.SYNOPSIS
    One-command release for SpeakUp: build -> GitHub release -> installed copy.

.DESCRIPTION
    Removes the risk of a half-done release. Runs every step that has to happen
    for "the app" to actually be updated everywhere, in order, and aborts loudly
    if any step fails:

      0. Bump the PATCH version in src\version.py  (skip with -NoBump)
      1. Run the test suite            (skip with -SkipTests)
      2. Rebuild the exe (PyInstaller) -> dist\SpeakUp.exe
      3. Commit + push the version bump so the release tag isn't stale
      4. Create the GitHub release for the new version and upload the exe
                                                   (skip with -NoRelease)
      5. Overwrite the installed copy you actually launch, closing the running
         app first and relaunching it if it was open (skip with -NoInstall)

    EVERY build gets its own version, so you can always tell which one is
    running (tray -> About) and whether a machine has the latest. Fixes and
    small enhancements bump the THIRD place (1.2.0 -> 1.2.1 -> 1.2.2); -Minor
    marks a feature release (1.2.5 -> 1.3.0); -Major starts a new series
    (1.3.7 -> 2.0.0); -NoBump reuses the current version while iterating.
    src\version.py is the single source of truth for the app, exe and tag.

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
    [switch]$Relaunch,    # relaunch the app even if it wasn't running
    [switch]$NoBump,      # reuse the current version instead of bumping
    [switch]$Minor,       # bump MINOR for a feature release (1.2.5 -> 1.3.0)
    [switch]$Major        # bump MAJOR for a new series  (1.3.7 -> 2.0.0)
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host $msg -ForegroundColor Green }
function Warn($msg) { Write-Host $msg -ForegroundColor Yellow }

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "venv Python not found at $py — create the virtualenv first." }

# --- Version: bump the PATCH on every build (single source of truth) -------- #
# Every exe gets its own version so you can always tell which build is running.
# Small fixes/enhancements bump the third place (1.2.0 -> 1.2.1 -> 1.2.2);
# -Minor marks a feature release (1.2.5 -> 1.3.0); -Major starts a new series
# (1.3.7 -> 2.0.0); -NoBump reuses the current version while iterating.
$verFile = Join-Path $root 'src\version.py'
$verMatch = Select-String -Path $verFile -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $verMatch) { throw "Could not read __version__ from src\version.py" }
$current = $verMatch.Matches[0].Groups[1].Value
$parts = $current.Split('.')
if ($parts.Count -lt 3) { throw "Unexpected version format '$current' (want MAJOR.MINOR.PATCH)" }
[int]$maj = $parts[0]; [int]$min = $parts[1]; [int]$pat = $parts[2]

if ($NoBump) {
    $version = $current
    Warn "Reusing version $version (-NoBump)"
} else {
    if     ($Major) { $maj++; $min = 0; $pat = 0 }
    elseif ($Minor) { $min++; $pat = 0 }
    else            { $pat++ }
    $version = "$maj.$min.$pat"
    # Rewrite the single source of truth, then verify it took.
    (Get-Content $verFile -Raw) `
        -replace '__version__\s*=\s*"[^"]+"', "__version__ = `"$version`"" `
        | Set-Content $verFile -NoNewline
    $check = (Select-String -Path $verFile -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    if ($check -ne $version) { throw "Version bump failed (file still says '$check')" }
    Ok "Version bumped: $current -> $version"
}
$tag = "v$version"
Ok "Releasing SpeakUp $tag"

# --- Warn if the exe would not match GitHub's source ----------------------- #
# (src/version.py is excluded — this script just bumped it and commits it below.)
$dirty = git status --porcelain | Where-Object { $_ -notmatch 'src/version\.py' }
if ($dirty) {
    Warn "WARNING: you have uncommitted changes. The exe will include them, but"
    Warn "         GitHub's source won't until you commit + push:"
    $dirty | ForEach-Object { Warn "         $_" }
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

# --- 3. Commit + push the version bump ------------------------------------- #
# The GitHub release tags a commit, so the bumped version must be on the remote
# first — otherwise the tag would point at a commit that still says the old one.
if (-not $NoBump -and -not $NoRelease) {
    Step "Committing version bump"
    git add $verFile
    git diff --cached --quiet -- $verFile
    $hasStagedBump = ($LASTEXITCODE -ne 0)   # non-zero = there ARE staged changes
    if ($hasStagedBump) {
        git commit -m "chore(release): bump version to $version"
        if ($LASTEXITCODE -ne 0) { throw "git commit of the version bump failed." }
        git push
        if ($LASTEXITCODE -ne 0) { throw "git push failed — release aborted so the tag can't point at a stale commit." }
        Ok "Committed + pushed version $version"
    } else {
        Warn "src\version.py already committed at $version — nothing to push."
    }
}

# --- 4. GitHub release ----------------------------------------------------- #
if ($NoRelease) {
    Warn "Skipping GitHub release (-NoRelease)"
} else {
    Step "Publishing to GitHub release $tag"
    gh release view $tag *> $null
    if ($LASTEXITCODE -ne 0) {
        Warn "No release for $tag yet — creating it."
        gh release create $tag --title "SpeakUp $tag" --generate-notes --target main --latest
        if ($LASTEXITCODE -ne 0) { throw "gh release create failed." }
    }
    gh release upload $tag $exe --clobber
    if ($LASTEXITCODE -ne 0) { throw "gh release upload failed." }
    Ok "Uploaded exe to GitHub release $tag."
}

# --- 5. Installed copy ----------------------------------------------------- #
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
# Say only what this run actually did: with -NoRelease it once claimed the
# GitHub release was "in sync" when none had been created (2026-11-05).
$did = @('build')
if (-not $NoRelease) { $did += 'GitHub release' }
if (-not $NoInstall) { $did += 'installed copy' }
Ok ("SpeakUp ${tag}: " + ($did -join ' + ') + ' done.')
if ($NoRelease) { Warn "No GitHub release was created or updated (-NoRelease)." }
