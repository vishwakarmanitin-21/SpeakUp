"""Build SpeakUp into a standalone .exe using PyInstaller.

Usage:
    python scripts/build.py

Output:
    dist/SpeakUp.exe
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "SpeakUp.spec"
DIST = ROOT / "dist"


def main() -> None:
    # Ensure pyinstaller is installed
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[Build] Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Clean previous build artifacts
    for d in (ROOT / "build", DIST):
        if d.exists():
            print(f"[Build] Cleaning {d}...")
            shutil.rmtree(d)

    # Run PyInstaller
    print("[Build] Building SpeakUp.exe...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm"],
        cwd=str(ROOT),
    )

    if result.returncode != 0:
        print("[Build] FAILED — see errors above.")
        sys.exit(1)

    exe_path = DIST / "SpeakUp.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n[Build] SUCCESS: {exe_path}  ({size_mb:.1f} MB)")
        print("\nTo distribute (safe — your API key is never in the build):")
        print(f"  1. Share ONLY {exe_path.name} — do not zip the whole project folder")
        print("  2. On first run, each user is prompted for their own OpenAI API key")
        print("  3. Each user's key/settings are stored privately in %APPDATA%\\SpeakUp")
        print("     (never next to the exe), so nothing personal travels with the file.")
    else:
        print("[Build] FAILED — exe not found in dist/")
        sys.exit(1)


if __name__ == "__main__":
    main()
