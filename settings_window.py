import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

class WhitelistEntry(tk.Frame):
    """在白名单设置中显示单个应用的控件。"""
    
    # 中英文模式映射
    MODE_MAP = {
        "正常": "normal",
        "忽略": "ignore",
        "延时": "delay"
    }
    REVERSE_MODE_MAP = {v: k for k, v in MODE_MAP.items()}

    def __init__(self, parent, app_info, current_settings, on_update_callback):
        super().__init__(parent, bg="white", highlightbackground="#e0e0e0", highlightthickness=1)
        self.app_info = app_info
        self.on_update_callback = on_update_callback
        self.photo = None

        # --- UI 变量 ---
        # 从配置中获取英文mode，转换为中文显示
        initial_mode_english = current_settings.get('mode', 'normal')
        initial_mode_chinese = self.REVERSE_MODE_MAP.get(initial_mode_english, "正常")
        self.mode_var = tk.StringVar(value=initial_mode_chinese)
        self.delay_var = tk.IntVar(value=current_settings.get('delay_seconds', 2))

        self.grid_columnconfigure(1, weight=1)

        # --- 图标和标签 ---
        self.icon_label = tk.Label(self, bg="white")
        self.icon_label.grid(row=0, column=0, rowspan=2, padx=(10, 5), pady=5, sticky="nsew")
        self._update_icon(app_info.get('icon'))

        display_name = app_info.get('display_name', app_info.get('name', 'Unknown App'))
        self.name_label = tk.Label(self, text=display_name, anchor="w", bg="white", font=("Segoe UI", 10, "bold"))
        self.name_label.grid(row=0, column=1, sticky="ew", padx=5)

        process_name = app_info.get('process_name', app_info.get('name', 'N/A'))
        status_icon = "▶️ 播放中" if app_info.get('is_playing') else "⏹️ 静默"
        status_text = f"{process_name}  •  {status_icon}"
        self.status_label = tk.Label(self, text=status_text, anchor="w", bg="white", fg="gray", font=("Segoe UI", 8))
        self.status_label.grid(row=1, column=1, sticky="ew", padx=5)

        # --- 控制器 ---
        control_frame = ttk.Frame(self)
        control_frame.grid(row=0, column=2, rowspan=2, padx=10, pady=5)

        self.mode_combo = ttk.Combobox(control_frame, textvariable=self.mode_var, values=list(self.MODE_MAP.keys()), state="readonly", width=8)
        self.mode_combo.grid(row=0, column=0, padx=(0, 5))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_update)

        self.delay_label = ttk.Label(control_frame, text="延时(秒):", background="white")
        self.delay_spinbox = ttk.Spinbox(control_frame, from_=1, to=60, textvariable=self.delay_var, width=4, command=self._on_update)

        self._toggle_delay_widgets()

    def _update_icon(self, icon):
        if icon:
            try:
                img_copy = icon.copy()
                img_copy.thumbnail((32, 32), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(img_copy)
                self.icon_label.config(image=self.photo, text="")
            except Exception:
                self.icon_label.config(image='', text="🖼️")
        else:
            self.icon_label.config(image='', text="🎵")

    def _toggle_delay_widgets(self, event=None):
        """根据模式显示或隐藏延时设置。"""
        if self.mode_var.get() == "延时":
            self.delay_label.grid(row=0, column=1, padx=(5, 2))
            self.delay_spinbox.grid(row=0, column=2)
        else:
            self.delay_label.grid_remove()
            self.delay_spinbox.grid_remove()

    def _on_update(self, event=None):
        """当任何设置改变时调用回调函数。"""
        self._toggle_delay_widgets()
        if self.on_update_callback:
            # 将UI选择的中文模式转换为英文内部值
            selected_mode_chinese = self.mode_var.get()
            mode_english = self.MODE_MAP.get(selected_mode_chinese, 'normal')
            
            new_settings = {
                'mode': mode_english,
                'delay_seconds': self.delay_var.get()
            }
            # 使用 process_name 作为唯一标识符
            process_name = self.app_info.get('process_name', self.app_info.get('name'))
            if process_name:
                self.on_update_callback(process_name, new_settings)

    def destroy(self):
        """销毁控件时清理图像引用。"""
        if hasattr(self, 'icon_label') and self.icon_label.winfo_exists():
            self.icon_label.config(image='')
            self.icon_label.image = None
        self.photo = None
        self.on_update_callback = None
        super().destroy()

    def update_status(self, app_info):
        """仅更新此条目的播放状态，而不重新创建整个控件。"""
        if not self.winfo_exists():
            return
        
        self.app_info.update(app_info) # 更新内部信息
        
        process_name = self.app_info.get('process_name', 'N/A')
        status_icon = "▶️ 播放中" if self.app_info.get('is_playing') else "⏹️ 静默"
        status_text = f"{process_name}  •  {status_icon}"
        self.status_label.config(text=status_text)

class SettingsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("设置")
        self.transient(parent)
        self.grab_set()
        self.resizable(True, True) # 允许调整大小
        self.minsize(600, 500)

        self.was_saved = False
        self.saved_values = None
        self.parent = parent
        self.all_audio_apps = {}
        self.whitelist = {}
        self.whitelist_entries = {}

        # 创建UI变量
        self.always_on_top_var = tk.BooleanVar()
        self.debug_mode_var = tk.BooleanVar()
        self.log_retention_days_var = tk.IntVar()
        self.ignore_manual_pause_var = tk.BooleanVar()

        self.create_widgets()
        self.center_window()

    def create_widgets(self):
        main_frame = ttk.Frame(self, padding=(20, 20, 20, 10))
        main_frame.pack(expand=True, fill="both")
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # 创建标签页控件
        notebook = ttk.Notebook(main_frame)
        notebook.grid(row=0, column=0, sticky="nsew")

        # --- 创建标签页 ---
        general_tab = ttk.Frame(notebook, padding=15)
        whitelist_tab = ttk.Frame(notebook, padding=15)
        
        notebook.add(general_tab, text="常规")
        notebook.add(whitelist_tab, text="音频白名单")

        # --- 填充“常规”标签页 ---
        self._create_general_settings(general_tab)

        # --- 填充“音频白名单”标签页 ---
        self._create_whitelist_settings(whitelist_tab)

        # --- 按钮区域 ---
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", padx=20, pady=(0, 20))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        save_button = ttk.Button(button_frame, text="保存", command=self.save_and_close)
        save_button.grid(row=0, column=0, sticky="e", padx=5)

        cancel_button = ttk.Button(button_frame, text="取消", command=self.cancel_and_close)
        cancel_button.grid(row=0, column=1, sticky="w", padx=5)

    def _create_general_settings(self, parent):
        """创建通用和日志设置。"""
        # --- 通用设置 ---
        general_group = ttk.LabelFrame(parent, text="通用", padding="10")
        general_group.pack(fill="x", expand=True)

        always_on_top_check = ttk.Checkbutton(
            general_group, text="窗口置顶", variable=self.always_on_top_var
        )
        always_on_top_check.pack(anchor="w", pady=5)

        debug_mode_check = ttk.Checkbutton(
            general_group, text="调试模式", variable=self.debug_mode_var
        )
        debug_mode_check.pack(anchor="w", pady=5)

        ignore_manual_pause_check = ttk.Checkbutton(
            general_group, text="手动暂停后不自动恢复", variable=self.ignore_manual_pause_var
        )
        ignore_manual_pause_check.pack(anchor="w", pady=5)

        # --- 日志设置 ---
        logging_group = ttk.LabelFrame(parent, text="日志", padding="10")
        logging_group.pack(fill="x", expand=True, pady=(10, 0))

        retention_frame = ttk.Frame(logging_group)
        retention_frame.pack(fill="x", expand=True)
        
        retention_label = ttk.Label(retention_frame, text="日志保留天数:")
        retention_label.pack(side="left", padx=(0, 10))

        retention_spinbox = ttk.Spinbox(
            retention_frame, from_=1, to=365, textvariable=self.log_retention_days_var, width=5
        )
        retention_spinbox.pack(side="left")

    def _create_whitelist_settings(self, parent):
        """创建音频白名单设置。"""
        parent.rowconfigure(1, weight=1) # 为滚动区域设置权重
        parent.columnconfigure(0, weight=1)

        title_label = ttk.Label(parent, text="管理应用程序音频", font=("Segoe UI", 12, "bold"))
        title_label.grid(row=0, column=0, sticky="w", pady=(0, 10))

        list_frame = ttk.Frame(parent)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw"), width=e.width))
        
    def set_initial_values(self, debug, top, retention, whitelist, all_audio_apps, ignore_manual_pause):
        """从主程序接收当前的临时设置值。"""
        self.debug_mode_var.set(debug)
        self.always_on_top_var.set(top)
        self.log_retention_days_var.set(retention)
        self.ignore_manual_pause_var.set(ignore_manual_pause)
        
        self.whitelist = whitelist.copy()
        # 使用 process_name 作为字典的键，因为它更唯一
        self.all_audio_apps = {
            app['process_name']: app
            for app in all_audio_apps
            if app.get('process_name')
        }
        
        # 将白名单中但当前未运行的应用也加入到显示列表
        for process_name, settings in self.whitelist.items():
            if process_name not in self.all_audio_apps:
                self.all_audio_apps[process_name] = {
                    'process_name': process_name,
                    'display_name': process_name, # 回退到显示进程名
                    'is_playing': False,
                    'icon': None
                }

        self._update_whitelist_display()

    def _update_whitelist_display(self):
        """根据当前数据更新白名单UI。"""
        for entry in self.whitelist_entries.values():
            entry.destroy()
        self.whitelist_entries.clear()
        
        # 按显示名称排序，如果显示名称相同，则按进程名排序
        sorted_app_items = sorted(
            self.all_audio_apps.values(),
            key=lambda app: (app.get('display_name', '').lower(), app.get('process_name', '').lower())
        )
        
        for app_info in sorted_app_items:
            process_name = app_info.get('process_name')
            if not process_name:
                continue
            current_settings = self.whitelist.get(process_name, {})
            entry = WhitelistEntry(self.scrollable_frame, app_info, current_settings, self._on_update_whitelist)
            entry.pack(fill="x", pady=2, padx=2)
            self.whitelist_entries[process_name] = entry

    def _on_update_whitelist(self, process_name, new_settings):
        """处理白名单条目设置的更新。"""
        # 如果模式是“normal”，则从白名单中移除
        if new_settings['mode'] == 'normal':
            self.whitelist.pop(process_name, None)
        else:
            self.whitelist[process_name] = new_settings

    def update_app_statuses(self, all_audio_apps):
        """根据最新的音频应用信息更新白名单条目的状态。"""
        if not self.winfo_exists():
            return
            
        apps_by_process_name = {
            app['process_name']: app
            for app in all_audio_apps
            if app.get('process_name')
        }

        for process_name, entry in self.whitelist_entries.items():
            if process_name in apps_by_process_name:
                latest_info = apps_by_process_name[process_name]
                entry.update_status(latest_info)
            else:
                # 如果应用已不在播放列表中，则将其标记为静默
                entry.update_status({'is_playing': False})

    def get_values(self):
        """返回UI控件的当前值。"""
        # 清理掉值为 'normal' 的条目，因为这是默认行为
        cleaned_whitelist = {
            app: settings for app, settings in self.whitelist.items()
            if settings.get('mode') != 'normal'
        }
        return {
            'debug_mode': self.debug_mode_var.get(),
            'always_on_top': self.always_on_top_var.get(),
            'log_retention_days': self.log_retention_days_var.get(),
            'whitelist': cleaned_whitelist,
            'ignore_manual_pause': self.ignore_manual_pause_var.get()
        }

    def save_and_close(self):
        """获取当前值，标记为已保存，然后调用父窗口的关闭处理程序。"""
        self.was_saved = True
        self.saved_values = self.get_values()
        # 调用父窗口的关闭处理程序，而不是直接销毁
        if self.parent and hasattr(self.parent, '_on_settings_window_close'):
            self.parent._on_settings_window_close()

    def cancel_and_close(self):
        """不保存，直接调用父窗口的关闭处理程序。"""
        self.was_saved = False
        if self.parent and hasattr(self.parent, '_on_settings_window_close'):
            self.parent._on_settings_window_close()

    def destroy(self):
        """销毁窗口时，确保所有子控件也被正确销毁。"""
        for entry in self.whitelist_entries.values():
            entry.destroy()
        self.whitelist_entries.clear()
        super().destroy()

    def center_window(self):
        """将窗口居中于父窗口。"""
        self.update_idletasks()
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_w = self.parent.winfo_width()
        parent_h = self.parent.winfo_height()
        win_w = self.winfo_reqwidth()
        win_h = self.winfo_reqheight()
        x = parent_x + (parent_w - win_w) // 2
        y = parent_y + (parent_h - win_h) // 2
        self.geometry(f"+{x}+{y}")