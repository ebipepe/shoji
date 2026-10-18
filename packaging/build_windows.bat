@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
rem Shoji.exe をローカルでビルドする（通常は GitHub Actions が自動でビルドします）
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (echo 先に install.bat を実行してください & pause & exit /b 1)
.venv\Scripts\pip install pyinstaller pip-licenses || (pause & exit /b 1)
.venv\Scripts\pip-licenses --from=mixed --with-urls --with-license-file --with-notice-file --no-license-path --format=plain-vertical --ignore-packages pip-licenses prettytable wcwidth pip setuptools pyinstaller pyinstaller-hooks-contrib altgraph pefile pywin32-ctypes --output-file THIRD_PARTY_LICENSES.txt
.venv\Scripts\pyinstaller packaging\shoji.spec --noconfirm || (pause & exit /b 1)
copy /y LICENSE dist\Shoji\ >nul
copy /y NOTICE dist\Shoji\ >nul
copy /y THIRD_PARTY_LICENSES.txt dist\Shoji\ >nul
echo.
echo 完成: dist\Shoji\Shoji.exe
pause
