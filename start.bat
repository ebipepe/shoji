@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo 先に install.bat を実行してください & pause & exit /b 1)
title Shoji
.venv\Scripts\python.exe main.py %*
echo.
echo Shoji が終了しました。
pause
