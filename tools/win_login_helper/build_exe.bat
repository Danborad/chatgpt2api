@echo off
chcp 65001 >nul
title 打包 Windows EXE 独立可执行程序

echo =======================================================
echo     一键打包 ChatGPT2API 桌面登录助手为 EXE 可执行程序
echo =======================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    pause
    exit /b
)

echo 正在安装 PyInstaller 打包工具及依赖...
pip install pyinstaller -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn

echo.
echo 正在执行 PyInstaller 打包为独立的 Windows EXE 程序...
echo.

pyinstaller --noconfirm --onedir --windowed ^
    --name "ChatGPT2API-LoginHelper" ^
    --add-data "config.example.json;." ^
    --add-data "accounts.txt;." ^
    --add-data "core;core" ^
    gui.py

echo.
echo =======================================================
echo [打包完成] 生成的可执行文件位于: dist\ChatGPT2API-LoginHelper\
echo 包含主程序: ChatGPT2API-LoginHelper.exe
echo 您可以直接把 dist\ChatGPT2API-LoginHelper 目录拷贝到任何电脑上直接双击运行！
echo =======================================================
echo.

pause
