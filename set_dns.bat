@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
net session >nul 2>&1 || (echo このファイルを右クリックして「管理者として実行」してください & pause & exit /b 1)
echo 有効なネットワークアダプターの DNS を 127.0.0.1 / ::1 に設定します（Shoji 起動中のみ使ってください）
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object { Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses ('127.0.0.1','::1') }; Clear-DnsClientCache"
echo 完了しました。元に戻すときは reset_dns.bat を管理者として実行してください。
pause
