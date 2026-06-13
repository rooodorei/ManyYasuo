import sys
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import shutil
import threading
import json
import re
import multiprocessing
from tkinterdnd2 import TkinterDnD, DND_FILES

CONFIG_FILE = "config.json"

class PipelineApp:
    def __init__(self, root):
        self.root = root
        self.root.title("流水线压缩工作站 (原生进度条 & 硬核性能版)")
        self.root.geometry("1240x780") # 稍微加高以容纳专业的性能面板
        self.root.resizable(False, False)

        self._is_updating = False

        config = self.load_config()
        self.sevenz_path = config.get("7z_path", self.find_default_7z())
        self.default_prefix = config.get("prefix", "HGLIST-")
        self.default_ext = config.get("extension", ".1") 
        
        self.is_running = False
        self.left_rows = []
        self.right_rows = []

        # 获取系统最大逻辑处理器(线程)数量
        self.max_cpu_threads = multiprocessing.cpu_count()

        self.setup_ui()
        self.revalidate_left_list()

    def find_default_7z(self):
        for p in [r"C:\Program Files\7-Zip\7zG.exe", 
                  r"C:\Program Files (x86)\7-Zip\7zG.exe",
                  r"C:\Program Files\7-Zip\7z.exe"]: 
            if os.path.exists(p): return p
        return ""

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {}

    def save_config(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "7z_path": self.entry_7z.get(),
                "prefix": self.entry_prefix.get(),
                "extension": self.entry_ext.get()
            }, f)
        messagebox.showinfo("成功", "设置已保存！")

    def setup_ui(self):
        # ================= 顶部：设置与计数器 =================
        top_frame = tk.Frame(self.root, pady=10, padx=10)
        top_frame.pack(fill=tk.X)

        tk.Label(top_frame, text="7z(G)路径:").pack(side=tk.LEFT)
        self.entry_7z = tk.Entry(top_frame, width=30)
        self.entry_7z.pack(side=tk.LEFT, padx=(5, 10))
        self.entry_7z.insert(0, self.sevenz_path)

        tk.Label(top_frame, text="默认前缀:").pack(side=tk.LEFT)
        self.entry_prefix = tk.Entry(top_frame, width=12)
        self.entry_prefix.pack(side=tk.LEFT, padx=5)
        self.entry_prefix.insert(0, self.default_prefix)
        self.entry_prefix.bind("<KeyRelease>", lambda e: self.revalidate_left_list())

        tk.Label(top_frame, text="后缀:").pack(side=tk.LEFT)
        self.entry_ext = tk.Entry(top_frame, width=6)
        self.entry_ext.pack(side=tk.LEFT, padx=5)
        self.entry_ext.insert(0, self.default_ext)

        tk.Button(top_frame, text="💾 保存配置", command=self.save_config).pack(side=tk.LEFT, padx=10)

        counter_frame = tk.Frame(top_frame, bg="#e3f2fd", padx=10, pady=5, bd=1, relief=tk.SOLID)
        counter_frame.pack(side=tk.RIGHT, padx=20)
        
        tk.Button(counter_frame, text="🔍 提取最小序号", command=self.detect_min_number, bg="#FFC107", relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(counter_frame, text="🏁 锚点序号:", bg="#e3f2fd", font=("", 10, "bold")).pack(side=tk.LEFT)
        
        self.counter_var = tk.StringVar(value="0001")
        self.counter_var.trace_add("write", self.revalidate_left_list)
        
        self.entry_counter = tk.Entry(counter_frame, textvariable=self.counter_var, width=8, font=("", 12, "bold"), justify="center")
        self.entry_counter.pack(side=tk.LEFT, padx=5)
        
        self.lbl_counter_status = tk.Label(counter_frame, text="就绪", bg="#e3f2fd", fg="gray", width=8)
        self.lbl_counter_status.pack(side=tk.LEFT)

        # ================= 中间：三栏流水线 =================
        main_frame = tk.Frame(self.root, padx=10, pady=5)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_panel = tk.LabelFrame(main_frame, text="第一步：拖入与自动脱壳 (已自动排序)", padx=5, pady=5)
        left_panel.place(relx=0, rely=0, relwidth=0.48, relheight=1)

        tk.Button(left_panel, text="🗑️ 清空拖入记录", command=self.clear_left_list, fg="blue", relief=tk.FLAT).pack(anchor=tk.E)

        self.canvas_left = tk.Canvas(left_panel, bg="white")
        scroll_left = ttk.Scrollbar(left_panel, orient="vertical", command=self.canvas_left.yview)
        self.frame_left = tk.Frame(self.canvas_left, bg="white")
        self.frame_left.bind("<Configure>", lambda e: self.canvas_left.configure(scrollregion=self.canvas_left.bbox("all")))
        self.canvas_left.create_window((0, 0), window=self.frame_left, anchor="nw")
        self.canvas_left.configure(yscrollcommand=scroll_left.set)
        self.canvas_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_left.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas_left.drop_target_register(DND_FILES)
        self.canvas_left.dnd_bind('<<Drop>>', self.handle_drop)
        self.frame_left.drop_target_register(DND_FILES)
        self.frame_left.dnd_bind('<<Drop>>', self.handle_drop)

        mid_panel = tk.Frame(main_frame)
        mid_panel.place(relx=0.49, rely=0, relwidth=0.12, relheight=1)
        
        tk.Label(mid_panel, text="第二步", font=("", 10, "bold"), fg="gray").pack(pady=(120, 5))
        self.btn_restructure = tk.Button(mid_panel, text="置入名字标签\n⏩ 移至右侧 ⏩", command=self.do_restructure, bg="#FFEB3B", height=3)
        self.btn_restructure.pack(fill=tk.X, padx=5)

        right_panel = tk.LabelFrame(main_frame, text="第三步：已标记队列", padx=5, pady=5)
        right_panel.place(relx=0.62, rely=0, relwidth=0.38, relheight=1)

        tk.Button(right_panel, text="🧹 清理已完成记录", command=self.clear_completed_right, fg="blue", relief=tk.FLAT).pack(anchor=tk.E)

        self.canvas_right = tk.Canvas(right_panel, bg="#f9f9f9")
        scroll_right = ttk.Scrollbar(right_panel, orient="vertical", command=self.canvas_right.yview)
        self.frame_right = tk.Frame(self.canvas_right, bg="#f9f9f9")
        self.frame_right.bind("<Configure>", lambda e: self.canvas_right.configure(scrollregion=self.canvas_right.bbox("all")))
        self.canvas_right.create_window((0, 0), window=self.frame_right, anchor="nw")
        self.canvas_right.configure(yscrollcommand=scroll_right.set)
        self.canvas_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_right.pack(side=tk.RIGHT, fill=tk.Y)

        # ================= 底部：安全设置与硬核性能配置 =================
        bottom_frame = tk.Frame(self.root, pady=10)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10)

        # --- 安全设置行 ---
        sec_frame = tk.Frame(bottom_frame)
        sec_frame.pack(pady=(0, 5), fill=tk.X)
        
        tk.Label(sec_frame, text="🔒 统一压缩密码:").pack(side=tk.LEFT)
        self.entry_pwd = tk.Entry(sec_frame, width=20, show="*")
        self.entry_pwd.pack(side=tk.LEFT, padx=(5, 0))

        self.btn_toggle_pwd = tk.Button(sec_frame, text="👁️", command=self.toggle_pwd_visibility, relief=tk.FLAT, cursor="hand2")
        self.btn_toggle_pwd.pack(side=tk.LEFT, padx=(0, 15))

        self.var_hide = tk.BooleanVar(value=True)
        tk.Checkbutton(sec_frame, text="加密文件名(需密码)", variable=self.var_hide).pack(side=tk.LEFT, padx=10)

        # --- 👑 7-Zip 硬核性能配置面板 ---
        perf_frame = tk.LabelFrame(bottom_frame, text="⚙️ 7-Zip 核心性能配置 (LZMA2算法)", padx=10, pady=8, fg="#1565C0", font=("", 9, "bold"))
        perf_frame.pack(fill=tk.X, pady=(0, 10))

        # 压缩等级
        tk.Label(perf_frame, text="压缩等级:").grid(row=0, column=0, padx=(0, 5), sticky="e")
        self.combo_lvl = ttk.Combobox(perf_frame, values=["0-仅存储", "1-极速", "3-快速", "5-标准", "7-最大", "9-极限"], state="readonly", width=10)
        self.combo_lvl.current(5) # 默认极限(9) 对应你截图
        self.combo_lvl.grid(row=0, column=1, padx=(0, 15))

        # 字典大小 (绝对控制内存)
        tk.Label(perf_frame, text="字典大小:").grid(row=0, column=2, padx=(0, 5), sticky="e")
        self.combo_dict = ttk.Combobox(perf_frame, values=["16 MB", "32 MB", "64 MB", "128 MB", "256 MB", "512 MB", "1024 MB"], state="readonly", width=10)
        self.combo_dict.current(4) # 默认 256MB 对应你截图
        self.combo_dict.grid(row=0, column=3, padx=(0, 15))

        # 单词大小
        tk.Label(perf_frame, text="单词大小:").grid(row=0, column=4, padx=(0, 5), sticky="e")
        self.combo_word = ttk.Combobox(perf_frame, values=["32", "64", "128", "273"], state="readonly", width=8)
        self.combo_word.current(1) # 默认 64 对应你截图
        self.combo_word.grid(row=0, column=5, padx=(0, 15))

        # 固实数据大小
        tk.Label(perf_frame, text="固实块大小:").grid(row=0, column=6, padx=(0, 5), sticky="e")
        self.combo_solid = ttk.Combobox(perf_frame, values=["不固实(Off)", "1 GB", "4 GB", "16 GB", "固实(Solid)"], state="readonly", width=12)
        self.combo_solid.current(3) # 默认 16 GB 对应你截图
        self.combo_solid.grid(row=0, column=7, padx=(0, 15))

        # 线程数 (智能获取本机最大线程)
        tk.Label(perf_frame, text="CPU 线程数:").grid(row=0, column=8, padx=(0, 5), sticky="e")
        thread_opts = [str(i) for i in range(1, self.max_cpu_threads + 1)]
        self.combo_threads = ttk.Combobox(perf_frame, values=thread_opts, state="readonly", width=5)
        # 默认选最大线程的一半（防卡死），你可以自由改
        default_thread = str(min(8, self.max_cpu_threads)) 
        if default_thread in thread_opts:
            self.combo_threads.set(default_thread)
        self.combo_threads.grid(row=0, column=9)

        # 最终按钮
        self.btn_compress = tk.Button(bottom_frame, text="🚀 开始加密压缩右侧队列 🚀", command=self.do_compress, bg="#4CAF50", fg="white", font=("", 13, "bold"), width=35, height=2)
        self.btn_compress.pack(pady=5)

    # ================= 核心业务逻辑 =================

    def detect_min_number(self):
        if not self.left_rows: return
        min_num = None
        min_str = None
        for row in self.left_rows:
            matches = re.findall(r'\d+', row['original_name'])
            if matches:
                num_str = matches[-1]
                num = int(num_str)
                if min_num is None or num < min_num:
                    min_num = num
                    min_str = num_str
        
        if min_str is not None:
            self.counter_var.set(min_str)

    def unwrap_nested_folders(self, folder_path):
        try:
            while True:
                items = [i for i in os.listdir(folder_path) if i not in ['desktop.ini', '.DS_Store', 'Thumbs.db']]
                if len(items) == 1:
                    inner_path = os.path.join(folder_path, items[0])
                    if os.path.isdir(inner_path):
                        for sub_item in os.listdir(inner_path):
                            shutil.move(os.path.join(inner_path, sub_item), folder_path)
                        os.rmdir(inner_path)
                        continue
                break
        except Exception:
            pass

    def toggle_pwd_visibility(self):
        if self.entry_pwd.cget('show') == '*':
            self.entry_pwd.config(show='')
            self.btn_toggle_pwd.config(text="🙈")
        else:
            self.entry_pwd.config(show='*')
            self.btn_toggle_pwd.config(text="👁️")

    def revalidate_left_list(self, *args):
        if self._is_updating: return
        self._is_updating = True

        try:
            start_str = self.counter_var.get()
            start_num = int(start_str)
            pad = len(start_str)
        except ValueError:
            self.lbl_counter_status.config(text="等待数字", fg="gray")
            self._is_updating = False
            return

        prefix = self.entry_prefix.get()

        for index, row in enumerate(self.left_rows):
            folder_name = row['original_name']
            expected_current_num = start_num + index
            expected_perfect_name = f"{prefix}{str(expected_current_num).zfill(pad)}"

            if folder_name == expected_perfect_name:
                row['lbl_name'].config(fg="black", text=folder_name)
                row['btn_fix'].config(state=tk.DISABLED, text="✔ 正确", bg="#eee", fg="gray")
            else:
                row['lbl_name'].config(fg="red", text=folder_name)
                row['btn_fix'].config(state=tk.NORMAL, text=f"🔧重命名为 {expected_perfect_name}", bg="#FF9800", fg="white")
                row['expected_target_name'] = expected_perfect_name

        self.lbl_counter_status.config(text="校验完成", fg="green")
        self._is_updating = False

    def do_fix_name(self, row):
        old_path = row['path']
        target_name = row['expected_target_name']
        parent_dir = os.path.dirname(old_path)
        new_path = os.path.join(parent_dir, target_name)

        if os.path.exists(new_path):
            messagebox.showerror("冲突", f"目标文件夹 {target_name} 已经存在！请检查硬盘。")
            return

        try:
            os.rename(old_path, new_path)
            row['path'] = new_path
            row['original_name'] = target_name
            self.revalidate_left_list()
        except Exception as e:
            messagebox.showerror("重命名失败", f"无法改名:\n{e}")

    def handle_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        valid_paths = [p for p in files if os.path.isdir(p)]
        
        valid_paths.sort(key=lambda x: os.path.basename(x))

        for path in valid_paths:
            self.unwrap_nested_folders(path)
            if any(row['path'] == path for row in self.left_rows): continue
            if any(row['path'] == path for row in self.right_rows): continue
            self.add_left_row(path, os.path.basename(path))
        
        self.revalidate_left_list()

    def add_left_row(self, path, folder_name):
        row_frame = tk.Frame(self.frame_left, bg="white", pady=5)
        row_frame.pack(fill=tk.X, padx=5)
        
        tk.Label(row_frame, text="📁", bg="white").pack(side=tk.LEFT)
        lbl_name = tk.Label(row_frame, text=folder_name, bg="white", width=20, anchor="w")
        lbl_name.pack(side=tk.LEFT)
        tk.Label(row_frame, text="➡", bg="white").pack(side=tk.LEFT)
        
        entry_new = tk.Entry(row_frame, width=15)
        entry_new.pack(side=tk.LEFT, padx=5)
        
        btn_rm = tk.Button(row_frame, text="❌", command=lambda r=row_frame: self.remove_left_row(r), relief=tk.FLAT, bg="white")
        btn_rm.pack(side=tk.RIGHT)

        btn_fix = tk.Button(row_frame, text="🔧", command=lambda: self.do_fix_name(row_data))
        btn_fix.pack(side=tk.RIGHT, padx=5)
        
        tk.Frame(self.frame_left, height=1, bg="#eee").pack(fill=tk.X)

        row_data = {
            'frame': row_frame,
            'path': path,
            'original_name': folder_name,
            'entry': entry_new,
            'lbl_name': lbl_name,
            'btn_fix': btn_fix,
            'expected_target_name': ''
        }
        self.left_rows.append(row_data)

    def remove_left_row(self, frame):
        frame.destroy()
        self.left_rows = [row for row in self.left_rows if row['frame'] != frame]
        self.revalidate_left_list()

    def clear_left_list(self):
        for row in self.left_rows:
            row['frame'].destroy()
        self.left_rows.clear()
        self.revalidate_left_list()

    def clear_completed_right(self):
        for row in list(self.right_rows):
            if row['status'] == 'done':
                row['frame'].destroy()
                self.right_rows.remove(row)

    def do_restructure(self):
        if not self.left_rows: return
        
        for row in list(self.left_rows):
            original_path = row['path']
            original_name = row['original_name']
            inner_name = row['entry'].get().strip()
            
            try:
                if inner_name:
                    safe_name = re.sub(r'[\\/:*?"<>|]', '_', inner_name)
                    marker_name = f"AAA_{safe_name}"
                    marker_path = os.path.join(original_path, marker_name)
                    
                    os.makedirs(marker_path, exist_ok=True)
                    display_text = f"{original_name}  [签: {marker_name}]"
                else:
                    display_text = f"{original_name} (无标签)"
                
                row['frame'].destroy()
                self.left_rows.remove(row)
                self.add_right_row(original_path, display_text)
                
            except Exception as e:
                messagebox.showerror("打标签失败", f"文件夹 {original_name} 创建标签失败:\n{e}")
                return

    def add_right_row(self, path, display_text):
        row_frame = tk.Frame(self.frame_right, bg="#f9f9f9", pady=5)
        row_frame.pack(fill=tk.X, padx=5)
        
        tk.Label(row_frame, text="📦", bg="#f9f9f9").pack(side=tk.LEFT)
        tk.Label(row_frame, text=display_text, bg="#f9f9f9", width=35, anchor="w").pack(side=tk.LEFT)
        
        lbl_status = tk.Label(row_frame, text="等待压缩", fg="gray", bg="#f9f9f9")
        lbl_status.pack(side=tk.RIGHT, padx=10)
        tk.Frame(self.frame_right, height=1, bg="#ddd").pack(fill=tk.X)

        self.right_rows.append({
            'frame': row_frame,
            'path': path,
            'status_label': lbl_status,
            'status': 'pending'
        })

    def do_compress(self):
        if self.is_running: return
        sevenz = self.entry_7z.get().strip()
        if not sevenz or not os.path.exists(sevenz):
            messagebox.showerror("错误", "7z(G).exe 路径不正确！请检查。")
            return
            
        tasks_to_run = [r for r in self.right_rows if r['status'] == 'pending']
        if not tasks_to_run: return

        self.is_running = True
        self.btn_compress.config(state=tk.DISABLED, text="压缩中...")
        self.entry_pwd.config(state=tk.DISABLED)
        self.btn_toggle_pwd.config(state=tk.DISABLED)

        # 👑 读取所有基础设置
        pwd = self.entry_pwd.get()
        hide = self.var_hide.get()
        ext = self.entry_ext.get().strip()
        if not ext: ext = ".1"
        if not ext.startswith('.'): ext = '.' + ext

        # 👑 映射硬核性能参数 (将中文选项翻译为 7-Zip 原生命令行参数)
        
        # 1. 压缩等级 (-mx)
        lvl = self.combo_lvl.get().split("-")[0] # 取前面的数字，例如 "9-极限" -> "9"
        
        # 2. 字典大小 (-md)
        dict_map = {"16 MB":"16m", "32 MB":"32m", "64 MB":"64m", "128 MB":"128m", "256 MB":"256m", "512 MB":"512m", "1024 MB":"1024m"}
        dict_val = dict_map.get(self.combo_dict.get(), "256m")
        
        # 3. 单词大小 (-mfb)
        word_val = self.combo_word.get()
        
        # 4. 固实块大小 (-ms)
        solid_map = {"不固实(Off)":"off", "1 GB":"1g", "4 GB":"4g", "16 GB":"16g", "固实(Solid)":"on"}
        solid_val = solid_map.get(self.combo_solid.get(), "16g")
        
        # 5. 线程数 (-mmt)
        threads_val = self.combo_threads.get()

        # 把这堆硬核参数打包丢给后台线程
        threading.Thread(target=self.compress_worker, args=(tasks_to_run, sevenz, pwd, hide, lvl, dict_val, word_val, solid_val, threads_val, ext), daemon=True).start()

    def compress_worker(self, tasks, sevenz, pwd, hide, lvl, dict_val, word_val, solid_val, threads_val, ext):
        is_gui_version = sevenz.lower().endswith('7zg.exe')
        
        try:
            for row in tasks:
                folder_path = row['path']
                archive_path = f"{folder_path}{ext}"
                
                self.root.after(0, lambda r=row: r['status_label'].config(text="压缩中...", fg="orange"))
                
                # 👑 终极核心命令行拼装：严格遵守 LZMA2 算法与自定义参数
                cmd = [
                    sevenz, 'a', archive_path, folder_path,
                    f'-t7z',              # 指定7z格式 (不受后缀名干扰)
                    f'-m0=lzma2',         # 指定算法为 LZMA2 (支持多线程效率最高)
                    f'-mx={lvl}',         # 压缩等级
                    f'-md={dict_val}',    # 字典大小 (绝对控制内存)
                    f'-mfb={word_val}',   # 单词大小
                    f'-ms={solid_val}',   # 固实数据
                    f'-mmt={threads_val}' # 线程控制 (防卡死核心)
                ]
                
                if pwd:
                    cmd.append(f'-p{pwd}')
                    if hide: cmd.append('-mhe=on')

                if is_gui_version:
                    proc = subprocess.run(cmd)
                else:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    proc = subprocess.run(cmd, startupinfo=startupinfo)
                
                if proc.returncode == 0:
                    row['status'] = 'done'
                    self.root.after(0, lambda r=row: r['status_label'].config(text="✅ 完成", fg="green"))
                else:
                    row['status'] = 'failed'
                    self.root.after(0, lambda r=row: r['status_label'].config(text="❌ 失败", fg="red"))

            self.root.after(0, lambda: messagebox.showinfo("任务结束", "已完成队列压缩！"))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("致命错误", str(e)))
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.btn_compress.config(state=tk.NORMAL, text="🚀 开始加密压缩右侧队列 🚀"))
            self.root.after(0, lambda: self.entry_pwd.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.btn_toggle_pwd.config(state=tk.NORMAL))

if __name__ == "__main__":
    if getattr(sys, 'frozen', False):
        tkdnd_path = os.path.join(sys._MEIPASS, 'tkinterdnd2', 'tkdnd')
        os.environ['TKDND_LIBRARY'] = tkdnd_path
    root = TkinterDnD.Tk()
    app = PipelineApp(root)
    root.mainloop()