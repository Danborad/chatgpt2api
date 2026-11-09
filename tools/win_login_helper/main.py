#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ChatGPT2API Windows 桌面原生登录助手

功能特性：
1. 原生浏览器登录：直接调用 Windows 本地 Edge 或 Chrome 启动独立无痕会话，绕过各类无头检测；
2. 自动计算 2FA：自动识别 Base32 密钥并实时计算 TOTP 动态验证码；
3. 多服务器分发：支持将账号全部导入某一台服务器，或在多个 ChatGPT2API 实例之间均匀轮询分发；
4. 智能排重：启动前自动探测各服务器已存在的账号，避免重复登录消耗代理；
5. 自动重试：失败后自动更换代理会话后缀并重试，彻底杜绝单次网络卡顿；
6. 自动入库：登录成功自动获取全权限 Web Token 及 Refresh Token 并推送到 ChatGPT2API。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.browser import parse_card_key_accounts, perform_windows_login
from core.dispatcher import MultiServerDispatcher
from core.proxy import derive_isolated_proxy

console = Console()
BASE_DIR = Path(__file__).resolve().parent


def load_config() -> dict:
    cfg_path = BASE_DIR / "config.json"
    example_path = BASE_DIR / "config.example.json"
    if not cfg_path.exists() and example_path.exists():
        import shutil
        shutil.copy(example_path, cfg_path)
        console.print("[yellow]已根据 config.example.json 自动生成初始 config.json[/yellow]")
    if not cfg_path.exists():
        console.print(f"[bold red]错误：未找到配置文件 {cfg_path}[/bold red]")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_accounts_file(filename: str) -> str:
    path = BASE_DIR / filename
    if not path.exists():
        console.print(f"[bold red]错误：未找到卡密文件 {path}[/bold red]")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def append_failed_account(filename: str, item: dict, reason: str) -> None:
    path = BASE_DIR / filename
    card_line = f"{item['email']}----{item['password']}----{item.get('two_factor_secret', '')}"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{card_line}  # 失败原因: {reason}\n")


