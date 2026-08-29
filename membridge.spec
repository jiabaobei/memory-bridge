# -*- mode: python ; coding: utf-8 -*-
# 便携 membridge.exe 打包配置（借鉴 ncnn 的便携发布精神：免安装、拷走即用）
# 构建：python -m PyInstaller membridge.spec  → 产物 dist\membridge.exe

a = Analysis(
    ["scripts\\membridge_exe_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="membridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
