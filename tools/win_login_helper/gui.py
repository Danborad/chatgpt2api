#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ChatGPT2API Windows 桌面原生批量登录助手 - GUI 图形界面版

特性：
1. 现代化桌面图形界面，无需命令行，双击即可操作；
2. 支持可视化配置多个 ChatGPT2API 服务器，自由选择单机或均匀轮流分发；
3. 自动探测服务端并排重，避免重复登录已正常入库的账号；
4. Windows 原生 Edge / Chrome 独立无痕环境，彻底避开 Cloudflare 质询拦截；
5. 支持一键重试失败账号、一键复制失败卡密、实时日志与表格动态进度。
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from core.browser import parse_card_key_accounts, perform_windows_login
from core.client import ChatGPT2APIClient
from core.dispatcher import MultiServerDispatcher
from core.proxy import derive_isolated_proxy

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
FAILED_FILE = BASE_DIR / "failed_accounts.txt"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        example = BASE_DIR / "config.example.json"
        if example.exists():
            import shutil
            shutil.copy(example, CONFIG_FILE)
        else:
            return {
                "servers": [
                    {"name": "NAS主节点", "url": "http://192.168.31.61:3005", "auth_key": "onepiece1314", "enabled": True, "target_group_id": None}
                ],
                "import_strategy": "round_robin",
                "target_server": "NAS主节点",
                "base_proxy": "http://nohk@192.168.31.46:2260",
                "browser": {"channel": "msedge", "headless": false, "timeout_seconds": 90, "slow_mo_ms": 50},
                "max_retries": 2,
            }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


class LoginHelperGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ChatGPT2API Windows 批量登录助手 v1.0")
        self.geometry("1020x720")
        self.minsize(860, 600)

        # 尝试设置 Windows 原生样式
        self.style = ttk.Style(self)
        try:
            if "vista" in self.style.theme_names():
                self.style.theme_use("vista")
            elif "clam" in self.style.theme_names():
                self.style.theme_use("clam")
        except Exception:
            pass

        self.config_data = load_config()
        self.ui_queue: queue.Queue = queue.Queue()
        self.is_running = False
        self.stop_requested = False
        self.failed_items: list[dict] = []
        self.current_accounts: list[dict] = []

        self._build_ui()
        self._load_config_to_ui()
        self.after(100, self._process_ui_queue)

    def _build_ui(self) -> None:
        # 顶部导航选项卡
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 选项卡 1：批量登录主控面板
        self.tab_main = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_main, text=" 批量登录授权 ")

        # 选项卡 2：服务器节点管理
        self.tab_servers = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_servers, text=" 服务器节点配置 ")

        self._build_main_tab()
        self._build_servers_tab()

    def _build_main_tab(self) -> None:
        # 主界面分为左右两列或上下两部分
        paned = ttk.PanedWindow(self.tab_main, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左侧：配置与卡密输入
        left_frame = ttk.Frame(paned, padding=5)
        paned.add(left_frame, weight=1)

        # 1. 运行配置区
        cfg_group = ttk.LabelFrame(left_frame, text="分发与代理设置", padding=8)
        cfg_group.pack(fill=tk.X, pady=(0, 8))

        # 目标服务器策略
        strat_frame = ttk.Frame(cfg_group)
        strat_frame.pack(fill=tk.X, pady=2)
        ttk.Label(strat_frame, text="分发策略:").pack(side=tk.LEFT)
        self.var_strategy = tk.StringVar(value="round_robin")
        ttk.Radiobutton(strat_frame, text="均匀轮流分发", variable=self.var_strategy, value="round_robin", command=self._on_strategy_change).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(strat_frame, text="指定单台服务器", variable=self.var_strategy, value="single", command=self._on_strategy_change).pack(side=tk.LEFT, padx=5)

        target_frame = ttk.Frame(cfg_group)
        target_frame.pack(fill=tk.X, pady=2)
        ttk.Label(target_frame, text="目标单机:").pack(side=tk.LEFT)
        self.combo_target_server = ttk.Combobox(target_frame, state="readonly", width=25)
        self.combo_target_server.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # 代理设置
        proxy_frame = ttk.Frame(cfg_group)
        proxy_frame.pack(fill=tk.X, pady=2)
        ttk.Label(proxy_frame, text="出口代理:").pack(side=tk.LEFT)
        self.var_proxy = tk.StringVar()
        entry_proxy = ttk.Entry(proxy_frame, textvariable=self.var_proxy, font=("Consolas", 9))
        entry_proxy.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # 选项：浏览器内核与有头设置
        opt_frame = ttk.Frame(cfg_group)
        opt_frame.pack(fill=tk.X, pady=4)
        ttk.Label(opt_frame, text="浏览器:").pack(side=tk.LEFT)
        self.var_channel = tk.StringVar(value="msedge")
        combo_browser = ttk.Combobox(opt_frame, textvariable=self.var_channel, state="readonly", width=10, values=["msedge", "chrome", "chromium"])
        combo_browser.pack(side=tk.LEFT, padx=5)

        self.var_headless = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="后台静默(无头)", variable=self.var_headless).pack(side=tk.LEFT, padx=8)

        self.var_filter_existing = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="自动过滤已有账号", variable=self.var_filter_existing).pack(side=tk.LEFT, padx=8)

        # 2. 卡密文本区
        card_group = ttk.LabelFrame(left_frame, text="待登录卡密（一行一个：账号----密码----2FA密钥）", padding=8)
        card_group.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.txt_accounts = scrolledtext.ScrolledText(card_group, wrap=tk.NONE, font=("Consolas", 9), height=10)
        self.txt_accounts.pack(fill=tk.BOTH, expand=True)
        self.txt_accounts.bind("<KeyRelease>", lambda e: self._update_account_stats())

        # 文本提示与按钮区
        btn_bar = ttk.Frame(left_frame)
        btn_bar.pack(fill=tk.X)

        self.lbl_card_stats = ttk.Label(btn_bar, text="待识别卡密: 0 个", foreground="#0066cc")
        self.lbl_card_stats.pack(side=tk.LEFT, pady=2)

        self.btn_paste = ttk.Button(btn_bar, text="从剪贴板粘贴", command=self._paste_clipboard)
        self.btn_paste.pack(side=tk.RIGHT, padx=4)

        self.btn_clear = ttk.Button(btn_bar, text="清空输入", command=self._clear_input)
        self.btn_clear.pack(side=tk.RIGHT, padx=4)

        # 控制操作栏
        act_frame = ttk.Frame(left_frame, padding=(0, 6))
        act_frame.pack(fill=tk.X)

        self.btn_start = ttk.Button(act_frame, text="▶ 开始批量登录授权", command=self._start_task, style="Accent.TButton")
        self.btn_start.pack(side=tk.LEFT, padx=(0, 6), ipady=3)

        self.btn_stop = ttk.Button(act_frame, text="⏹ 停止任务", command=self._stop_task, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=6, ipady=3)

        self.btn_retry_failed = ttk.Button(act_frame, text="↻ 重试失败账号", command=self._retry_failed, state=tk.DISABLED)
        self.btn_retry_failed.pack(side=tk.LEFT, padx=6, ipady=3)

        self.btn_copy_failed = ttk.Button(act_frame, text="复制失败卡密", command=self._copy_failed, state=tk.DISABLED)
        self.btn_copy_failed.pack(side=tk.LEFT, padx=6, ipady=3)

        # 右侧：实时任务表格与日志
        right_frame = ttk.Frame(paned, padding=5)
        paned.add(right_frame, weight=2)

        # 进度条与指标看板
        metric_group = ttk.LabelFrame(right_frame, text="任务执行进度", padding=8)
        metric_group.pack(fill=tk.X, pady=(0, 8))

        self.progress_bar = ttk.Progressbar(metric_group, orient=tk.HORIZONTAL, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(0, 6))

        self.lbl_summary = ttk.Label(metric_group, text="总数: 0  |  已完成: 0  |  成功: 0  |  失败: 0  |  进度: 0%", font=("Segoe UI", 9, "bold"))
        self.lbl_summary.pack(fill=tk.X)

        # 表格区
        table_group = ttk.LabelFrame(right_frame, text="账号处理列表", padding=6)
        table_group.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        cols = ("idx", "email", "server", "status", "info")
        self.tree = ttk.Treeview(table_group, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("idx", text="#")
        self.tree.heading("email", text="账号邮箱")
        self.tree.heading("server", text="分发目标")
        self.tree.heading("status", text="状态")
        self.tree.heading("info", text="结果说明 / 错误信息")

        self.tree.column("idx", width=40, anchor=tk.CENTER)
        self.tree.column("email", width=190, anchor=tk.W)
        self.tree.column("server", width=90, anchor=tk.CENTER)
        self.tree.column("status", width=70, anchor=tk.CENTER)
        self.tree.column("info", width=240, anchor=tk.W)

        tree_scroll = ttk.Scrollbar(table_group, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 下方详细执行日志
        log_group = ttk.LabelFrame(right_frame, text="运行实时日志", padding=6)
        log_group.pack(fill=tk.BOTH, expand=True)

        self.txt_log = scrolledtext.ScrolledText(log_group, wrap=tk.WORD, font=("Consolas", 8), height=8)
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def _build_servers_tab(self) -> None:
        # 服务器管理选项卡
        srv_top = ttk.Frame(self.tab_servers)
        srv_top.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(srv_top, text="在此管理所有协同的 ChatGPT2API 服务端节点（支持配置多个服务器并自动负载均衡）：", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        ttk.Button(srv_top, text="测试全部连通性", command=self._test_all_servers).pack(side=tk.RIGHT, padx=4)
        ttk.Button(srv_top, text="保存节点配置", command=self._save_servers_config).pack(side=tk.RIGHT, padx=4)

        # 服务器表格
        cols = ("enabled", "name", "url", "auth_key", "status")
        self.srv_tree = ttk.Treeview(self.tab_servers, columns=cols, show="headings", height=8)
        self.srv_tree.heading("enabled", text="启用")
        self.srv_tree.heading("name", text="节点名称")
        self.srv_tree.heading("url", text="服务器地址")
        self.srv_tree.heading("auth_key", text="管理员密钥")
        self.srv_tree.heading("status", text="测试状态")

        self.srv_tree.column("enabled", width=50, anchor=tk.CENTER)
        self.srv_tree.column("name", width=120, anchor=tk.W)
        self.srv_tree.column("url", width=220, anchor=tk.W)
        self.srv_tree.column("auth_key", width=180, anchor=tk.W)
        self.srv_tree.column("status", width=120, anchor=tk.CENTER)
        self.srv_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # 表单编辑区
        form_frame = ttk.LabelFrame(self.tab_servers, text="新增 / 编辑服务器节点", padding=10)
        form_frame.pack(fill=tk.X)

        f_row1 = ttk.Frame(form_frame)
        f_row1.pack(fill=tk.X, pady=2)
        ttk.Label(f_row1, text="节点名称:", width=10).pack(side=tk.LEFT)
        self.var_srv_name = tk.StringVar(value="NAS主节点")
        ttk.Entry(f_row1, textvariable=self.var_srv_name, width=20).pack(side=tk.LEFT, padx=5)

        ttk.Label(f_row1, text="服务地址:", width=10).pack(side=tk.LEFT, padx=(10, 0))
        self.var_srv_url = tk.StringVar(value="http://192.168.31.61:3005")
        ttk.Entry(f_row1, textvariable=self.var_srv_url, width=35).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        f_row2 = ttk.Frame(form_frame)
        f_row2.pack(fill=tk.X, pady=2)
        ttk.Label(f_row2, text="管理员密钥:", width=10).pack(side=tk.LEFT)
        self.var_srv_key = tk.StringVar(value="onepiece1314")
        ttk.Entry(f_row2, textvariable=self.var_srv_key, width=35).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        self.var_srv_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(f_row2, text="启用此节点", variable=self.var_srv_enabled).pack(side=tk.LEFT, padx=10)

        f_btn = ttk.Frame(form_frame)
        f_btn.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(f_btn, text="添加 / 更新到列表", command=self._add_or_update_server).pack(side=tk.LEFT, padx=4)
        ttk.Button(f_btn, text="删除选中节点", command=self._delete_selected_server).pack(side=tk.LEFT, padx=4)

    def _load_config_to_ui(self) -> None:
        cfg = self.config_data
        self.var_strategy.set(cfg.get("import_strategy", "round_robin"))
        self.var_proxy.set(cfg.get("base_proxy", "http://nohk@192.168.31.46:2260"))
        b_cfg = cfg.get("browser", {})
        self.var_channel.set(b_cfg.get("channel", "msedge"))
        self.var_headless.set(bool(b_cfg.get("headless", False)))

        # 加载服务器列表
        self._refresh_servers_tree()
        self._on_strategy_change()

        # 加载 accounts.txt 示例
        acc_file = BASE_DIR / cfg.get("accounts_file", "accounts.txt")
        if acc_file.exists():
            try:
                with open(acc_file, "r", encoding="utf-8") as f:
                    self.txt_accounts.insert(tk.END, f.read())
            except Exception:
                pass
        self._update_account_stats()

    def _refresh_servers_tree(self) -> None:
        for item in self.srv_tree.get_children():
            self.srv_tree.delete(item)

        servers = self.config_data.get("servers", [])
        names = []
        for s in servers:
            name = s.get("name", "未命名")
            names.append(name)
            enabled = "✓ 是" if s.get("enabled", True) else "否"
            self.srv_tree.insert("", tk.END, values=(enabled, name, s.get("url", ""), s.get("auth_key", ""), "未测试"))

        self.combo_target_server["values"] = names
        target_name = self.config_data.get("target_server", "")
        if target_name in names:
            self.combo_target_server.set(target_name)
        elif names:
            self.combo_target_server.set(names[0])

    def _on_strategy_change(self) -> None:
        if self.var_strategy.get() == "single":
            self.combo_target_server.configure(state="readonly")
        else:
            self.combo_target_server.configure(state="disabled")

    def _paste_clipboard(self) -> None:
        try:
            clip = self.clipboard_get()
            if clip:
                self.txt_accounts.insert(tk.END, "\n" + clip.strip() + "\n")
                self._update_account_stats()
        except Exception:
            pass

    def _clear_input(self) -> None:
        self.txt_accounts.delete("1.0", tk.END)
        self._update_account_stats()

    def _update_account_stats(self) -> None:
        content = self.txt_accounts.get("1.0", tk.END).strip()
        parsed = parse_card_key_accounts(content)
        self.lbl_card_stats.config(text=f"已识别待登录卡密: {len(parsed)} 个")

    def _log(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.ui_queue.put(("log", f"[{ts}] {text}\n"))

    def _process_ui_queue(self) -> None:
        while not self.ui_queue.empty():
            action, data = self.ui_queue.get_nowait()
            if action == "log":
                self.txt_log.insert(tk.END, data)
                self.txt_log.see(tk.END)
            elif action == "table_init":
                for item in self.tree.get_children():
                    self.tree.delete(item)
                for acc in data:
                    self.tree.insert("", tk.END, iid=acc["id"], values=(acc["idx"], acc["email"], acc["server"], "等待中", "排队中"))
            elif action == "table_update":
                iid, status, info = data
                if self.tree.exists(iid):
                    item = self.tree.item(iid)
                    vals = list(item["values"])
                    vals[3] = status
                    vals[4] = info
                    self.tree.item(iid, values=vals)
                    self.tree.see(iid)
            elif action == "progress":
                total, done, success, failed = data
                pct = int((done / total) * 100) if total else 0
                self.progress_bar["maximum"] = total
                self.progress_bar["value"] = done
                self.lbl_summary.config(text=f"总数: {total}  |  已完成: {done}  |  成功: {success}  |  失败: {failed}  |  进度: {pct}%")
            elif action == "finish":
                self.is_running = False
                self.btn_start.configure(state=tk.NORMAL)
                self.btn_stop.configure(state=tk.DISABLED)
                if self.failed_items:
                    self.btn_retry_failed.configure(state=tk.NORMAL, text=f"↻ 重试失败账号 ({len(self.failed_items)})")
                    self.btn_copy_failed.configure(state=tk.NORMAL)
                else:
                    self.btn_retry_failed.configure(state=tk.DISABLED, text="↻ 重试失败账号")
                    self.btn_copy_failed.configure(state=tk.DISABLED)
                messagebox.showinfo("任务完成", f"批量登录授权完成！\n成功: {data['success']} 个\n失败: {data['failed']} 个")
        self.after(100, self._process_ui_queue)

    def _start_task(self, specific_items: list[dict] | None = None) -> None:
        if self.is_running:
            return

        # 同步界面配置
        self.config_data["import_strategy"] = self.var_strategy.get()
        self.config_data["target_server"] = self.combo_target_server.get()
        self.config_data["base_proxy"] = self.var_proxy.get().strip()
        b_cfg = self.config_data.get("browser", {})
        b_cfg["channel"] = self.var_channel.get()
        b_cfg["headless"] = self.var_headless.get()
        self.config_data["browser"] = b_cfg
        save_config(self.config_data)

        if specific_items is not None:
            accounts_to_run = specific_items
        else:
            content = self.txt_accounts.get("1.0", tk.END).strip()
            accounts_to_run = parse_card_key_accounts(content)

        if not accounts_to_run:
            messagebox.showwarning("提示", "请输入或粘贴有效卡密信息！")
            return

        self.is_running = True
        self.stop_requested = False
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self.btn_retry_failed.configure(state=tk.DISABLED)
        self.btn_copy_failed.configure(state=tk.DISABLED)
        self.failed_items = []

        # 启动后台异步工作线程
        threading.Thread(target=self._worker_thread, args=(accounts_to_run,), daemon=True).start()

    def _stop_task(self) -> None:
        if not self.is_running:
            return
        self.stop_requested = True
        self._log("用户点击了【停止任务】，正在优雅中止当前任务...")
        self.btn_stop.configure(state=tk.DISABLED)

    def _retry_failed(self) -> None:
        if not self.failed_items:
            messagebox.showinfo("提示", "暂无失败账号需要重试！")
            return
        items_to_retry = list(self.failed_items)
        self._log(f"用户触发重试：正在准备针对 {len(items_to_retry)} 个失败账号重新发起登录...")
        self._start_task(specific_items=items_to_retry)

    def _copy_failed(self) -> None:
        if not self.failed_items:
            messagebox.showinfo("提示", "暂无失败账号！")
            return
        lines = [f"{it['email']}----{it['password']}----{it.get('two_factor_secret', '')}" for it in self.failed_items]
        text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("成功", f"已复制 {len(self.failed_items)} 个失败账号卡密到剪贴板！")

    def _worker_thread(self, accounts: list[dict]) -> None:
        asyncio.run(self._async_worker(accounts))

    async def _async_worker(self, raw_accounts: list[dict]) -> None:
        dispatcher = MultiServerDispatcher(self.config_data)
        if not dispatcher.has_servers():
            self._log("错误：未配置任何可用的服务器节点！")
            self.ui_queue.put(("finish", {"success": 0, "failed": 0}))
            return

        self._log(">>> 1. 正在检查服务器连通性...")
        results = dispatcher.test_all_servers()
        for client, ok, msg in results:
            tag = "正常" if ok else "离线"
            self._log(f"  节点 [{client.name}]: {tag} ({msg})")

        # 自动排重检查
        pending_list: list[dict] = []
        if self.var_filter_existing.get():
            self._log(">>> 2. 正在向服务器拉取已有账号，执行查重排重...")
            existing_emails = dispatcher.get_global_existing_emails()
            self._log(f"  各服务器当前共记录已有账号: {len(existing_emails)} 个")
            for acc in raw_accounts:
                if acc["email"].lower() in existing_emails:
                    self._log(f"  [自动跳过已有账号]: {acc['email']}")
                else:
                    pending_list.append(acc)
        else:
            pending_list = raw_accounts

        if not pending_list:
            self._log("全部账号均已在系统中正常存在，无需重复登录！")
            self.ui_queue.put(("finish", {"success": 0, "failed": 0}))
            return

        self._log(f">>> 3. 排重完成，本次待执行登录入库: {len(pending_list)} 个账号")

        # 初始化前端表格
        table_init_data = []
        for idx, it in enumerate(pending_list, 1):
            it["id"] = f"acc_{idx}"
            it["idx"] = idx
            it["server"] = "自动分发"
            table_init_data.append(it)

        self.ui_queue.put(("table_init", table_init_data))
        self.ui_queue.put(("progress", (len(pending_list), 0, 0, 0)))

        # 循环登录
        from playwright.async_api import async_playwright

        base_proxy = self.config_data.get("base_proxy", "").strip()
        browser_cfg = self.config_data.get("browser", {})
        max_retries = max(1, int(self.config_data.get("max_retries", 2)))

        success_count = 0
        failed_count = 0

        async with async_playwright() as playwright:
            for idx, item in enumerate(pending_list, 1):
                if self.stop_requested:
                    self._log("任务已手动停止！剩余账号已被跳过。")
                    break

                email = item["email"]
                pwd = item["password"]
                secret = item.get("two_factor_secret", "")
                target_server = dispatcher.pick_next_server()
                iid = item["id"]

                self.ui_queue.put(("table_update", (iid, "登录中", f"正在使用 {browser_cfg.get('channel', 'msedge')} 登录...")))
                self._log(f"[{idx}/{len(pending_list)}] 正在登录: {email} -> 目标服务器: [{target_server.name}]")

                logged_payload = None
                last_err = ""

                for attempt in range(1, max_retries + 1):
                    if self.stop_requested:
                        break
                    salt = f"r{attempt}_{int(time.time()) % 1000}"
                    acc_proxy = derive_isolated_proxy(base_proxy, email, salt=salt)
                    if attempt > 1:
                        self.ui_queue.put(("table_update", (iid, "重试中", f"第 {attempt} 次重试，已切全新代理...")))
                        self._log(f"  重试 [{attempt}/{max_retries}] 更换全新代理出口并在 2 秒后拉起窗口...")
                        await asyncio.sleep(2)

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
                        self._log(f"  尝试 [{attempt}/{max_retries}] 失败: {last_err}")

                if logged_payload is not None:
                    self.ui_queue.put(("table_update", (iid, "上传中", "授权成功，正在推送至服务端...")))
                    ok, push_msg = target_server.push_account(logged_payload)
                    if ok:
                        self._log(f"  ✓ 成功登录并已入库至 [{target_server.name}] (Plan: {logged_payload.get('plan_type')})")
                        self.ui_queue.put(("table_update", (iid, "✓ 成功", f"入库成功 (Plan: {logged_payload.get('plan_type')})")))
                        success_count += 1
                    else:
                        self._log(f"  ✗ 服务端入库报错: {push_msg}")
                        self.ui_queue.put(("table_update", (iid, "✗ 失败", f"上传服务端失败: {push_msg}")))
                        item["error"] = push_msg
                        self.failed_items.append(item)
                        failed_count += 1
                else:
                    self._log(f"  ✗ 账号 {email} 登录全部重试失败: {last_err}")
                    self.ui_queue.put(("table_update", (iid, "✗ 失败", last_err)))
                    item["error"] = last_err
                    self.failed_items.append(item)
                    failed_count += 1

                self.ui_queue.put(("progress", (len(pending_list), idx, success_count, failed_count)))
                await asyncio.sleep(1)

        self._log(f"=== 全部批次执行结束：成功 {success_count} 个，失败 {failed_count} 个 ===")
        self.ui_queue.put(("finish", {"success": success_count, "failed": failed_count}))

    def _test_all_servers(self) -> None:
        dispatcher = MultiServerDispatcher(self.config_data)
        results = dispatcher.test_all_servers()
        for idx, (client, ok, msg) in enumerate(results):
            children = self.srv_tree.get_children()
            if idx < len(children):
                iid = children[idx]
                vals = list(self.srv_tree.item(iid)["values"])
                vals[4] = f"✓ {msg}" if ok else f"✗ {msg}"
                self.srv_tree.item(iid, values=vals)
        messagebox.showinfo("测试结果", "所有服务器节点连通性测试已完成！")

    def _add_or_update_server(self) -> None:
        name = self.var_srv_name.get().strip()
        url = self.var_srv_url.get().strip()
        key = self.var_srv_key.get().strip()
        enabled = self.var_srv_enabled.get()

        if not name or not url:
            messagebox.showwarning("提示", "节点名称和服务地址不能为空！")
            return

        servers = self.config_data.get("servers", [])
        found = False
        for s in servers:
            if s.get("name") == name:
                s["url"] = url
                s["auth_key"] = key
                s["enabled"] = enabled
                found = True
                break

        if not found:
            servers.append({"name": name, "url": url, "auth_key": key, "enabled": enabled, "target_group_id": None})

        self.config_data["servers"] = servers
        save_config(self.config_data)
        self._refresh_servers_tree()
        messagebox.showinfo("成功", f"节点 [{name}] 已保存！")

    def _delete_selected_server(self) -> None:
        selected = self.srv_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先在上方表格中选中要删除的节点！")
            return
        item = self.srv_tree.item(selected[0])
        name = item["values"][1]
        servers = [s for s in self.config_data.get("servers", []) if s.get("name") != name]
        self.config_data["servers"] = servers
        save_config(self.config_data)
        self._refresh_servers_tree()
        messagebox.showinfo("成功", f"节点 [{name}] 已删除！")

    def _save_servers_config(self) -> None:
        save_config(self.config_data)
        messagebox.showinfo("成功", "服务器配置已保存！")


if __name__ == "__main__":
    app = LoginHelperGUI()
    app.mainloop()
