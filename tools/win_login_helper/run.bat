@echo off
chcp 65001 >nul
title ChatGPT2API Windows 桌面原生批量登录助手

echo =======================================================
echo          ChatGPT2API Windows 桌面原生批量登录助手
echo =======================================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    echo 请前往 Python 官网下载并安装 Python 3.10 或更高版本：
    echo 官网地址: https://www.python.org/downloads/
    echo 注意：安装时请务必勾选 "Add Python to PATH" 选项！
    echo.
    pause
    exit /b
)

:: 安装依赖库
echo 正在检查并更新运行依赖库 (playwright, requests, rich)...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn >nul 2>&1
if %errorlevel% neq 0 (
    pip install -r requirements.txt
)

echo.
echo 依赖环境准备就绪，正在启动桌面图形界面 (GUI)...
echo.

start "" pythonw gui.py

exit
