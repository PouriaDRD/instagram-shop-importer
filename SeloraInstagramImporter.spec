from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH)

ICON_PATH = (
    ROOT
    / "app"
    / "static"
    / "images"
    / "favicon.ico"
)

playwright_datas, playwright_binaries, playwright_hiddenimports = (
    collect_all("playwright")
)

datas = [
    (
        str(ROOT / "app" / "templates"),
        "app/templates",
    ),
    (
        str(ROOT / "app" / "static"),
        "app/static",
    ),
    (
        str(ROOT / "migrations"),
        "migrations",
    ),
    (
        str(ROOT / ".env.example"),
        ".",
    ),
]

datas += playwright_datas


a = Analysis(
    ["run.py"],
    pathex=[str(ROOT)],
    binaries=playwright_binaries,
    datas=datas,
    hiddenimports=playwright_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
    ],
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
    name="SeloraInstagramImporter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH),
)