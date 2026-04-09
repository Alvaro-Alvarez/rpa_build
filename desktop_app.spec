from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules


project_root = Path.cwd()
app_icon = project_root / "assets" / "app_icon.ico"

datas = [
    (str(project_root / "assets"), "assets"),
]

hiddenimports = []
hiddenimports += collect_submodules("openpyxl")
binaries = collect_dynamic_libs("shiboken6", destdir="PySide6")


a = Analysis(
    ["desktop_app.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="CitySensAIBuild",
    icon=str(app_icon),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CitySensAIBuild",
)
