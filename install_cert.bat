@echo off
rem SPDX-License-Identifier: Apache-2.0 / Copyright 2026 The Shoji Authors
chcp 65001 >nul
cd /d "%~dp0"
if not exist data\certs\mitmproxy-ca-cert.cer (echo 一度 start.bat で起動して証明書を生成してください & pause & exit /b 1)
certutil -user -addstore Root data\certs\mitmproxy-ca-cert.cer
echo ブラウザを再起動すると HTTPS フィルタリングが有効になります。
pause
