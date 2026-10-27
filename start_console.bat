@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo 先に install.bat を実行してください & pause & exit /b 1)
rem Shoji の更新で部品の版が変わったのに、install.bat を実行していなければ止める
fc /b requirements-lock.txt .venv\shoji-installed-lock.txt >nul 2>nul || (
  echo 部品の更新が必要です（Shoji の更新で、使う部品の版が変わりました）。
  echo Shoji が起動中ならタスクトレイから終了し、install.bat を実行してから、もう一度起動してください。
  pause
  exit /b 1
)
title Shoji (console)
rem 動作確認・不具合調査用。ログをこの画面にも表示します
.venv\Scripts\python.exe main.py %*
echo.
echo Shoji が終了しました。
pause
