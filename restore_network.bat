@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
rem Shoji が異常終了してネットに繋がらなくなったときの復旧用
echo Windows のプロキシ設定を解除します...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
if exist "%~dp0data\saved_network.json" del "%~dp0data\saved_network.json"
echo プロキシを解除しました。DNS を 127.0.0.1 にしていた場合は reset_dns.bat も管理者として実行してください。
pause
