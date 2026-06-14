# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Scholar Watch Desktop."""

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = os.path.abspath(".")

# Selenium drives the user's real Chrome for citing-paper fetches. Bundle it fully so the
# Selenium Manager binary (which resolves chromedriver at runtime) ships inside the exe.
selenium_datas, selenium_binaries, selenium_hiddenimports = collect_all("selenium")

a = Analysis(
    ["scholar_watch_app.py"],
    pathex=[root],
    binaries=selenium_binaries,
    datas=[
        (os.path.join(root, "scholar_watch", "desktop", "web"), os.path.join("scholar_watch", "desktop", "web")),
        (os.path.join(root, "config", "config.example.yaml"), "config"),
    ] + selenium_datas,
    hiddenimports=[
        "scholar_watch.desktop.api",
        "scholar_watch.browser_fetcher",
        "bottle_websocket",
        "engineio.async_drivers.threading",
    ] + selenium_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="ScholarWatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)
