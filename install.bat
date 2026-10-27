@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
cd /d "%~dp0"
echo === Shoji インストール ===
where python >nul 2>nul || (echo Python 3.12 以上をインストールしてください: https://www.python.org/downloads/ & pause & exit /b 1)

rem 起動中の Shoji は部品のファイルを使っているため、更新に失敗する（アクセスが拒否されました）
set "SHOJI_DIR=%CD%"
powershell -NoProfile -Command "if (Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ($env:SHOJI_DIR + '\.venv\*') }) { exit 1 }"
if errorlevel 1 (
  echo.
  echo Shoji が起動中です。タスクトレイの Shoji のアイコンを右クリックして「終了」してから、もう一度実行してください。
  pause
  exit /b 1
)

if not exist .venv (
  python -m venv .venv || (echo 仮想環境の作成に失敗しました & pause & exit /b 1)
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip

rem Windows アプリ版と同じ版の部品を、指紋（ハッシュ）を確かめて入れる
"%PY%" -m pip install --require-hashes -r requirements-lock.txt
if errorlevel 1 (
  echo.
  echo 固定の版の部品を入れられませんでした（お使いの Python の版に合う部品が無いことがあります）。
  echo 代わりに requirements.txt の指定（新しい版）で入れます。
  "%PY%" -m pip install -r requirements.txt || (echo パッケージのインストールに失敗しました & pause & exit /b 1)
)
rem start.bat が「部品の更新が必要か」を判断するための記録
copy /y requirements-lock.txt .venv\shoji-installed-lock.txt >nul
echo.
echo インストール完了。start.bat で起動し、ダッシュボードの「セットアップ」タブで証明書をインストールしてください。
pause
