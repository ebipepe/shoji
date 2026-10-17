@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
cd /d "%~dp0"
echo === Shoji インストール ===
where python >nul 2>nul || (echo Python 3.12 以上をインストールしてください: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv (
  python -m venv .venv || (echo 仮想環境の作成に失敗しました & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (echo パッケージのインストールに失敗しました & pause & exit /b 1)
echo.
echo インストール完了。start.bat で起動し、ダッシュボードの「セットアップ」タブで証明書をインストールしてください。
pause
