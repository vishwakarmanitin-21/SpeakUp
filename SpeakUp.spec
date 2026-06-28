# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for SpeakUp.

Build with:  pyinstaller SpeakUp.spec
Output:      dist/SpeakUp.exe
"""

import os
import sys

block_cipher = None

# Project root (where this spec file lives)
ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'src', 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Bundle config defaults and .env template so the exe is self-contained
        (os.path.join(ROOT, 'config_defaults.json'), '.'),
        (os.path.join(ROOT, '.env.example'), '.'),
        (os.path.join(ROOT, 'user_guide.html'), '.'),
        (os.path.join(ROOT, 'assets', 'icon.png'), '.'),
    ],
    hiddenimports=[
        # qasync needs explicit import
        'qasync',
        # PyQt5 plugins
        'PyQt5.sip',
        # sounddevice backend
        'sounddevice',
        '_sounddevice_data',
        # pynput backends (Windows)
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        # stdlib modules sometimes missed
        'winreg',
        # websockets (live transcription) — imported lazily, list explicitly
        'websockets',
        'websockets.asyncio.client',
        # App modules imported lazily (inside functions) — list so they're bundled
        'src.transcription.realtime_client',
        'src.transcription.deepgram_client',
        'src.services.vocab_learner',
        'src.ui.components.caption_window',
        'src.ui.components.onboarding_dialog',
        # scipy.io.wavfile is used for the realtime/deepgram WAV fallback
        'scipy.io.wavfile',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional deps not needed for cloud-only mode
        'faster_whisper',
        'ctranslate2',
        'torch',
        'torchaudio',
        'torchvision',
        # Exclude test frameworks
        'pytest',
        'pytest_asyncio',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SpeakUp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window — GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'assets', 'icon.ico'),
)
