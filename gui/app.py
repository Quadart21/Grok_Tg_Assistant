from __future__ import annotations

import asyncio
import queue
import threading
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk

from core.config import AppConfig, ProxyConfig, RoleGroup, RolesConfig
from core.dialog_engine import DialogEngine, EngineStats
from core.guide_server import GuideServer
from core.proxy_manager import load_proxies, save_proxies
from core.session_manager import discover_sessions
from core.state_store import StateStore
from gui.helpers import hint_label, labeled_entry, section_title


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class OutreachApp(ctk.CTk):
    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self.base_dir = base_dir
        self.config_path = base_dir / "config" / "settings.json"
        self.roles_path = base_dir / "roles.json"
        self.proxies_path = base_dir / "config" / "proxies.json"

        self.config = self._load_config()
        self.roles = self._load_roles()
        self.proxies: dict[str, ProxyConfig] = load_proxies(self.proxies_path)
        self.state_store = StateStore(base_dir / self.config.state_file)
        self.engine: DialogEngine | None = None
        self.worker_thread: threading.Thread | None = None
        self.ui_queue: queue.Queue = queue.Queue()
        self.role_group_widgets: list[dict] = []
        self._show_secrets = False
        self.guide_server = GuideServer(base_dir / "web" / "guidance")

        self.title("Telegram Рассылка — Панель управления")
        self.geometry("1100x820")
        self.minsize(900, 680)

        self._build_ui()
        self._refresh_accounts()
        self.after(100, self._process_ui_queue)
        self.guide_server.start()
        if not self.config.telegram_api_id and not self.config.grok_api_key:
            self.after(500, self._open_web_guidance)

    def _open_web_guidance(self) -> None:
        self.guide_server.open_in_browser()

    def _load_config(self) -> AppConfig:
        if not self.config_path.exists():
            example = self.base_dir / "config" / "settings.example.json"
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if example.exists():
                self.config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                AppConfig(telegram_api_id=0, telegram_api_hash="", grok_api_key="").save(
                    self.config_path
                )
        cfg = AppConfig.load(self.config_path)
        self.proxies_path = self.base_dir / cfg.proxies_file
        if self.proxies_path.suffix != ".json":
            self.proxies_path = self.base_dir / "config" / "proxies.json"
        return cfg

    def _load_roles(self) -> RolesConfig:
        if not self.roles_path.exists():
            example = self.base_dir / "roles.example.json"
            if example.exists():
                self.roles_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return RolesConfig.load(self.roles_path)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))
        status_row = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        status_row.pack(fill="x", padx=12, pady=10)
        status_row.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_row,
            text="",
            anchor="w",
            font=ctk.CTkFont(size=13),
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        ctk.CTkButton(
            status_row,
            text="📖  Инструкция",
            width=130,
            command=self._open_web_guidance,
        ).grid(row=0, column=1, padx=(12, 0))

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

        self.tab_main = self.tabs.add("  1. Рассылка  ")
        self.tab_connect = self.tabs.add("  2. Подключение  ")
        self.tab_accounts = self.tabs.add("  3. Аккаунты  ")
        self.tab_roles = self.tabs.add("  4. Стиль общения  ")
        self.tab_dialogs = self.tabs.add("  5. Диалоги  ")

        self._build_main_tab()
        self._build_connect_tab()
        self._build_accounts_tab()
        self._build_roles_tab()
        self._build_dialogs_tab()
        self._update_status_bar()

    def _build_main_tab(self) -> None:
        self.tab_main.grid_columnconfigure(0, weight=1)
        self.tab_main.grid_rowconfigure(5, weight=1)

        section_title(self.tab_main, "Кому написать", 0)
        hint_label(
            self.tab_main,
            "Впишите username получателей — по одному на строку. Можно с @ или без.",
            1,
        )

        self.targets_text = ctk.CTkTextbox(self.tab_main, height=140)
        self.targets_text.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        self.targets_text.insert("1.0", "ivan_petrov\nmaria_shop")

        hint_label(self.tab_main, "Дополнительная подсказка для текста (необязательно):", 3)
        self.context_entry = ctk.CTkEntry(
            self.tab_main,
            placeholder_text="Например: предложить сотрудничество, поздороваться",
        )
        self.context_entry.grid(row=4, column=0, sticky="ew", padx=12, pady=4)

        options_frame = ctk.CTkFrame(self.tab_main)
        options_frame.grid(row=5, column=0, sticky="ew", padx=12, pady=8)

        self.enable_dialog_var = ctk.BooleanVar(value=True)
        self.resume_dialog_var = ctk.BooleanVar(value=True)

        ctk.CTkCheckBox(
            options_frame,
            text="Вести диалог — отвечать на сообщения автоматически (Grok)",
            variable=self.enable_dialog_var,
        ).pack(anchor="w", padx=12, pady=(10, 4))

        ctk.CTkCheckBox(
            options_frame,
            text="Продолжить прошлые диалоги после паузы (память сохраняется)",
            variable=self.resume_dialog_var,
        ).pack(anchor="w", padx=12, pady=(4, 10))

        btn_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        btn_frame.grid(row=6, column=0, sticky="ew", padx=12, pady=4)
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="▶  Запустить",
            height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_outreach,
        )
        self.start_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.resume_btn = ctk.CTkButton(
            btn_frame,
            text="↻  Продолжить диалоги",
            height=44,
            command=self._start_resume_only,
        )
        self.resume_btn.grid(row=0, column=1, padx=4, sticky="ew")

        self.stop_btn = ctk.CTkButton(
            btn_frame,
            text="■  Остановить",
            height=44,
            fg_color="#8b0000",
            hover_color="#a00000",
            command=self._stop_outreach,
            state="disabled",
        )
        self.stop_btn.grid(row=0, column=2, padx=(4, 0), sticky="ew")

        self.stats_label = ctk.CTkLabel(
            self.tab_main,
            text="Ожидание запуска",
            font=ctk.CTkFont(size=13),
        )
        self.stats_label.grid(row=7, column=0, sticky="ew", padx=12, pady=(0, 4))

        ctk.CTkLabel(self.tab_main, text="Что происходит:", anchor="w").grid(
            row=8, column=0, sticky="ew", padx=12
        )
        self.log_text = ctk.CTkTextbox(self.tab_main, state="disabled")
        self.log_text.grid(row=9, column=0, sticky="nsew", padx=12, pady=(4, 12))
        self.tab_main.grid_rowconfigure(9, weight=1)

    def _build_connect_tab(self) -> None:
        self.tab_connect.grid_columnconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self.tab_connect)
        scroll.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        scroll.grid_columnconfigure(1, weight=1)
        self.tab_connect.grid_rowconfigure(0, weight=1)

        section_title(scroll, "Telegram — ключи приложения", 0)
        hint_label(
            scroll,
            "Нужны один раз. Получите бесплатно на my.telegram.org → API development tools.",
            1,
        )

        self.api_id_entry = labeled_entry(scroll, 2, "API ID:", "Например: 12345678")
        self.api_hash_entry = labeled_entry(scroll, 3, "API Hash:", "Длинная строка букв и цифр")

        section_title(scroll, "Grok (xAI) — ключ для генерации текста", 4)
        hint_label(
            scroll,
            "Grok придумывает текст первого сообщения. Ключ берётся на console.x.ai",
            5,
        )

        self.grok_key_entry = labeled_entry(
            scroll, 6, "Ключ Grok:", "xai-...", show="*"
        )
        self.grok_model_entry = labeled_entry(
            scroll, 7, "Модель Grok:", "grok-3-mini"
        )

        section_title(scroll, "Дополнительно", 8)
        hint_label(scroll, "Обычно менять не нужно.", 9)

        self.delay_entry = labeled_entry(
            scroll, 10, "Пауза между сообщениями (сек):", "30"
        )
        self.concurrent_entry = labeled_entry(
            scroll, 11, "Сколько аккаунтов одновременно:", "5"
        )
        self.language_entry = labeled_entry(scroll, 12, "Язык сообщений:", "ru")
        self.reply_min_entry = labeled_entry(scroll, 13, "Пауза перед ответом, от (сек):", "5")
        self.reply_max_entry = labeled_entry(scroll, 14, "Пауза перед ответом, до (сек):", "25")

        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.grid(row=15, column=0, columnspan=2, sticky="ew", padx=12, pady=16)
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row,
            text="👁  Показать / скрыть ключи",
            command=self._toggle_secrets,
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")

        ctk.CTkButton(
            btn_row,
            text="💾  Сохранить подключение",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            command=self._save_connection,
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        self._fill_connection_fields()

    def _build_accounts_tab(self) -> None:
        self.tab_accounts.grid_columnconfigure(0, weight=1)
        self.tab_accounts.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self.tab_accounts, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top,
            text="Папка с аккаунтами:",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, padx=(4, 8), sticky="w")

        sessions_path = self.base_dir / self.config.sessions_dir
        self.sessions_path_label = ctk.CTkLabel(top, text=str(sessions_path), anchor="w")
        self.sessions_path_label.grid(row=0, column=1, sticky="w")

        ctk.CTkButton(top, text="📂  Открыть папку", width=140, command=self._open_sessions_folder).grid(
            row=0, column=2, padx=4
        )
        ctk.CTkButton(top, text="↻  Обновить список", width=140, command=self._refresh_accounts).grid(
            row=0, column=3, padx=4
        )

        hint_label(
            self.tab_accounts,
            "Положите файлы .session или папки tdata в эту папку — программа подхватит их автоматически. "
            "Выберите аккаунт в таблице и задайте ему прокси справа.",
            1,
            columnspan=1,
        )

        content = ctk.CTkFrame(self.tab_accounts)
        content.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)
        self.tab_accounts.grid_rowconfigure(2, weight=1)

        table_frame = ctk.CTkFrame(content)
        table_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background="#2b2b2b",
            foreground="white",
            fieldbackground="#2b2b2b",
            rowheight=30,
        )
        style.configure("Treeview.Heading", background="#1f538d", foreground="white")

        columns = ("account", "format", "proxy", "role")
        self.accounts_tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        self.accounts_tree.heading("account", text="Аккаунт")
        self.accounts_tree.heading("format", text="Тип")
        self.accounts_tree.heading("proxy", text="Прокси")
        self.accounts_tree.heading("role", text="Стиль")
        self.accounts_tree.column("account", width=160)
        self.accounts_tree.column("format", width=80)
        self.accounts_tree.column("proxy", width=180)
        self.accounts_tree.column("role", width=120)
        self.accounts_tree.grid(row=0, column=0, sticky="nsew")
        self.accounts_tree.bind("<<TreeviewSelect>>", self._on_account_selected)

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.accounts_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.accounts_tree.configure(yscrollcommand=scroll.set)

        proxy_panel = ctk.CTkFrame(content)
        proxy_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        proxy_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            proxy_panel,
            text="Прокси для выбранного аккаунта",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        self.proxy_account_label = ctk.CTkLabel(
            proxy_panel, text="Выберите аккаунт слева", text_color="#888888"
        )
        self.proxy_account_label.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        ctk.CTkLabel(proxy_panel, text="Тип прокси:", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=12, pady=(4, 0)
        )
        self.proxy_type_var = ctk.StringVar(value="socks5")
        self.proxy_type_menu = ctk.CTkOptionMenu(
            proxy_panel,
            variable=self.proxy_type_var,
            values=["socks5", "socks4", "http"],
        )
        self.proxy_type_menu.grid(row=3, column=0, sticky="ew", padx=12, pady=4)

        ctk.CTkLabel(proxy_panel, text="Адрес (IP или домен):", anchor="w").grid(
            row=4, column=0, sticky="ew", padx=12, pady=(4, 0)
        )
        self.proxy_host_entry = ctk.CTkEntry(proxy_panel, placeholder_text="127.0.0.1")
        self.proxy_host_entry.grid(row=5, column=0, sticky="ew", padx=12, pady=4)

        ctk.CTkLabel(proxy_panel, text="Порт:", anchor="w").grid(row=6, column=0, sticky="ew", padx=12, pady=(4, 0))
        self.proxy_port_entry = ctk.CTkEntry(proxy_panel, placeholder_text="1080")
        self.proxy_port_entry.grid(row=7, column=0, sticky="ew", padx=12, pady=4)

        ctk.CTkLabel(proxy_panel, text="Логин (если есть):", anchor="w").grid(
            row=8, column=0, sticky="ew", padx=12, pady=(4, 0)
        )
        self.proxy_user_entry = ctk.CTkEntry(proxy_panel)
        self.proxy_user_entry.grid(row=9, column=0, sticky="ew", padx=12, pady=4)

        ctk.CTkLabel(proxy_panel, text="Пароль (если есть):", anchor="w").grid(
            row=10, column=0, sticky="ew", padx=12, pady=(4, 0)
        )
        self.proxy_pass_entry = ctk.CTkEntry(proxy_panel, show="*")
        self.proxy_pass_entry.grid(row=11, column=0, sticky="ew", padx=12, pady=4)

        proxy_btns = ctk.CTkFrame(proxy_panel, fg_color="transparent")
        proxy_btns.grid(row=12, column=0, sticky="ew", padx=12, pady=12)
        proxy_btns.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            proxy_btns, text="💾  Сохранить прокси", command=self._save_current_proxy
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(
            proxy_btns,
            text="✕  Убрать прокси",
            fg_color="#555555",
            command=self._clear_current_proxy,
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        ctk.CTkButton(
            proxy_panel,
            text="📋  Вставить список прокси",
            command=self._open_bulk_proxy_dialog,
        ).grid(row=13, column=0, sticky="ew", padx=12, pady=(0, 8))

        hint_label(
            proxy_panel,
            "Массовая вставка: по одной строке на аккаунт в порядке таблицы.\n"
            "Формат: ip:port  или  ip:port:логин:пароль",
            14,
            columnspan=1,
        )

        bottom = ctk.CTkFrame(self.tab_accounts, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=8, pady=8)
        self.accounts_count_label = ctk.CTkLabel(bottom, text="Аккаунтов: 0")
        self.accounts_count_label.pack(side="left", padx=4)
        ctk.CTkLabel(
            bottom,
            text="Для рассылки: выделите нужные аккаунты (Ctrl+клик). Если ничего не выбрано — все.",
            text_color="#aaaaaa",
        ).pack(side="right", padx=4)

        self._selected_proxy_account: str | None = None

    def _build_roles_tab(self) -> None:
        self.tab_roles.grid_columnconfigure(0, weight=1)
        self.tab_roles.grid_rowconfigure(2, weight=1)

        section_title(self.tab_roles, "Стиль по умолчанию", 0)
        hint_label(
            self.tab_roles,
            "Так будет писать Grok, если аккаунт не входит ни в одну группу ниже.",
            1,
        )

        self.default_role_text = ctk.CTkTextbox(self.tab_roles, height=80)
        self.default_role_text.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        self.default_role_text.insert("1.0", self.roles.default_role)

        section_title(self.tab_roles, "Группы стилей", 3)
        hint_label(
            self.tab_roles,
            "Создайте группы с разным «характером» и отметьте, какие аккаунты к какой группе относятся.",
            4,
        )

        header = ctk.CTkFrame(self.tab_roles, fg_color="transparent")
        header.grid(row=5, column=0, sticky="ew", padx=12, pady=4)
        ctk.CTkButton(
            header, text="+  Добавить группу", command=self._add_role_group
        ).pack(side="right")

        self.roles_scroll = ctk.CTkScrollableFrame(self.tab_roles)
        self.roles_scroll.grid(row=6, column=0, sticky="nsew", padx=12, pady=4)
        self.roles_scroll.grid_columnconfigure(0, weight=1)
        self.tab_roles.grid_rowconfigure(6, weight=1)

        self._render_role_groups()

        ctk.CTkButton(
            self.tab_roles,
            text="💾  Сохранить стили общения",
            height=40,
            font=ctk.CTkFont(weight="bold"),
            command=self._save_roles,
        ).grid(row=7, column=0, sticky="ew", padx=12, pady=12)

    def _build_dialogs_tab(self) -> None:
        self.tab_dialogs.grid_columnconfigure(0, weight=1)
        self.tab_dialogs.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self.tab_dialogs, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(
            top,
            text="Сохранённые переписки — программа помнит их между запусками",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left", padx=4)
        ctk.CTkButton(top, text="↻  Обновить", width=120, command=self._refresh_dialogs).pack(side="right")

        table_frame = ctk.CTkFrame(self.tab_dialogs)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        columns = ("account", "target", "status", "messages", "last")
        self.dialogs_tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.dialogs_tree.heading("account", text="Аккаунт")
        self.dialogs_tree.heading("target", text="Кому")
        self.dialogs_tree.heading("status", text="Статус")
        self.dialogs_tree.heading("messages", text="Сообщений")
        self.dialogs_tree.heading("last", text="Последняя активность")
        self.dialogs_tree.column("account", width=140)
        self.dialogs_tree.column("target", width=140)
        self.dialogs_tree.column("status", width=100)
        self.dialogs_tree.column("messages", width=90)
        self.dialogs_tree.column("last", width=180)
        self.dialogs_tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.dialogs_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.dialogs_tree.configure(yscrollcommand=scroll.set)

        hint_label(
            self.tab_dialogs,
            "«На паузе» — диалог сохранён, можно продолжить кнопкой «Продолжить диалоги» на вкладке 1. "
            "Роли и прокси для каждого аккаунта тоже запоминаются.",
            2,
            columnspan=1,
        )
        self.dialogs_count_label = ctk.CTkLabel(self.tab_dialogs, text="Диалогов: 0")
        self.dialogs_count_label.grid(row=3, column=0, sticky="w", padx=12, pady=8)

        self._refresh_dialogs()

    def _refresh_dialogs(self) -> None:
        self.state_store.load()
        for item in self.dialogs_tree.get_children():
            self.dialogs_tree.delete(item)

        status_map = {"active": "активен", "paused": "на паузе", "closed": "закрыт"}
        for dialog in self.state_store.list_all_dialogs():
            last = (dialog.last_activity or dialog.created_at or "")[:19].replace("T", " ")
            self.dialogs_tree.insert(
                "",
                "end",
                values=(
                    dialog.account_id,
                    f"@{dialog.target_username}",
                    status_map.get(dialog.status, dialog.status),
                    len(dialog.messages),
                    last or "—",
                ),
            )

        paused = len(self.state_store.list_all_dialogs({"paused"}))
        active = len(self.state_store.list_all_dialogs({"active"}))
        total = len(self.state_store.list_all_dialogs())
        self.dialogs_count_label.configure(
            text=f"Диалогов: {total}  (на паузе: {paused}, активных: {active})"
        )

    def _fill_connection_fields(self) -> None:
        fields = {
            self.api_id_entry: str(self.config.telegram_api_id or ""),
            self.api_hash_entry: self.config.telegram_api_hash,
            self.grok_key_entry: self.config.grok_api_key,
            self.grok_model_entry: self.config.grok_model,
            self.delay_entry: str(self.config.delay_between_messages_sec),
            self.concurrent_entry: str(self.config.max_concurrent_accounts),
            self.language_entry: self.config.message_language,
            self.reply_min_entry: str(self.config.reply_delay_min_sec),
            self.reply_max_entry: str(self.config.reply_delay_max_sec),
        }
        for entry, value in fields.items():
            entry.delete(0, "end")
            entry.insert(0, value)

    def _toggle_secrets(self) -> None:
        self._show_secrets = not self._show_secrets
        show = "" if self._show_secrets else "*"
        self.grok_key_entry.configure(show=show)
        self.proxy_pass_entry.configure(show=show)

    def _save_connection(self) -> None:
        try:
            self.config.telegram_api_id = int(self.api_id_entry.get().strip() or "0")
            self.config.telegram_api_hash = self.api_hash_entry.get().strip()
            self.config.grok_api_key = self.grok_key_entry.get().strip()
            self.config.grok_model = self.grok_model_entry.get().strip() or "grok-3-mini"
            self.config.delay_between_messages_sec = int(self.delay_entry.get().strip() or "30")
            self.config.max_concurrent_accounts = int(self.concurrent_entry.get().strip() or "5")
            self.config.message_language = self.language_entry.get().strip() or "ru"
            self.config.reply_delay_min_sec = int(self.reply_min_entry.get().strip() or "5")
            self.config.reply_delay_max_sec = int(self.reply_max_entry.get().strip() or "25")
            self.config.proxies_file = "config/proxies.json"
            self.config.state_file = "data/state.json"
            self.config.save(self.config_path)
            self.proxies_path = self.base_dir / "config" / "proxies.json"
            self._update_status_bar()
            messagebox.showinfo("Готово", "Настройки подключения сохранены.")
        except ValueError:
            messagebox.showerror("Ошибка", "Проверьте числа: API ID, пауза и количество аккаунтов должны быть цифрами.")

    def _update_status_bar(self) -> None:
        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        has_tg = bool(self.config.telegram_api_id and self.config.telegram_api_hash)
        has_grok = bool(self.config.grok_api_key)
        has_accounts = len(sessions) > 0
        with_proxy = sum(1 for s in sessions if self._proxy_for_account(s.account_id))

        parts = []
        parts.append("✓ Telegram подключён" if has_tg else "✗ Укажите Telegram API (вкладка 2)")
        parts.append("✓ Grok настроен" if has_grok else "✗ Укажите ключ Grok (вкладка 2)")
        parts.append(f"✓ Аккаунтов: {len(sessions)}" if has_accounts else "✗ Нет аккаунтов в папке sessions")
        if has_accounts:
            parts.append(f"Прокси задано: {with_proxy} из {len(sessions)}")
            paused = len(self.state_store.list_all_dialogs({"paused"}))
            if paused:
                parts.append(f"Диалогов на паузе: {paused}")

        color = "#4ade80" if has_tg and has_grok and has_accounts else "#fbbf24"
        self.status_label.configure(text="   |   ".join(parts), text_color=color)

    def _proxy_for_account(self, account_id: str) -> ProxyConfig | None:
        binding = self.state_store.get_account_binding(account_id)
        if binding:
            saved = binding.to_proxy()
            if saved:
                return saved
        proxy = self.proxies.get(account_id)
        if proxy and proxy.host:
            return proxy
        return None

    def _role_label_for_account(self, account_id: str) -> str:
        binding = self.state_store.get_account_binding(account_id)
        if binding and binding.role_group_name:
            return binding.role_group_name
        for group in self.roles.groups:
            if account_id in group.accounts:
                return group.name
        return "по умолчанию"

    def _refresh_accounts(self) -> None:
        self.state_store.load()
        self.proxies = load_proxies(self.proxies_path)
        sessions_dir = self.base_dir / self.config.sessions_dir
        sessions = discover_sessions(sessions_dir)

        for item in self.accounts_tree.get_children():
            self.accounts_tree.delete(item)

        for session in sessions:
            proxy = self._proxy_for_account(session.account_id)
            proxy_str = f"{proxy.host}:{proxy.port}" if proxy else "не задан"
            role_name = self._role_label_for_account(session.account_id)

            self.accounts_tree.insert(
                "",
                "end",
                iid=session.account_id,
                values=(session.account_id, session.format.value, proxy_str, role_name),
            )

        self.accounts_count_label.configure(text=f"Аккаунтов: {len(sessions)}")
        self.sessions_path_label.configure(text=str(sessions_dir))
        self._update_status_bar()
        self._render_role_groups()

    def _on_account_selected(self, _event=None) -> None:
        selected = self.accounts_tree.selection()
        if not selected:
            self._selected_proxy_account = None
            self.proxy_account_label.configure(text="Выберите аккаунт слева", text_color="#888888")
            return

        account_id = selected[0]
        self._selected_proxy_account = account_id
        self.proxy_account_label.configure(text=f"Аккаунт: {account_id}", text_color="#ffffff")

        proxy = self._proxy_for_account(account_id)
        self.proxy_host_entry.delete(0, "end")
        self.proxy_port_entry.delete(0, "end")
        self.proxy_user_entry.delete(0, "end")
        self.proxy_pass_entry.delete(0, "end")

        if proxy:
            self.proxy_type_var.set(proxy.proxy_type)
            self.proxy_host_entry.insert(0, proxy.host)
            self.proxy_port_entry.insert(0, str(proxy.port) if proxy.port else "")
            self.proxy_user_entry.insert(0, proxy.username)
            self.proxy_pass_entry.insert(0, proxy.password)
        else:
            self.proxy_type_var.set("socks5")

    def _save_current_proxy(self) -> None:
        if not self._selected_proxy_account:
            messagebox.showwarning("Выберите аккаунт", "Сначала кликните на аккаунт в таблице слева.")
            return

        host = self.proxy_host_entry.get().strip()
        port_raw = self.proxy_port_entry.get().strip()
        if not host or not port_raw:
            messagebox.showwarning("Заполните поля", "Укажите адрес и порт прокси.")
            return

        try:
            port = int(port_raw)
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом.")
            return

        account_id = self._selected_proxy_account
        self.proxies[account_id] = ProxyConfig(
            account_id=account_id,
            proxy_type=self.proxy_type_var.get(),
            host=host,
            port=port,
            username=self.proxy_user_entry.get().strip(),
            password=self.proxy_pass_entry.get().strip(),
        )
        self.proxies_path.parent.mkdir(parents=True, exist_ok=True)
        save_proxies(self.proxies_path, self.proxies)
        role_prompt = self.roles.prompt_for_account(account_id)
        group_name = self._role_label_for_account(account_id)
        self.state_store.save_account_binding(account_id, role_prompt, self.proxies[account_id], group_name)
        self._refresh_accounts()
        messagebox.showinfo("Готово", f"Прокси для «{account_id}» сохранён.")

    def _clear_current_proxy(self) -> None:
        if not self._selected_proxy_account:
            messagebox.showwarning("Выберите аккаунт", "Сначала кликните на аккаунт в таблице слева.")
            return
        account_id = self._selected_proxy_account
        self.proxies.pop(account_id, None)
        save_proxies(self.proxies_path, self.proxies)
        self._on_account_selected()
        self._refresh_accounts()

    def _open_bulk_proxy_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Массовая вставка прокси")
        dialog.geometry("520x420")
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="Вставьте прокси — по одной строке на каждый аккаунт\n"
            "в том же порядке, как в таблице (сверху вниз).\n"
            "Формат:  ip:port  или  ip:port:логин:пароль",
            justify="left",
        ).pack(padx=16, pady=(16, 8), anchor="w")

        textbox = ctk.CTkTextbox(dialog, height=220)
        textbox.pack(fill="both", expand=True, padx=16, pady=8)

        def apply() -> None:
            accounts = list(self.accounts_tree.get_children())
            lines = [ln.strip() for ln in textbox.get("1.0", "end").splitlines() if ln.strip()]
            if not lines:
                messagebox.showwarning("Пусто", "Вставьте хотя бы одну строку.", parent=dialog)
                return
            if len(lines) > len(accounts):
                messagebox.showwarning(
                    "Слишком много строк",
                    f"Аккаунтов: {len(accounts)}, строк прокси: {len(lines)}.\n"
                    "Лишние строки будут проигнорированы.",
                    parent=dialog,
                )

            applied = 0
            for account_id, line in zip(accounts, lines):
                parts = line.split(":")
                if len(parts) < 2:
                    continue
                host = parts[0].strip()
                try:
                    port = int(parts[1].strip())
                except ValueError:
                    continue
                username = parts[2].strip() if len(parts) > 2 else ""
                password = parts[3].strip() if len(parts) > 3 else ""
                self.proxies[account_id] = ProxyConfig(
                    account_id=account_id,
                    proxy_type=self.proxy_type_var.get(),
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                )
                applied += 1

            save_proxies(self.proxies_path, self.proxies)
            self._refresh_accounts()
            dialog.destroy()
            messagebox.showinfo("Готово", f"Прокси назначены для {applied} аккаунтов.")

        ctk.CTkButton(dialog, text="Применить", command=apply).pack(pady=12)

    def _get_all_account_ids(self) -> list[str]:
        return list(self.accounts_tree.get_children())

    def _render_role_groups(self) -> None:
        for widget in self.roles_scroll.winfo_children():
            widget.destroy()
        self.role_group_widgets.clear()

        account_ids = self._get_all_account_ids()

        for idx, group in enumerate(self.roles.groups):
            frame = ctk.CTkFrame(self.roles_scroll)
            frame.grid(row=idx, column=0, sticky="ew", pady=8)
            frame.grid_columnconfigure(0, weight=1)

            name_entry = ctk.CTkEntry(frame, placeholder_text="Название группы, например: Продажи")
            name_entry.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
            name_entry.insert(0, group.name)

            ctk.CTkLabel(frame, text="Как должен писать Grok для этой группы:", anchor="w").grid(
                row=1, column=0, sticky="ew", padx=12, pady=(4, 0)
            )
            prompt_text = ctk.CTkTextbox(frame, height=70)
            prompt_text.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
            prompt_text.insert("1.0", group.role_prompt)

            ctk.CTkLabel(frame, text="Отметьте аккаунты этой группы:", anchor="w").grid(
                row=3, column=0, sticky="ew", padx=12, pady=(8, 0)
            )

            checks_frame = ctk.CTkScrollableFrame(frame, height=100)
            checks_frame.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
            checks_frame.grid_columnconfigure(0, weight=1)

            check_vars: dict[str, ctk.BooleanVar] = {}
            if account_ids:
                for col, acc_id in enumerate(account_ids):
                    var = ctk.BooleanVar(value=acc_id in group.accounts)
                    check_vars[acc_id] = var
                    ctk.CTkCheckBox(checks_frame, text=acc_id, variable=var).grid(
                        row=col // 3, column=col % 3, sticky="w", padx=8, pady=2
                    )
            else:
                ctk.CTkLabel(
                    checks_frame,
                    text="Сначала добавьте аккаунты во вкладке «3. Аккаунты»",
                    text_color="#888888",
                ).grid(row=0, column=0, padx=8, pady=4)

            ctk.CTkButton(
                frame,
                text="Удалить группу",
                width=120,
                fg_color="#8b0000",
                command=lambda i=idx: self._remove_role_group(i),
            ).grid(row=5, column=0, sticky="e", padx=12, pady=(4, 12))

            self.role_group_widgets.append(
                {"name": name_entry, "prompt": prompt_text, "checks": check_vars}
            )

    def _add_role_group(self) -> None:
        self.roles.groups.append(
            RoleGroup(
                name="Новая группа",
                role_prompt="Вы вежливый собеседник. Пишете первым, коротко и по делу.",
                accounts=[],
            )
        )
        self._render_role_groups()

    def _remove_role_group(self, index: int) -> None:
        if 0 <= index < len(self.roles.groups):
            self.roles.groups.pop(index)
            self._render_role_groups()

    def _save_roles(self) -> None:
        self.roles.default_role = self.default_role_text.get("1.0", "end").strip()
        groups: list[RoleGroup] = []
        for widget in self.role_group_widgets:
            accounts = [acc for acc, var in widget["checks"].items() if var.get()]
            groups.append(
                RoleGroup(
                    name=widget["name"].get().strip() or "Без названия",
                    role_prompt=widget["prompt"].get("1.0", "end").strip(),
                    accounts=accounts,
                )
            )
        self.roles.groups = groups
        self.roles.save(self.roles_path)
        self._refresh_accounts()
        messagebox.showinfo("Готово", "Стили общения сохранены.")

    def _get_selected_account_ids(self) -> list[str] | None:
        selected = self.accounts_tree.selection()
        return list(selected) if selected else None

    def _start_resume_only(self) -> None:
        self._run_engine([], resume_only=True)

    def _start_outreach(self) -> None:
        targets_raw = self.targets_text.get("1.0", "end").strip()
        targets = [line.strip().lstrip("@") for line in targets_raw.splitlines() if line.strip()]
        if not targets and not self.resume_dialog_var.get():
            messagebox.showerror(
                "Кому писать?",
                "Впишите username или включите «Продолжить прошлые диалоги».",
            )
            return
        self._run_engine(targets, resume_only=False)

    def _run_engine(self, targets: list[str], resume_only: bool) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("Подождите", "Уже работает.")
            return

        self._save_connection_silent()

        if not self.config.telegram_api_id or not self.config.telegram_api_hash:
            messagebox.showerror(
                "Не хватает данных",
                "Откройте вкладку «2. Подключение» и укажите Telegram API ID и Hash.",
            )
            self.tabs.set("  2. Подключение  ")
            return
        if not self.config.grok_api_key:
            messagebox.showerror(
                "Не хватает данных",
                "Откройте вкладку «2. Подключение» и укажите ключ Grok.",
            )
            self.tabs.set("  2. Подключение  ")
            return

        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        if not sessions:
            messagebox.showerror(
                "Нет аккаунтов",
                "Положите сессии в папку sessions и нажмите «Обновить список».",
            )
            self.tabs.set("  3. Аккаунты  ")
            return

        if resume_only:
            self.state_store.load()
            if not self.state_store.list_all_dialogs({"paused", "active"}):
                messagebox.showinfo(
                    "Нет диалогов",
                    "Сохранённых диалогов пока нет. Сначала запустите рассылку с «Вести диалог».",
                )
                return

        self.roles = RolesConfig.load(self.roles_path)
        account_ids = self._get_selected_account_ids()
        extra_context = self.context_entry.get().strip()
        enable_dialog = self.enable_dialog_var.get() or resume_only
        resume_existing = self.resume_dialog_var.get() or resume_only

        self.start_btn.configure(state="disabled")
        self.resume_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        self.engine = DialogEngine(
            self.config,
            self.roles,
            self.base_dir,
            log=lambda msg: self.ui_queue.put(("log", msg)),
            on_task=lambda task: self.ui_queue.put(("task", task)),
            on_stats=lambda stats: self.ui_queue.put(("stats", stats)),
        )

        run_targets = [] if resume_only else targets

        def run_async() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self.engine.run(
                        run_targets,
                        account_ids,
                        extra_context,
                        enable_dialog=enable_dialog,
                        resume_existing=resume_existing,
                    )
                )
            finally:
                loop.close()
                self.ui_queue.put(("done", None))

        self.worker_thread = threading.Thread(target=run_async, daemon=True)
        self.worker_thread.start()
        if resume_only:
            self._append_log("↻ Продолжаем сохранённые диалоги...")
        else:
            self._append_log("▶ Запуск...")

    def _save_connection_silent(self) -> None:
        try:
            self.config.telegram_api_id = int(self.api_id_entry.get().strip() or "0")
            self.config.telegram_api_hash = self.api_hash_entry.get().strip()
            self.config.grok_api_key = self.grok_key_entry.get().strip()
            self.config.grok_model = self.grok_model_entry.get().strip() or "grok-3-mini"
            self.config.delay_between_messages_sec = int(self.delay_entry.get().strip() or "30")
            self.config.max_concurrent_accounts = int(self.concurrent_entry.get().strip() or "5")
            self.config.message_language = self.language_entry.get().strip() or "ru"
            self.config.reply_delay_min_sec = int(self.reply_min_entry.get().strip() or "5")
            self.config.reply_delay_max_sec = int(self.reply_max_entry.get().strip() or "25")
            self.config.save(self.config_path)
            self._update_status_bar()
        except ValueError:
            pass

    def _stop_outreach(self) -> None:
        if self.engine:
            self.engine.stop()
            self._append_log("■ Останавливаем...")

    def _process_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "stats":
                    self._update_stats(payload)
                elif kind == "done":
                    self.start_btn.configure(state="normal")
                    self.resume_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self._refresh_dialogs()
                    self._update_status_bar()
                self.ui_queue.task_done()
        except queue.Empty:
            pass
        self.after(100, self._process_ui_queue)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_stats(self, stats: EngineStats) -> None:
        self.stats_label.configure(
            text=(
                f"Первых сообщений: {stats.success}/{stats.total}  •  "
                f"Ответов в диалоге: {stats.replies_sent}  •  "
                f"Ошибок: {stats.failed}  •  "
                f"Активных диалогов: {stats.active_dialogs}"
            )
        )

    def _open_sessions_folder(self) -> None:
        path = self.base_dir / self.config.sessions_dir
        path.mkdir(parents=True, exist_ok=True)
        import os

        os.startfile(str(path))


def run_app(base_dir: Path) -> None:
    app = OutreachApp(base_dir)
    app.mainloop()
