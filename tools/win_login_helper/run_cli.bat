@echo off
chcp 65001 >nul
title ChatGPT2API Windows 登录助手 (控制台命令行版)

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    pause
    exit /b
)

pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn >nul 2>&1

python main.py

pause
