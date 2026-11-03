@echo off
chcp 65001 >nul
title 小伴 · 公网隧道
cd /d E:\WH\pc-core
echo 正在建立公网隧道（控制台 8771）…
echo.
E:\WH\pc-core\.venv\Scripts\python.exe scripts\tunnel.py
pause
