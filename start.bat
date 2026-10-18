@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (echo 先に install.bat を実行してください & pause & exit /b 1)
rem コンソール画面を出さずに起動し、タスクトレイに常駐します（ログは data\shoji.log）
start "" .venv\Scripts\pythonw.exe main.py %*
