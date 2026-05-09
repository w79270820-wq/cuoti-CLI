# -*- mode: python ; coding: utf-8 -*-
# cuoti.spec
#
# Build: pyinstaller cuoti.spec --clean
# Output: dist/cuoti.exe  (~15 MB)
#
# How it works:
#   Double-click cuoti.exe
#   -> starts local HTTP server (port 7417)
#   -> auto-opens default browser
#   -> close the console window to quit

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('ui', 'ui'),   # bundle the entire ui/ folder
    ],
    hiddenimports=[
        'http.server',
        'urllib.parse',
        'sqlite3',
        'json',
        'threading',
        'webbrowser',
        'socket',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'numpy', 'pandas', 'matplotlib',
        'scipy', 'PIL', 'cv2', 'PyQt5', 'PyQt6',
        'wx', 'gi', 'webview',
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
    # Use ASCII name to avoid Windows encoding issues
    # Rename to any name after building if needed
    name='cuoti',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,    # Keep console: shows server status + errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico',  # optional: add a custom icon
)