async def main() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]ChatGPT2API Windows 桌面原生批量登录助手[/bold cyan]\n"
            "[dim]支持 Edge/Chrome 原生无痕沙盒 · 自动计算 2FA · 自动切代理 · 多服务器均匀分发[/dim]",
            border_style="cyan",
        )
    )

    config = load_config()
    dispatcher = MultiServerDispatcher(config)

    if not dispatcher.has_servers():
        console.print("[bold red]错误：config.json 中未配置任何可用的 ChatGPT2API 服务器！[/bold red]")
        return

    # 1. 连通性测试
    console.print("\n[bold]1. 正在检查服务器连接与可用状态...[/bold]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("服务器名称", style="cyan")
    table.add_column("地址", style="blue")
    table.add_column("状态", justify="center")

    results = dispatcher.test_all_servers()
    has_online = False
    for client, ok, msg in results:
        status_text = f"[green]✓ {msg}[/green]" if ok else f"[red]✗ {msg}[/red]"
        if ok:
            has_online = True
        table.add_row(client.name, client.base_url, status_text)

    console.print(table)
    if not has_online:
        console.print("[bold red]没有可连通的 ChatGPT2API 服务器，请检查网络或地址配置！[/bold red]")
        return

    # 2. 读取卡密并解析
    accounts_file = config.get("accounts_file", "accounts.txt")
    raw_text = read_accounts_file(accounts_file)
    parsed_accounts = parse_card_key_accounts(raw_text)

    if not parsed_accounts:
        console.print(f"[bold yellow]警告：在 {accounts_file} 中未解析到有效卡密（格式：账号----密码----2FA）[/bold yellow]")
        return

    console.print(f"\n[bold]2. 卡密解析完成：共识别到 [green]{len(parsed_accounts)}[/green] 个待登录账号。[/bold]")

    # 3. 查重排重
    console.print("\n[bold]3. 正在比对服务器已存在账号，自动排重...[/bold]")
    existing_emails = dispatcher.get_global_existing_emails()
    console.print(f"服务器端目前共记录有效账号：[cyan]{len(existing_emails)}[/cyan] 个")

    pending_accounts: list[dict] = []
    skipped_count = 0
    for acc in parsed_accounts:
        if acc["email"].lower() in existing_emails:
            skipped_count += 1
            console.print(f"  [dim]- [跳过已有账号] {acc['email']}[/dim]")
        else:
            pending_accounts.append(acc)

    if skipped_count > 0:
        console.print(f"[yellow]已自动跳过 {skipped_count} 个已在系统中存在的账号。[/yellow]")

    if not pending_accounts:
        console.print("[bold green]太棒了！所有提交的账号均已在系统中正常存在，无需重复登录！[/bold green]")
        return

    console.print(f"本次将执行真实登录与授权入库：[bold green]{len(pending_accounts)}[/bold green] 个账号。")
    strategy_desc = "均匀轮流分发 (Round-Robin)" if dispatcher.strategy == "round_robin" else f"指定单机导入 ({dispatcher.target_server_name})"
    console.print(f"当前分发策略：[cyan]{strategy_desc}[/cyan]")

    # 清空或准备失败记录文件
    failed_file = config.get("failed_file", "failed_accounts.txt")
    if Path(BASE_DIR / failed_file).exists():
        try:
            os.remove(BASE_DIR / failed_file)
        except Exception:
            pass

    # 4. 循环登录与分发
    console.print("\n[bold]4. 开始执行 Windows 原生浏览器批量登录...[/bold]\n")

    base_proxy = config.get("base_proxy", "").strip()
    browser_cfg = config.get("browser", {})
    max_retries = max(1, int(config.get("max_retries", 2)))

    success_count = 0
    failed_count = 0

    async with async_playwright() as playwright:
        for idx, item in enumerate(pending_accounts, 1):
            email = item["email"]
            pwd = item["password"]
            secret = item.get("two_factor_secret", "")

            # 选取本次目标服务器
            target_server = dispatcher.pick_next_server()
            console.print(f"[bold cyan]──────────────────────────────────────────────────[/bold cyan]")
            console.print(f"[bold cyan][{idx}/{len(pending_accounts)}] 正在处理账号:[/bold cyan] [yellow]{email}[/yellow]")
            console.print(f"  分发目标服务器: [blue]{target_server.name}[/blue] ({target_server.base_url})")

            # 若卡密中自带 Access Token (JWT)，优先直接入库（免开浏览器，0秒极速完成）
            if item.get("access_token"):
                console.print("  [dim]检测到卡密自带 Access Token，正在尝试免开浏览器极速直连入库...[/dim]")
                direct_payload = {
                    "email": email,
                    "password": pwd,
                    "two_factor_secret": secret,
                    "access_token": item["access_token"],
                    "source_type": "web",
                    "registration_engine": "card_at_direct",
                }
                ok, push_msg = target_server.push_account(direct_payload)
                if ok:
                    console.print(f"  [bold green]★ 自带 AT 极速入库成功: {push_msg} (0 秒)[/bold green]")
                    success_count += 1
                    continue
                console.print(f"  [yellow]自带 AT 入库未通过 ({push_msg})，自动降级启动浏览器重新登录换取新 Token...[/yellow]")

            logged_payload = None
            last_err = ""

            for attempt in range(1, max_retries + 1):
                # 动态派生独立粘性代理（每次尝试使用不同后缀确保新 IP）
                salt = f"r{attempt}_{int(time.time()) % 1000}"
                acc_proxy = derive_isolated_proxy(base_proxy, email, salt=salt)
                proxy_label = acc_proxy if acc_proxy else "直连（无代理）"
                console.print(f"  尝试 [{attempt}/{max_retries}] 启动无痕浏览器 (代理: [dim]{proxy_label}[/dim])...")

                try:
                    payload = await perform_windows_login(
                        playwright=playwright,
                        email=email,
                        password=pwd,
                        two_factor_secret=secret,
                        proxy=acc_proxy,
                        browser_config=browser_cfg,
                    )
                    logged_payload = payload
                    break
                except Exception as exc:
                    last_err = str(exc)
                    console.print(f"  [red]✗ 登录遇到异常: {last_err}[/red]")
                    if attempt < max_retries:
                        console.print("  [dim]正在更换全新代理会话并在 3 秒后重试...[/dim]")
                        await asyncio.sleep(3)

            if logged_payload is not None:
                # 登录成功，推送到目标服务端
                console.print("  [green]✓ 浏览器登录授权成功，正在上传至 ChatGPT2API 服务端...[/green]")
                ok, push_msg = target_server.push_account(logged_payload)
                if ok:
                    console.print(f"  [bold green]★ 成功入库: {push_msg}[/bold green]")
                    success_count += 1
                else:
                    console.print(f"  [bold red]✗ 服务端入库失败: {push_msg}[/bold red]")
                    append_failed_account(failed_file, item, push_msg)
                    failed_count += 1
            else:
                console.print(f"  [bold red]★ 该账号所有重试均告失败: {last_err}[/bold red]")
                append_failed_account(failed_file, item, last_err)
                failed_count += 1

            # 账号间自然缓冲 1 秒
            await asyncio.sleep(1)

    # 5. 输出最终报表
    console.print(f"\n[bold cyan]================ 批量登录任务完成 ================[/bold cyan]")
    summary_table = Table(show_header=False)
    summary_table.add_row("解析总卡密数", f"[bold]{len(parsed_accounts)}[/bold]")
    summary_table.add_row("自动跳过已有账号", f"[yellow]{skipped_count}[/yellow]")
    summary_table.add_row("本次执行登录数", f"[cyan]{len(pending_accounts)}[/cyan]")
    summary_table.add_row("登录成功并入库", f"[bold green]{success_count}[/bold green]")
    summary_table.add_row("登录失败账号", f"[bold red]{failed_count}[/bold red]")
    console.print(summary_table)

    if failed_count > 0:
        console.print(f"\n[bold yellow]已将所有失败账号及原因归档至: [cyan]{failed_file}[/cyan][/bold yellow]")
        console.print("[dim]提示：您可以排查原因后，直接将失败文件内容重新粘贴进 accounts.txt 再次运行。[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]任务已被用户手动中断。[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]程序运行发生未捕获异常: {e}[/bold red]")

    print("\n" + "=" * 50)
    input("执行完毕，按回车键退出程序...")
