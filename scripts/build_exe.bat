@echo off
REM 构建便携 membridge.exe（产物：dist\membridge.exe）
REM 借鉴 ncnn 的发布方式：为各平台提供免安装的便携构建
cd /d "%~dp0.."
python -m pip install pyinstaller -q
python -m PyInstaller --noconfirm --onefile --name membridge --paths src scripts\membridge_exe_entry.py
echo.
echo 产物: dist\membridge.exe
