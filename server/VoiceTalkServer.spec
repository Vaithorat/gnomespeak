# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['windows_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('handlers', 'handlers'), ('config.py', '.'), ('intent_parser.py', '.'), ('command_executor.py', '.'), ('auth.py', '.')],
    hiddenimports=['customtkinter', 'pystray', 'PIL', 'PIL._imaging', 'PIL.ImageDraw', 'websockets', 'openai', 'cryptography', 'cryptography.fernet', 'cryptography.hazmat.primitives', 'cryptography.hazmat.primitives.kdf.pbkdf2', 'cryptography.hazmat.primitives.hashes', 'asyncio', 'google.genai', 'pyautogui', 'playwright', 'playwright.async_api', 'playwright._impl._driver', 'playwright._impl._browser_type', 'playwright._impl._page', 'yt_dlp', 'pycaw', 'comtypes'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VoiceTalkServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
