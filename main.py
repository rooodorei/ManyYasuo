"""ManyYasuo - modern batch 7-Zip compression workstation."""

import ctypes
import json
import multiprocessing
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinterdnd2 import DND_FILES
from tkinterdnd2.TkinterDnD import DnDWrapper, _require


APP_NAME = "批量压缩工作台"
APP_FONT = "Microsoft YaHei UI"
CONFIG_FILE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).with_name("config.json")

BG = "#F3F6FA"
SURFACE = "#FFFFFF"
SURFACE_2 = "#F8FAFC"
SURFACE_3 = "#E8EEF6"
BORDER = "#D6DFEA"
TEXT = "#0F172A"
MUTED = "#334155"
PRIMARY = "#635BFF"
PRIMARY_HOVER = "#5145CD"
SUCCESS = "#15803D"
WARNING = "#B45309"
DANGER = "#DC2626"


class ModernDnDWindow(ctk.CTk, DnDWrapper):
    """CustomTkinter root with tkinterdnd2 support."""

    def __init__(self):
        super().__init__()
        self.TkdndVersion = _require(self)


class PipelineApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1240x780")
        self.root.minsize(1000, 680)
        self.root.configure(fg_color=BG)

        self.max_cpu_threads = multiprocessing.cpu_count()
        self.left_rows = []
        self.right_rows = []
        self.is_running = False
        self.is_paused = False
        self.cancel_requested = False
        self.current_process = None
        self.current_row = None
        # Keep UI work bounded. Progress is also throttled by the worker, so
        # this queue cannot grow indefinitely during long compression jobs.
        self.ui_events = queue.Queue(maxsize=512)
        self.config = self.load_config()
        self.settings_expanded = False
        self.status_var = ctk.StringVar(value="")

        self.sevenz_path = self.config.get("7z_path", self.find_default_7z())
        self.setup_ui()
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self.handle_drop)
        self.poll_ui_events()

    @staticmethod
    def find_default_7z():
        candidates = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            r"C:\Program Files\7-Zip\7zG.exe",
            r"C:\Program Files (x86)\7-Zip\7zG.exe",
        ]
        return next((path for path in candidates if os.path.exists(path)), "")

    def load_config(self):
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_config(self):
        data = {
            "7z_path": self.entry_7z.get().strip(),
            "prefix": self.entry_prefix.get(),
            "tag_prefix": self.entry_tag_prefix.get(),
            "extension": self.entry_ext.get(),
            "lvl": self.combo_lvl.get(),
            "dict": self.combo_dict.get(),
            "word": self.combo_word.get(),
            "solid": self.combo_solid.get(),
            "threads": self.combo_threads.get(),
            "pwd": self.entry_pwd.get(),
            "hide_name": bool(self.var_hide.get()),
        }
        try:
            CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("已保存", f"配置已保存至\n{CONFIG_FILE}")
        except OSError as error:
            messagebox.showerror("无法保存", str(error))

    def setup_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.build_workspace()
        self.build_settings_card()
        self.build_action_dock()

    @staticmethod
    def card(parent, **kwargs):
        return ctk.CTkFrame(
            parent,
            fg_color=SURFACE,
            border_color=BORDER,
            border_width=1,
            corner_radius=14,
            **kwargs,
        )

    @staticmethod
    def title(parent, text, subtitle=""):
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.pack(fill="x", padx=20, pady=(17, 10))
        ctk.CTkLabel(line, text=text, text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        if subtitle:
            ctk.CTkLabel(line, text=subtitle, text_color=MUTED, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(10, 0))
        return line

    @staticmethod
    def secondary_button(parent, text, command, width=90):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=36,
            corner_radius=9,
            fg_color=SURFACE_3,
            hover_color="#DCE5F0",
            text_color="#334155",
            font=ctk.CTkFont(size=13, weight="bold"),
        )

    def build_workspace(self):
        workspace = ctk.CTkFrame(self.root, fg_color="transparent")
        workspace.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 10))
        workspace.grid_columnconfigure(0, weight=1)
        workspace.grid_rowconfigure(0, weight=1)
        self.build_pipeline(workspace)

    def build_pipeline(self, parent):
        pipeline = ctk.CTkFrame(parent, fg_color="transparent")
        pipeline.grid(row=0, column=0, sticky="nsew")
        pipeline.grid_rowconfigure(0, weight=1)
        pipeline.grid_columnconfigure(0, weight=1)
        pipeline.grid_columnconfigure(2, weight=1)

        self.build_left_panel(pipeline).grid(row=0, column=0, sticky="nsew")

        center = ctk.CTkFrame(pipeline, width=126, fg_color="transparent")
        center.grid(row=0, column=1, sticky="ns", padx=12)
        center.grid_propagate(False)
        center.grid_rowconfigure(0, weight=1)
        center.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(center, text="添加标签后", text_color=MUTED, font=ctk.CTkFont(size=13, weight="bold")).grid(row=1, column=0, pady=(0, 8))
        ctk.CTkButton(
            center,
            text="加入队列  →",
            command=self.do_restructure,
            width=126,
            height=46,
            corner_radius=12,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color="white",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=2, column=0, sticky="n")

        self.build_right_panel(pipeline).grid(row=0, column=2, sticky="nsew")

    def panel_header(self, panel, step, title, subtitle):
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 10))
        ctk.CTkLabel(
            head,
            text=step,
            width=30,
            height=30,
            corner_radius=10,
            fg_color="#EDE9FE",
            text_color="#6D28D9",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left")
        words = ctk.CTkFrame(head, fg_color="transparent")
        words.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(words, text=title, text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(words, text=subtitle, text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        return head

    def build_left_panel(self, parent):
        panel = self.card(parent)
        head = self.panel_header(panel, "01", "导入文件夹", "支持多选或直接拖放到窗口")
        self.secondary_button(head, "清空", self.clear_left_list, 66).pack(side="right")
        self.secondary_button(head, "选择文件夹", self.choose_folders, 104).pack(side="right", padx=(0, 8))

        number_card = ctk.CTkFrame(panel, fg_color="#F1F5F9", corner_radius=10)
        number_card.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(number_card, text="起始编号", text_color=MUTED, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(14, 8), pady=10)
        self.counter_var = ctk.StringVar(value="0001")
        self.counter_var.trace_add("write", self.revalidate_left_list)
        ctk.CTkEntry(number_card, textvariable=self.counter_var, width=90, height=34, corner_radius=8, fg_color=SURFACE_3, border_color=BORDER, justify="center").pack(side="left", pady=8)
        self.secondary_button(number_card, "提取最小编号", self.detect_min_number, 112).pack(side="left", padx=8, pady=8)

        self.frame_left = ctk.CTkScrollableFrame(
            panel,
            fg_color="#F1F5F9",
            corner_radius=10,
            scrollbar_button_color="#CBD5E1",
            scrollbar_button_hover_color="#94A3B8",
        )
        self.frame_left.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.left_empty = ctk.CTkLabel(
            self.frame_left,
            text="将文件夹拖到这里\n\n也可以点击“选择文件夹”添加",
            text_color="#475569",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.left_empty.pack(expand=True, pady=70)
        return panel

    def build_right_panel(self, parent):
        panel = self.card(parent)
        head = self.panel_header(panel, "02", "压缩队列", "实时显示每个文件夹的压缩状态")
        self.secondary_button(head, "清除已完成", self.clear_completed_right, 104).pack(side="right")
        self.queue_count_var = ctk.StringVar(value="队列为空")
        ctk.CTkLabel(panel, textvariable=self.queue_count_var, text_color=MUTED, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=20, pady=(0, 10))

        self.frame_right = ctk.CTkScrollableFrame(
            panel,
            fg_color="#F1F5F9",
            corner_radius=10,
            scrollbar_button_color="#CBD5E1",
            scrollbar_button_hover_color="#94A3B8",
        )
        self.frame_right.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.right_empty = ctk.CTkLabel(self.frame_right, text="队列中还没有任务", text_color="#475569", font=ctk.CTkFont(size=14, weight="bold"))
        self.right_empty.pack(expand=True, pady=80)
        return panel

    def build_settings_card(self):
        outer = ctk.CTkFrame(self.root, fg_color="transparent")
        outer.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        outer.grid_columnconfigure(0, weight=1)
        self.settings_card = self.card(outer)
        self.settings_card.grid(row=0, column=0, sticky="ew")

        header = ctk.CTkFrame(self.settings_card, fg_color="transparent", cursor="hand2")
        header.pack(fill="x", padx=18, pady=13)
        header.bind("<Button-1>", lambda _event: self.toggle_settings())
        icon = ctk.CTkLabel(header, text="⚙", width=32, height=32, corner_radius=10, fg_color="#EDE9FE", text_color="#6D28D9", font=ctk.CTkFont(size=15))
        icon.pack(side="left")
        icon.bind("<Button-1>", lambda _event: self.toggle_settings())
        label_box = ctk.CTkFrame(header, fg_color="transparent")
        label_box.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(label_box, text="压缩配置", text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w")
        self.settings_summary = ctk.CTkLabel(label_box, text="路径、命名、加密与性能", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold"))
        self.settings_summary.pack(anchor="w")
        self.settings_toggle = ctk.CTkButton(
            header,
            text="展开 ⌄",
            command=self.toggle_settings,
            width=82,
            height=32,
            corner_radius=9,
            fg_color=SURFACE_3,
            hover_color="#DCE5F0",
            text_color="#334155",
        )
        self.settings_toggle.pack(side="right")

        self.settings_body = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        self.settings_body.pack(fill="x", padx=18, pady=(0, 16))
        self.settings_body.pack_forget()
        self.build_settings_fields(self.settings_body)

    def build_settings_fields(self, parent):
        for column in range(4):
            parent.grid_columnconfigure(column, weight=1)

        project = ctk.CTkFrame(parent, fg_color="#F1F5F9", corner_radius=10)
        project.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 14))
        project.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(project, text="7-Zip 路径", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, padx=(14, 8), pady=12)
        self.entry_7z = ctk.CTkEntry(
            project,
            height=38,
            corner_radius=9,
            fg_color=SURFACE_2,
            border_color=BORDER,
            text_color=TEXT,
            placeholder_text="选择 7z.exe 路径",
        )
        self.entry_7z.grid(row=0, column=1, sticky="ew", pady=12)
        self.entry_7z.insert(0, self.sevenz_path)
        self.secondary_button(project, "浏览", self.choose_7z, 72).grid(row=0, column=2, padx=8)

        ctk.CTkLabel(project, text="前缀", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=3, padx=(10, 6))
        self.entry_prefix = ctk.CTkEntry(project, width=130, height=38, corner_radius=9, fg_color=SURFACE_2, border_color=BORDER, text_color=TEXT)
        self.entry_prefix.grid(row=0, column=4)
        self.entry_prefix.insert(0, self.config.get("prefix", "HGLIST-"))
        self.entry_prefix.bind("<KeyRelease>", self.revalidate_left_list)

        ctk.CTkLabel(project, text="后缀", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=5, padx=(10, 6))
        self.entry_ext = ctk.CTkEntry(project, width=76, height=38, corner_radius=9, fg_color=SURFACE_2, border_color=BORDER, text_color=TEXT)
        self.entry_ext.grid(row=0, column=6)
        self.entry_ext.insert(0, self.config.get("extension", ".1"))
        self.secondary_button(project, "保存设置", self.save_config, 92).grid(row=0, column=7, padx=(10, 14))

        ctk.CTkLabel(project, text="标签前缀", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).grid(row=1, column=0, padx=(14, 8), pady=(0, 12))
        self.entry_tag_prefix = ctk.CTkEntry(
            project,
            width=130,
            height=38,
            corner_radius=9,
            fg_color=SURFACE_2,
            border_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(size=13, weight="bold"),
            placeholder_text="可留空",
        )
        self.entry_tag_prefix.grid(row=1, column=1, sticky="w", pady=(0, 12))
        self.entry_tag_prefix.insert(0, self.config.get("tag_prefix", "AAA_"))
        ctk.CTkLabel(
            project,
            text="例如：前缀 AAA_ + 标签 图片 → 创建目录 AAA_图片",
            text_color=MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=1, column=2, columnspan=6, sticky="w", padx=(8, 14), pady=(0, 12))

        advanced = ctk.CTkFrame(parent, fg_color="transparent")
        advanced.grid(row=1, column=0, columnspan=4, sticky="ew")
        for column in range(4):
            advanced.grid_columnconfigure(column, weight=1)
        parent = advanced

        password = self.setting_group(parent, "压缩密码", 0, 0)
        password.grid_columnconfigure(0, weight=1)
        self.entry_pwd = ctk.CTkEntry(password, height=38, corner_radius=9, fg_color=SURFACE_2, border_color=BORDER, show="●")
        self.entry_pwd.grid(row=1, column=0, sticky="ew")
        self.entry_pwd.insert(0, self.config.get("pwd", ""))
        self.show_pwd = False
        self.btn_toggle_pwd = ctk.CTkButton(password, text="显示", command=self.toggle_pwd_visibility, width=58, height=38, corner_radius=9, fg_color=SURFACE_3, hover_color="#DCE5F0", text_color="#334155")
        self.btn_toggle_pwd.grid(row=1, column=1, padx=(6, 0))

        encryption = self.setting_group(parent, "文件名", 0, 1)
        self.var_hide = ctk.BooleanVar(value=self.config.get("hide_name", True))
        ctk.CTkCheckBox(
            encryption,
            text="加密文件名",
            variable=self.var_hide,
            width=120,
            height=38,
            corner_radius=6,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            border_color="#94A3B8",
            command=self.update_settings_summary,
        ).grid(row=1, column=0, sticky="w")

        self.combo_lvl = self.combo(self.setting_group(parent, "压缩等级", 0, 2), ["0-仅存储", "1-极快", "3-快速", "5-标准", "7-最大", "9-极限"], self.config.get("lvl", "5-标准"), 150)
        self.combo_dict = self.combo(self.setting_group(parent, "字典大小", 0, 3), ["64 KB", "256 KB", "1 MB", "4 MB", "16 MB", "64 MB", "128 MB", "256 MB", "512 MB", "1024 MB", "2048 MB"], self.config.get("dict", "64 MB"), 150)
        self.combo_word = self.combo(self.setting_group(parent, "单词大小", 1, 0), ["8", "12", "16", "24", "32", "48", "64", "96", "128", "192", "256", "273"], self.config.get("word", "64"), 150)
        self.combo_solid = self.combo(self.setting_group(parent, "固实块", 1, 1), ["非固实", "64 MB", "256 MB", "1 GB", "4 GB", "16 GB", "64 GB", "固实"], self.config.get("solid", "16 GB"), 150)
        self.combo_threads = self.combo(self.setting_group(parent, "线程数", 1, 2), ["自动"] + [str(i) for i in range(1, self.max_cpu_threads + 1)], self.config.get("threads", "自动"), 150)
        self.update_settings_summary()

    @staticmethod
    def setting_group(parent, label, row, column):
        group = ctk.CTkFrame(parent, fg_color="transparent")
        group.grid(
            row=row,
            column=column,
            sticky="ew",
            padx=(0 if column == 0 else 12, 0),
            pady=(0, 0 if row == 1 else 14),
        )
        ctk.CTkLabel(group, text=label, text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        return group

    def combo(self, parent, values, selected, width):
        value = selected if selected in values else values[0]
        widget = ctk.CTkComboBox(
            parent,
            values=values,
            width=width,
            height=38,
            state="readonly",
            corner_radius=9,
            fg_color=SURFACE_2,
            border_color=BORDER,
            button_color=SURFACE_3,
            button_hover_color="#CBD5E1",
            dropdown_fg_color=SURFACE_2,
            dropdown_hover_color="#EDE9FE",
            text_color=TEXT,
            command=lambda _value: self.update_settings_summary(),
        )
        widget.grid(row=1, column=0, sticky="w")
        widget.set(value)
        # Prevent accidental changes while the closed selector has focus.
        for target in (widget, getattr(widget, "_entry", None), getattr(widget, "_canvas", None)):
            if target is not None:
                target.bind("<MouseWheel>", lambda _event: "break")
        return widget

    def toggle_settings(self):
        self.settings_expanded = not self.settings_expanded
        if self.settings_expanded:
            self.settings_body.pack(fill="x", padx=18, pady=(0, 16))
            self.settings_toggle.configure(text="收起 ︿")
        else:
            self.settings_body.pack_forget()
            self.settings_toggle.configure(text="展开 ⌄")

    def update_settings_summary(self):
        if not hasattr(self, "combo_lvl"):
            return
        level = self.combo_lvl.get().split("-", 1)[-1]
        encrypted = " · 文件名加密" if self.var_hide.get() else ""
        suffix = self.entry_ext.get().strip() or ".1"
        self.settings_summary.configure(text=f"{level}压缩 · {suffix} 后缀 · {self.combo_dict.get()} 字典 · {self.combo_threads.get()}线程{encrypted}")

    def build_action_dock(self):
        dock = ctk.CTkFrame(self.root, height=78, corner_radius=0, fg_color=SURFACE, border_width=1, border_color=BORDER)
        dock.grid(row=2, column=0, sticky="ew")
        dock.grid_propagate(False)
        dock.grid_columnconfigure(0, weight=1)

        progress = ctk.CTkFrame(dock, fg_color="transparent")
        progress.grid(row=0, column=0, sticky="ew", padx=(24, 22), pady=14)
        progress.grid_columnconfigure(0, weight=1)
        progress_title = ctk.CTkFrame(progress, fg_color="transparent")
        progress_title.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(progress_title, text="队列总进度", text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkLabel(progress_title, textvariable=self.status_var, text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(10, 0))
        self.total_label = ctk.CTkLabel(progress, text="0%", text_color=PRIMARY, font=ctk.CTkFont(size=13, weight="bold"))
        self.total_label.grid(row=0, column=1, sticky="e")
        self.total_progress = ctk.CTkProgressBar(progress, height=8, corner_radius=4, fg_color=SURFACE_3, progress_color=PRIMARY)
        self.total_progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self.total_progress.set(0)

        self.btn_pause = ctk.CTkButton(dock, text="暂停全部", command=self.toggle_pause, state="disabled", width=108, height=44, corner_radius=11, fg_color=SURFACE_3, hover_color="#DCE5F0", text_color="#475569")
        self.btn_pause.grid(row=0, column=1, padx=(0, 8))
        self.btn_cancel = ctk.CTkButton(dock, text="取消任务", command=self.cancel_all, state="disabled", width=108, height=44, corner_radius=11, fg_color="#FEE2E2", hover_color="#FECACA", text_color="#B91C1C")
        self.btn_cancel.grid(row=0, column=2, padx=(0, 10))
        self.btn_compress = ctk.CTkButton(dock, text="▶  开始压缩", command=self.do_compress, width=178, height=48, corner_radius=12, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color="white", font=ctk.CTkFont(size=15, weight="bold"))
        self.btn_compress.grid(row=0, column=3, padx=(0, 24))

    def choose_7z(self):
        path = filedialog.askopenfilename(title="选择 7z.exe", filetypes=[("7-Zip", "7z.exe 7zG.exe"), ("可执行文件", "*.exe")])
        if path:
            self.entry_7z.delete(0, "end")
            self.entry_7z.insert(0, path)

    def choose_folders(self):
        path = filedialog.askdirectory(title="选择一个文件夹（可继续添加）")
        if path:
            self.add_paths([path])

    def handle_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))

    def add_paths(self, paths):
        for path in sorted((item for item in paths if os.path.isdir(item)), key=lambda item: os.path.basename(item).lower()):
            path = os.path.normpath(path)
            if any(row["path"] == path for row in self.left_rows + self.right_rows):
                continue
            self.unwrap_nested_folders(path)
            self.add_left_row(path, os.path.basename(path))
        self.revalidate_left_list()

    @staticmethod
    def unwrap_nested_folders(folder_path):
        try:
            while True:
                items = [item for item in os.listdir(folder_path) if item not in {"desktop.ini", ".DS_Store", "Thumbs.db"}]
                if len(items) != 1 or not os.path.isdir(os.path.join(folder_path, items[0])):
                    break
                nested = os.path.join(folder_path, items[0])
                for item in os.listdir(nested):
                    shutil.move(os.path.join(nested, item), folder_path)
                os.rmdir(nested)
        except OSError:
            pass

    def add_left_row(self, path, name):
        if self.left_empty.winfo_exists():
            self.left_empty.pack_forget()
        row_frame = ctk.CTkFrame(self.frame_left, fg_color=SURFACE_2, corner_radius=10)
        row_frame.pack(fill="x", pady=(0, 8))
        row_frame.grid_columnconfigure(0, weight=1)
        name_label = ctk.CTkLabel(row_frame, text=name, text_color=TEXT, anchor="w", font=ctk.CTkFont(size=14, weight="bold"))
        name_label.grid(row=0, column=0, sticky="ew", padx=(13, 8), pady=12)
        tag_entry = ctk.CTkEntry(row_frame, width=150, height=34, corner_radius=8, fg_color=SURFACE_3, border_color=BORDER, placeholder_text="可选标签")
        tag_entry.grid(row=0, column=1, padx=6)
        data = {"frame": row_frame, "path": path, "original_name": name, "entry": tag_entry, "lbl_name": name_label, "expected_target_name": ""}
        data["btn_fix"] = ctk.CTkButton(row_frame, text="检查编号", command=lambda: self.do_fix_name(data), width=118, height=34, corner_radius=8, fg_color="#FEF3C7", hover_color="#FDE68A", text_color="#92400E")
        data["btn_fix"].grid(row=0, column=2, padx=5)
        ctk.CTkButton(row_frame, text="×", command=lambda: self.remove_left_row(row_frame), width=34, height=34, corner_radius=8, fg_color="transparent", hover_color="#FEE2E2", text_color=MUTED, font=ctk.CTkFont(size=17)).grid(row=0, column=3, padx=(2, 9))
        self.left_rows.append(data)

    def revalidate_left_list(self, *_):
        try:
            raw = self.counter_var.get()
            start = int(raw)
            padding = len(raw)
        except ValueError:
            return
        prefix = self.entry_prefix.get()
        for index, row in enumerate(self.left_rows):
            target = f"{prefix}{str(start + index).zfill(padding)}"
            correct = row["original_name"] == target
            row["expected_target_name"] = target
            row["lbl_name"].configure(text_color=TEXT if correct else DANGER)
            row["btn_fix"].configure(
                text="✓ 编号正确" if correct else f"改为 {target}",
                state="disabled" if correct else "normal",
                fg_color="#DCFCE7" if correct else "#FEF3C7",
                text_color=SUCCESS if correct else "#92400E",
            )

    def detect_min_number(self):
        matches = [(int(numbers[-1]), numbers[-1]) for row in self.left_rows if (numbers := re.findall(r"\d+", row["original_name"]))]
        if matches:
            self.counter_var.set(min(matches)[1])

    def do_fix_name(self, row):
        target = os.path.join(os.path.dirname(row["path"]), row["expected_target_name"])
        if os.path.exists(target):
            messagebox.showerror("名称冲突", f"目标文件夹已存在：\n{target}")
            return
        try:
            os.rename(row["path"], target)
            row["path"] = target
            row["original_name"] = os.path.basename(target)
            row["lbl_name"].configure(text=row["original_name"])
            self.revalidate_left_list()
        except OSError as error:
            messagebox.showerror("重命名失败", str(error))

    def remove_left_row(self, frame):
        frame.destroy()
        self.left_rows = [row for row in self.left_rows if row["frame"] != frame]
        self.revalidate_left_list()
        self.update_left_empty()

    def clear_left_list(self):
        for row in self.left_rows:
            row["frame"].destroy()
        self.left_rows.clear()
        self.update_left_empty()

    def update_left_empty(self):
        if not self.left_rows:
            self.left_empty.pack(expand=True, pady=70)

    def do_restructure(self):
        if not self.left_rows:
            return
        for row in list(self.left_rows):
            tag = row["entry"].get().strip()
            try:
                if tag:
                    safe_tag = re.sub(r'[\\/:*?"<>|]', "_", tag)
                    safe_prefix = re.sub(r'[\\/:*?"<>|]', "_", self.entry_tag_prefix.get().strip())
                    os.makedirs(os.path.join(row["path"], f"{safe_prefix}{safe_tag}"), exist_ok=True)
                self.add_right_row(row["path"], row["original_name"], tag)
                row["frame"].destroy()
                self.left_rows.remove(row)
            except OSError as error:
                messagebox.showerror("添加标签失败", f"{row['original_name']}：\n{error}")
                return
        self.update_left_empty()
        self.update_queue_count()

    def add_right_row(self, path, name, tag):
        if self.right_empty.winfo_exists():
            self.right_empty.pack_forget()
        row_frame = ctk.CTkFrame(self.frame_right, fg_color=SURFACE_2, corner_radius=10)
        row_frame.pack(fill="x", pady=(0, 8))
        row_frame.grid_columnconfigure(0, weight=1)
        title = name if not tag else f"{name}  ·  {tag}"
        ctk.CTkLabel(row_frame, text=title, text_color=TEXT, anchor="w", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="ew", padx=13, pady=(11, 4))
        status = ctk.CTkLabel(row_frame, text="等待压缩", text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold"))
        status.grid(row=0, column=1, padx=13, pady=(11, 4))
        progress = ctk.CTkProgressBar(row_frame, height=7, corner_radius=4, fg_color=SURFACE_3, progress_color=PRIMARY)
        progress.grid(row=1, column=0, columnspan=2, sticky="ew", padx=13, pady=(3, 12))
        progress.set(0)
        self.right_rows.append({"frame": row_frame, "path": path, "name": name, "status": "pending", "progress": progress, "status_label": status})

    def update_queue_count(self):
        pending = sum(row["status"] == "pending" for row in self.right_rows)
        self.queue_count_var.set(f"{len(self.right_rows)} 个任务 · {pending} 个待压缩" if self.right_rows else "队列为空")
        if not self.right_rows:
            self.right_empty.pack(expand=True, pady=80)

    def clear_completed_right(self):
        for row in list(self.right_rows):
            if row["status"] in {"done", "cancelled"}:
                row["frame"].destroy()
                self.right_rows.remove(row)
        self.update_queue_count()

    def toggle_pwd_visibility(self):
        self.show_pwd = not self.show_pwd
        self.entry_pwd.configure(show="" if self.show_pwd else "●")
        self.btn_toggle_pwd.configure(text="隐藏" if self.show_pwd else "显示")

    def do_compress(self):
        sevenz = self.entry_7z.get().strip()
        if not sevenz or not os.path.isfile(sevenz):
            messagebox.showerror("未找到 7-Zip", "请先选择有效的 7z.exe。控制台版 7z.exe 才能显示准确进度。")
            return
        if sevenz.lower().endswith("7zg.exe") and not messagebox.askyesno("进度受限", "7zG.exe 无法稳定读取进度，建议改用 7z.exe。仍要继续吗？"):
            return
        tasks = [row for row in self.right_rows if row["status"] in {"pending", "failed"}]
        if not tasks:
            messagebox.showinfo("队列为空", "请先把文件夹加入压缩队列。")
            return
        self.is_running = True
        self.is_paused = False
        self.cancel_requested = False
        self.btn_compress.configure(state="disabled", text="正在压缩…")
        self.btn_pause.configure(state="normal", text="暂停全部")
        self.btn_cancel.configure(state="normal")
        self.status_var.set("正在压缩队列")
        threading.Thread(target=self.compress_worker, args=(tasks, sevenz, self.build_options()), daemon=True).start()

    def build_options(self):
        ext = self.entry_ext.get().strip() or ".1"
        ext = ext if ext.startswith(".") else f".{ext}"

        def amount(value):
            return value.replace(" ", "").lower().replace("kb", "k").replace("mb", "m").replace("gb", "g")

        solid = self.combo_solid.get()
        return {
            "ext": ext,
            "pwd": self.entry_pwd.get(),
            "hide": bool(self.var_hide.get()),
            "level": self.combo_lvl.get().split("-")[0],
            "dict": amount(self.combo_dict.get()),
            "word": self.combo_word.get(),
            "solid": "off" if solid == "非固实" else "on" if solid == "固实" else amount(solid),
            "threads": "" if self.combo_threads.get() == "自动" else f"-mmt={self.combo_threads.get()}",
        }

    def toggle_pause(self):
        if not self.is_running:
            return
        self.is_paused = not self.is_paused
        process = self.current_process
        if process and process.poll() is None and os.name == "nt":
            try:
                function = ctypes.windll.ntdll.NtSuspendProcess if self.is_paused else ctypes.windll.ntdll.NtResumeProcess
                function(int(process._handle))
            except (AttributeError, OSError):
                pass
        self.btn_pause.configure(text="继续全部" if self.is_paused else "暂停全部")
        self.status_var.set("队列已暂停" if self.is_paused else "正在压缩队列")
        if self.current_row:
            self.current_row["status_label"].configure(text="已暂停" if self.is_paused else "压缩中", text_color=WARNING if self.is_paused else PRIMARY)

    def cancel_all(self):
        if self.is_running and messagebox.askyesno("取消队列", "将停止当前压缩，并取消剩余任务。确定继续吗？"):
            self.cancel_requested = True
            if self.current_process and self.current_process.poll() is None:
                self.current_process.terminate()
            self.status_var.set("正在取消…")

    def compress_worker(self, tasks, sevenz, options):
        for index, row in enumerate(tasks):
            if self.cancel_requested:
                break
            while self.is_paused and not self.cancel_requested:
                threading.Event().wait(0.15)
            if self.cancel_requested:
                break
            self.current_row = row
            self.ui_events.put(("status", row, "压缩中", PRIMARY, 0))
            archive = f"{row['path']}{options['ext']}"
            command = [sevenz, "a", archive, row["path"], "-t7z", "-bsp1", "-m0=lzma2", f"-mx={options['level']}", f"-md={options['dict']}", f"-mfb={options['word']}", f"-ms={options['solid']}"]
            if options["threads"]:
                command.append(options["threads"])
            if options["pwd"]:
                command.append(f"-p{options['pwd']}")
                if options["hide"]:
                    command.append("-mhe=on")
            try:
                self.current_process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=0,
                    startupinfo=self.hidden_startupinfo(),
                    creationflags=self.compression_creation_flags(),
                )
                progress_output = ""
                last_emitted_progress = -1
                last_progress_emit_at = 0.0

                def emit_progress(text):
                    nonlocal last_emitted_progress, last_progress_emit_at
                    matches = re.findall(r"(\d{1,3})%", text)
                    if not matches:
                        return
                    value = min(100, int(matches[-1]))
                    now = time.monotonic()
                    if value == last_emitted_progress:
                        return
                    # Ten UI updates per second is visually smooth and avoids
                    # flooding Tk's event loop with duplicate progress values.
                    if value not in {0, 100} and now - last_progress_emit_at < 0.1:
                        return
                    last_emitted_progress = value
                    last_progress_emit_at = now
                    self.ui_events.put(("progress", row, value, index, len(tasks)))

                while True:
                    char = self.current_process.stdout.read(1)
                    if not char:
                        break
                    if char in "\r\n":
                        emit_progress(progress_output)
                        progress_output = ""
                    else:
                        progress_output = (progress_output + char)[-256:]
                emit_progress(progress_output)
                result = self.current_process.wait()
                if self.cancel_requested:
                    row["status"] = "cancelled"
                    self.ui_events.put(("status", row, "已取消", MUTED, 0))
                elif result == 0:
                    row["status"] = "done"
                    self.ui_events.put(("status", row, "✓ 完成", SUCCESS, 100))
                else:
                    row["status"] = "failed"
                    self.ui_events.put(("status", row, "失败 · 可重试", DANGER, 0))
            except OSError as error:
                row["status"] = "failed"
                self.ui_events.put(("status", row, f"启动失败：{error}", DANGER, 0))
            finally:
                self.current_process = None

        if self.cancel_requested:
            for row in tasks:
                if row["status"] == "pending":
                    row["status"] = "cancelled"
                    self.ui_events.put(("status", row, "已取消", MUTED, 0))
        self.ui_events.put(("finished",))

    @staticmethod
    def hidden_startupinfo():
        if os.name != "nt":
            return None
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return info

    @staticmethod
    def compression_creation_flags():
        if os.name != "nt":
            return 0
        # Compression is background work. Keeping it below the UI process
        # priority prevents an all-core 7-Zip job from starving window redraws.
        return subprocess.BELOW_NORMAL_PRIORITY_CLASS

    def poll_ui_events(self):
        processed = 0
        deadline = time.perf_counter() + 0.008
        try:
            # Never drain an unbounded queue in one Tk callback. Returning to
            # mainloop regularly lets Windows repaint after task switching.
            while processed < 32 and time.perf_counter() < deadline:
                event = self.ui_events.get_nowait()
                processed += 1
                if event[0] == "progress":
                    _, row, value, index, total = event
                    row["progress"].set(value / 100)
                    row["status_label"].configure(text=f"压缩中 {value}%", text_color=PRIMARY)
                    overall = (index + value / 100) / total
                    self.total_progress.set(overall)
                    self.total_label.configure(text=f"{overall * 100:.0f}%")
                elif event[0] == "status":
                    _, row, text, color, value = event
                    row["status_label"].configure(text=text, text_color=color)
                    row["progress"].set(value / 100)
                elif event[0] == "finished":
                    self.finish_compression()
        except queue.Empty:
            pass
        self.root.after(20 if not self.ui_events.empty() else 50, self.poll_ui_events)

    def finish_compression(self):
        self.is_running = False
        self.is_paused = False
        self.current_row = None
        self.btn_compress.configure(state="normal", text="▶  开始压缩")
        self.btn_pause.configure(state="disabled", text="暂停全部")
        self.btn_cancel.configure(state="disabled")
        done = sum(row["status"] == "done" for row in self.right_rows)
        self.status_var.set("已取消" if self.cancel_requested else "队列已完成")
        self.update_queue_count()
        if not self.cancel_requested:
            messagebox.showinfo("任务结束", f"压缩完成：{done} 个任务。\n失败任务可再次点击“开始压缩”重试。")


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        os.environ["TKDND_LIBRARY"] = os.path.join(sys._MEIPASS, "tkinterdnd2", "tkdnd")
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    ctk.ThemeManager.theme["CTkFont"]["family"] = APP_FONT
    window = ModernDnDWindow()
    PipelineApp(window)
    window.mainloop()
