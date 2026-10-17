@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
net session >nul 2>&1 || (echo このファイルを右クリックして「管理者として実行」してください & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetAdapter | ForEach-Object { Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ResetServerAddresses }; Clear-DnsClientCache"
echo DNS を自動取得に戻しました。
pause
