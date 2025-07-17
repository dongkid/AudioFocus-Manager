import tkinter as tk
from tkinter import ttk

class PropertiesWindow(tk.Toplevel):
    def __init__(self, parent, app_info):
        super().__init__(parent)
        self.title(f"属性 - {app_info.get('display_name', 'N/A')}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Configure style for a white background and clearer fonts
        self.configure(bg='white')
        style = ttk.Style(self)
        try:
            # 'clam' or 'alt' themes are more customizable
            style.theme_use('clam')
        except tk.TclError:
            # Fallback to default if 'clam' is not available
            style.theme_use('default')

        style.configure('.', background='white', foreground='black', font=('Segoe UI', 10))
        style.configure('TFrame', background='white')
        style.configure('TLabel', background='white')
        style.configure('Bold.TLabel', font=('Segoe UI', 10, 'bold'))
        style.configure('TProgressbar', troughcolor='#EAEAEA', background='#0078D7')
        style.configure('TButton', font=('Segoe UI', 10), padding=5)
        style.map('TButton', background=[('active', '#E5F1FB')])


        self.app_info = app_info
        self.peak_value_var = tk.StringVar(value="N/A")
        self.loudness_percentage_var = tk.StringVar(value="0%")
        self.loudness_progress_var = tk.DoubleVar(value=0.0)

        main_frame = ttk.Frame(self, padding="15", style='TFrame')
        main_frame.pack(expand=True, fill="both")
        
        self.create_widgets(main_frame)
        self.update_info(app_info)

        # 自动调整窗口大小并居中
        self.update_idletasks()
        win_w = self.winfo_reqwidth()
        win_h = self.winfo_reqheight()
        root_x = parent.winfo_x()
        root_y = parent.winfo_y()
        root_w = parent.winfo_width()
        root_h = parent.winfo_height()
        x = root_x + (root_w - win_w) // 2
        y = root_y + (root_h - win_h) // 2
        self.geometry(f'+{x}+{y}')

    def create_widgets(self, parent):
        parent.columnconfigure(1, weight=1)
        
        fields = [
            ("显示名称:", "display_name"),
            ("进程名称:", "process_name"),
            ("进程ID (PID):", "pid"),
            ("媒体标题:", "title"),
            ("艺术家:", "artist"),
            ("播放状态:", "status"),
            ("音频峰值:", self.peak_value_var) # 使用StringVar
        ]
        
        self.info_labels = {}
        for i, (label_text, data_key) in enumerate(fields):
            label = ttk.Label(parent, text=label_text, style='Bold.TLabel')
            label.grid(row=i, column=0, sticky="w", pady=4, padx=5)
            
            if isinstance(data_key, tk.StringVar):
                value_label = ttk.Label(parent, textvariable=data_key, wraplength=300, style='TLabel')
            else:
                value_label = ttk.Label(parent, text="N/A", wraplength=300, style='TLabel')
            
            value_label.grid(row=i, column=1, sticky="w", pady=4, padx=5)
            if not isinstance(data_key, tk.StringVar):
                self.info_labels[data_key] = value_label

        # --- 音频响度百分比显示 ---
        current_row = len(fields)
        loudness_label = ttk.Label(parent, text="音频响度:", style='Bold.TLabel')
        loudness_label.grid(row=current_row, column=0, sticky="w", pady=4, padx=5)

        loudness_frame = ttk.Frame(parent, style='TFrame')
        loudness_frame.grid(row=current_row, column=1, sticky="we", pady=4, padx=5)
        loudness_frame.columnconfigure(0, weight=1)

        self.progressbar = ttk.Progressbar(
            loudness_frame,
            orient="horizontal",
            length=200,
            mode="determinate",
            variable=self.loudness_progress_var,
            style='TProgressbar'
        )
        self.progressbar.grid(row=0, column=0, sticky="we")

        self.percentage_label = ttk.Label(
            loudness_frame,
            textvariable=self.loudness_percentage_var,
            style='TLabel'
        )
        self.percentage_label.grid(row=0, column=1, sticky="w", padx=(5, 0))

        # --- 关闭按钮 ---
        close_button = ttk.Button(parent, text="关闭", command=self.destroy)
        close_button.grid(row=current_row + 1, column=0, columnspan=2, pady=(20, 0))

    def update_info(self, new_app_info):
        self.app_info = new_app_info
        self.title(f"属性 - {self.app_info.get('display_name', 'N/A')}")

        for key, label in self.info_labels.items():
            label.config(text=self.app_info.get(key, "N/A"))
        
        # 单独更新峰值
        self.update_peak_value(self.app_info.get('peak_value', 0))

    def update_peak_value(self, peak_value):
        """专门用于更新音频峰值和响度显示的方法。"""
        if not self.winfo_exists():
            return
        
        if peak_value is not None:
            # 更新原始峰值
            self.peak_value_var.set(f"{peak_value:.4f}")
            # 计算并更新响度百分比和进度条
            percentage = peak_value * 100
            self.loudness_progress_var.set(percentage)
            self.loudness_percentage_var.set(f"{percentage:.0f}%")
        else:
            self.peak_value_var.set("N/A")
            self.loudness_progress_var.set(0)
            self.loudness_percentage_var.set("N/A")
