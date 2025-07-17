import tkinter as tk
from tkinter import ttk
from tkinter import font as tkFont
import threading
from pystray import MenuItem as item
import pystray
from PIL import Image, ImageDraw, ImageTk
import ctypes
import gc
import queue

from worker import BackgroundWorker
from logger import logger
from config import config_manager
from settings_window import SettingsWindow
from properties_window import PropertiesWindow

def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIUnaware()
        except (AttributeError, OSError):
            logger.log_warning("无法设置DPI感知。")


# =====================================================================================
# UI Components
# =====================================================================================

class StatusBar(tk.Frame):
    """显示全局状态信息的状态栏。"""
    def __init__(self, parent):
        super().__init__(parent, bd=1, relief=tk.SOLID, bg="white")
        self.target_label = tk.Label(self, text="目标: 无", anchor='w', bg="white")
        self.target_label.pack(side="left", padx=10, pady=2)
        self.status_label = tk.Label(self, text="状态: 正在监控...", anchor='e', bg="white")
        self.status_label.pack(side="right", padx=10, pady=2)

    def update_status(self, target_name=None, is_monitoring=True):
        """更新状态栏的文本。"""
        if not self.winfo_exists(): return
        if target_name:
            self.target_label.config(text=f"目标: {target_name}")
        else:
            self.target_label.config(text="目标: 无")
        
        if is_monitoring:
            self.status_label.config(text="状态: 正在监控...")
        else:
            self.status_label.config(text="状态: 已暂停")

class AppEntry(tk.Frame):
    """
    一个自定义控件，用于在GUI中显示单个应用程序的信息。
    包含一个图标、应用名称、播放状态和一个选择按钮。
    """
    def __init__(self, parent, app_info, on_select_callback, on_control_callback):
        super().__init__(parent, bg="white", highlightbackground="#e0e0e0", highlightthickness=1)
        self.app_info = app_info
        self.on_select_callback = on_select_callback
        self.on_control_callback = on_control_callback
        self.default_bg = "white"
        self.photo = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.icon_label = tk.Label(self, bg=self.default_bg)
        self.icon_label.grid(row=0, column=0, rowspan=3, padx=(10, 5), pady=5, sticky="nsew")

        self.name_label = tk.Label(self, text="", anchor="w", bg=self.default_bg, font=("Segoe UI", 10, "bold"))
        self.name_label.grid(row=0, column=1, sticky="ew", padx=5)

        self.title_label = tk.Label(self, text="", anchor="w", bg=self.default_bg, fg="gray")
        self.title_label.grid(row=1, column=1, sticky="ew", padx=5)

        self.artist_label = tk.Label(self, text="", anchor="w", bg=self.default_bg, fg="darkgray")
        self.artist_label.grid(row=2, column=1, sticky="ew", padx=5)

        self.status_label = tk.Label(self, text="", width=10, anchor="center", bg=self.default_bg)
        self.status_label.grid(row=0, column=2, rowspan=3, pady=5, sticky="nsew")

        self.select_button = ttk.Button(self, text="锚定", command=self._on_select)
        self.select_button.grid(row=0, column=3, rowspan=3, padx=(5, 10), pady=5, sticky="nsew")
        
        self.update_info(app_info)

        self.bind_right_click()

    def bind_right_click(self):
        """为整个条目及其子控件绑定右键单击事件。"""
        self.bind("<Button-3>", self._on_right_click)
        for widget in self.winfo_children():
            # 不要覆盖按钮的左键单击事件
            if widget != self.select_button:
                widget.bind("<Button-3>", self._on_right_click)

    def _on_right_click(self, event):
        """创建并显示右键菜单。"""
        menu = tk.Menu(self, tearoff=0)
        
        # 播放/暂停 选项
        status = self.app_info.get('status', 'Unknown')
        if status in ['Playing', 'Paused']:
            toggle_label = "暂停" if status == 'Playing' else "播放"
            menu.add_command(label=toggle_label, command=lambda: self.on_control_callback('toggle_play_pause', self.app_info))
        
        menu.add_separator()
        menu.add_command(label="属性...", command=lambda: self.on_control_callback('show_properties', self.app_info))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def update_info(self, app_info):
        if not self.winfo_exists(): return
        self.app_info = app_info

        try:
            scaling_factor = self.winfo_toplevel().tk.call('tk', 'scaling')
        except (tk.TclError, AttributeError):
            scaling_factor = 1.0
        
        base_icon_size = 32
        icon_size = int(base_icon_size * scaling_factor)

        icon = app_info.get('icon')
        if icon:
            try:
                img_copy = icon.copy()
                img_copy.thumbnail((icon_size, icon_size), Image.Resampling.LANCZOS)

                final_image = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
                paste_x = (icon_size - img_copy.width) // 2
                paste_y = (icon_size - img_copy.height) // 2
                final_image.paste(img_copy, (paste_x, paste_y))

                self.photo = ImageTk.PhotoImage(final_image)
                self.icon_label.config(image=self.photo, text="")
            except Exception as e:
                logger.log_error(f"Error updating icon: {e}")
                self.icon_label.config(image='', text="🖼️")
        else:
            self.icon_label.config(image='', text="🎵")

        self.name_label.config(text=app_info['display_name'])
        self.title_label.config(text=app_info.get('title', 'N/A'))
        self.artist_label.config(text=app_info.get('artist', ''))

        status = app_info.get('status', 'Unknown')
        status_text = "▶️ 播放中" if status == 'Playing' else "⏸️ 已暂停"
        status_color = "green" if status == 'Playing' else "orange"
        self.status_label.config(text=status_text, fg=status_color)

    def _on_select(self):
        if self.on_select_callback:
            self.on_select_callback(self.app_info)

    def destroy(self):
        """自定义销毁方法，确保所有图像和回调引用都被清理，防止内存泄漏。"""
        if hasattr(self, 'icon_label'):
            self.icon_label.config(image='')
        self.photo = None
        
        self.on_select_callback = None
        self.on_control_callback = None

        self.app_info = None
        
        super().destroy()

    def __del__(self):
        print(f"[GC] An AppEntry has been garbage collected.")

    def set_as_target(self, is_target):
        if not self.winfo_exists(): return
        
        new_bg = "#e6f7ff" if is_target else self.default_bg
        
        self.config(bg=new_bg)
        for widget in self.winfo_children():
            if isinstance(widget, tk.Label):
                widget.config(bg=new_bg)

        if is_target:
            self.select_button.config(text="取消锚定", state="normal")
        else:
            self.select_button.config(text="锚定", state="normal")

class AppListWindow(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg="white")
        self.entries = {}
        self.target_app_source = None
        self.on_select_callback = None
        self.on_control_callback = None

        self.status_bar = StatusBar(self)
        self.status_bar.pack(side="top", fill="x")

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        style = ttk.Style(self)
        style.configure("White.TFrame", background="white")
        self.scrollable_frame = ttk.Frame(self.canvas, style="White.TFrame")

        self.canvas_frame_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def update_app_list(self, app_infos):
        logger.log_debug(f"[GUI] 更新应用列表，接收 {len(app_infos)} 个应用信息")
        current_sources = {app['source'] for app in app_infos}
        existing_sources = set(self.entries.keys())

        removed_count = 0
        for source in existing_sources - current_sources:
            logger.log_debug(f"[GUI] 移除应用: {self.entries[source].app_info['display_name']}")
            self.entries[source].destroy()
            del self.entries[source]
            removed_count += 1
            
        added_count = 0
        updated_count = 0
        for app_info in app_infos:
            source = app_info['source']
            if source not in existing_sources:
                logger.log_debug(f"[GUI] 添加新应用: {app_info['display_name']}")
                entry = AppEntry(self.scrollable_frame, app_info, self._on_app_select, self._on_app_control)
                entry.pack(fill="x", pady=2, padx=5)
                self.entries[source] = entry
                added_count += 1
            else:
                entry = self.entries[source]
                entry.update_info(app_info)
                updated_count += 1

        logger.log_debug(f"[GUI] 更新完成: 新增 {added_count} 个应用, 移除 {removed_count} 个应用, 更新 {updated_count} 个应用")
        self._update_target_highlight()

    def update_status(self, target_name=None, is_monitoring=True):
        self.status_bar.update_status(target_name, is_monitoring)

    def set_callbacks(self, select_callback, control_callback):
        self.on_select_callback = select_callback
        self.on_control_callback = control_callback

    def _on_app_control(self, command, app_info):
        """处理来自AppEntry右键菜单的控制命令。"""
        if self.on_control_callback:
            return self.on_control_callback(command, app_info)
        return None

    def _on_app_select(self, app_info):
        if self.target_app_source == app_info['source']:
            self.target_app_source = None
            logger.log_info(f"GUI: 用户取消了 {app_info['display_name']} 的目标状态。")
            if self.on_select_callback:
                self.on_select_callback(None)
        else:
            self.target_app_source = app_info['source']
            logger.log_info(f"GUI: 用户选择了 {app_info['display_name']} 作为目标。")
            if self.on_select_callback:
                self.on_select_callback(app_info)
        self._update_target_highlight()

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        canvas_width = event.width
        try:
            if self.scrollable_frame.winfo_exists() and self.scrollable_frame.winfo_width() != canvas_width:
                self.canvas.itemconfig(self.canvas_frame_id, width=canvas_width)
        except tk.TclError:
            pass

    def _update_target_highlight(self):
        for source, entry in self.entries.items():
            entry.set_as_target(source == self.target_app_source)

    def destroy(self):
        logger.log_debug("[GUI] 正在销毁AppListWindow及其所有子条目...")
        for entry in self.entries.values():
            entry.destroy()
        self.entries.clear()
        super().destroy()
        logger.log_debug("[GUI] AppListWindow销毁完成")

    def __del__(self):
        print("[GC] AppListWindow has been garbage collected.")


# =====================================================================================
# Main Application
# =====================================================================================

class AudioFocusApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Audio Focus Manager")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.tray_icon = None
        self.system_queue = queue.Queue()
        self.setup_tray_icon()

        self.debug_mode_var = tk.BooleanVar(value=config_manager.get('general.debug_mode', True))
        self.always_on_top_var = tk.BooleanVar(value=config_manager.get('general.always_on_top', False))
        
        self.setup_menu()
        
        self.toggle_debug_mode(is_initial_setup=True)
        self.toggle_always_on_top(is_initial_setup=True)

        self.app_list_window = AppListWindow(self)
        self.app_list_window.pack(fill="both", expand=True)
        self.app_list_window.set_callbacks(
            select_callback=self.on_target_app_selected,
            control_callback=self.on_app_control
        )

        self.target_app_info = None
        self.was_paused_by_app = False
        self.current_audio_apps = []
        self.latest_app_infos = {}
        self.properties_window = None
        
        self.ui_queue = queue.Queue()
        self.worker_queue = queue.Queue()
        self.worker = BackgroundWorker(self.ui_queue, self.worker_queue)
        self.worker_thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker_thread.start()

        self.process_ui_queue()
        self.process_system_queue()

        self.aspect_ratio = 900 / 400
        self.minsize(900, 400)
        self.geometry("900x400")

        self._resize_job = None
        self.bind('<Configure>', self._on_resize_debounced)
        self._last_applied_width = 900
        self._last_applied_height = 400

    def _on_resize_debounced(self, event):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(50, self._perform_resize)

    def _perform_resize(self):
        current_width = self.winfo_width()
        current_height = self.winfo_height()

        if current_width == self._last_applied_width and current_height == self._last_applied_height:
            return

        new_height = int(current_width / self.aspect_ratio)

        if new_height != current_height:
            self.geometry(f'{current_width}x{new_height}')
            self._last_applied_width = current_width
            self._last_applied_height = new_height
        else:
            self._last_applied_width = current_width
            self._last_applied_height = current_height

        self._resize_job = None

    def setup_menu(self):
        self.menubar = tk.Menu(self)

        program_menu = tk.Menu(self.menubar, tearoff=0)
        program_menu.add_command(label="退出", command=self.quit_app)
        self.menubar.add_cascade(label="程序", menu=program_menu)
        
        view_menu = tk.Menu(self.menubar, tearoff=0)
        view_menu.add_command(label="刷新", command=self.force_ui_refresh)
        view_menu.add_separator()
        view_menu.add_checkbutton(label="窗口置顶", onvalue=True, offvalue=False, variable=self.always_on_top_var, command=self.toggle_always_on_top)
        self.menubar.add_cascade(label="视图", menu=view_menu)

        options_menu = tk.Menu(self.menubar, tearoff=0)
        options_menu.add_checkbutton(label="调试模式", onvalue=True, offvalue=False, variable=self.debug_mode_var, command=self.toggle_debug_mode)
        options_menu.add_separator()
        options_menu.add_command(label="设置", command=self.show_settings_window)
        self.menubar.add_cascade(label="选项", menu=options_menu)

        help_menu = tk.Menu(self.menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self.show_about_window)
        self.menubar.add_cascade(label="帮助", menu=help_menu)

        self.config(menu=self.menubar)

    def _set_menu_state(self, state):
        try:
            if not self.menubar or not self.menubar.winfo_exists():
                return
            for i in range(self.menubar.index("end") + 1):
                self.menubar.entryconfig(i, state=state)
        except tk.TclError as e:
            logger.log_warning(f"无法设置菜单状态: {e}")

    def show_about_window(self):
        self._set_menu_state("disabled")
        about_win = tk.Toplevel(self)
        about_win.title("关于 Audio Focus Manager")

        about_win.resizable(False, False)
        about_win.transient(self)
        about_win.grab_set()

        main_frame = ttk.Frame(about_win, padding="20")
        main_frame.pack(expand=True, fill="both")

        app_name = ttk.Label(main_frame, text="Audio Focus Manager", font=("Segoe UI", 12, "bold"))
        app_name.pack(pady=(0, 5))

        version_label = ttk.Label(main_frame, text="版本: 1.0.0")
        version_label.pack()

        desc_label = ttk.Label(main_frame, text="一个自动管理音频焦点的工具。")
        desc_label.pack(pady=10)

        author_label = ttk.Label(main_frame, text="作者: Dongkid")
        author_label.pack()

        close_button = ttk.Button(main_frame, text="关闭", command=about_win.destroy)
        close_button.pack(pady=(20, 0))

        about_win.update_idletasks()
        win_w = about_win.winfo_reqwidth()
        win_h = about_win.winfo_reqheight()
        root_x = self.winfo_x()
        root_y = self.winfo_y()
        root_w = self.winfo_width()
        root_h = self.winfo_height()
        x = root_x + (root_w - win_w) // 2
        y = root_y + (root_h - win_h) // 2
        about_win.geometry(f'+{x}+{y}')
        
        self.wait_window(about_win)
        self._set_menu_state("normal")

    def _send_state_to_worker(self):
        state = {
            'target': self.target_app_info,
            'paused': self.was_paused_by_app
        }
        self.worker_queue.put({'type': 'state_update', 'data': state})

    def process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                message = self.ui_queue.get_nowait()
                msg_type = message.get('type')
                data = message.get('data')

                if msg_type in ['update_list', 'update_status']:
                    if not self.app_list_window or not self.app_list_window.winfo_exists():
                        logger.log_debug(f"UI不存在，忽略UI消息: {msg_type}")
                        continue

                if msg_type == 'update_list':
                    self.latest_app_infos = {app['source']: app for app in data}
                    self.app_list_window.update_app_list(data)
                    self._update_properties_window_if_open()
                elif msg_type == 'update_status':
                    self.app_list_window.update_status(**data)
                elif msg_type == 'set_paused_flag':
                    self.was_paused_by_app = data
                    self._send_state_to_worker()
                elif msg_type == 'target_closed':
                    self.target_app_info = None
                    self.was_paused_by_app = False
                    if self.app_list_window and self.app_list_window.winfo_exists():
                        self.app_list_window.update_status(target_name=None)
                    self._send_state_to_worker()
                elif msg_type == 'update_audio_apps':
                    self.current_audio_apps = data

        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_ui_queue)

    def process_system_queue(self):
        try:
            message = self.system_queue.get_nowait()
            if message == 'show':
                self.show_window()
            elif message == 'quit':
                self.quit_app()
        except queue.Empty:
            pass
        finally:
            self.after(200, self.process_system_queue)

    def force_ui_refresh(self):
        logger.log_info("[GUI] 用户点击了强制刷新")
        self.worker_queue.put({'type': 'force_refresh', 'data': None})

    def do_nothing(self):
        pass

    def show_settings_window(self):
        self._set_menu_state("disabled")
        settings_win = SettingsWindow(self)
        
        current_retention_days = config_manager.get('logging.log_retention_days')
        whitelist = config_manager.get('audio.whitelist', {})
        
        all_known_apps_cache = self.worker.get_all_known_apps()
        final_app_list_for_settings = list(all_known_apps_cache.values())

        settings_win.set_initial_values(
            debug=self.debug_mode_var.get(),
            top=self.always_on_top_var.get(),
            retention=current_retention_days,
            whitelist=whitelist,
            all_audio_apps=final_app_list_for_settings
        )
        
        self.wait_window(settings_win)

        if settings_win.was_saved:
            new_values = settings_win.get_values()
            
            self.debug_mode_var.set(new_values['debug_mode'])
            self.always_on_top_var.set(new_values['always_on_top'])
            
            self.toggle_debug_mode()
            self.toggle_always_on_top()
            
            config_manager.set('general.debug_mode', new_values['debug_mode'])
            config_manager.set('general.always_on_top', new_values['always_on_top'])
            config_manager.set('logging.log_retention_days', new_values['log_retention_days'])
            config_manager.set('audio.whitelist', new_values['whitelist'])
            config_manager.save_config()

            self.worker_queue.put({'type': 'config_updated', 'data': None})
            
            logger.log_info("设置已从设置窗口保存。")
        
        self._set_menu_state("normal")

    def toggle_debug_mode(self, is_initial_setup=False):
        is_enabled = self.debug_mode_var.get()
        logger.set_debug_mode(is_enabled)

    def toggle_always_on_top(self, is_initial_setup=False):
        is_on_top = self.always_on_top_var.get()
        self.attributes("-topmost", is_on_top)
        if not is_initial_setup:
            logger.log_info(f"[GUI] 窗口置顶状态切换为: {is_on_top}")

    def create_image(self, width, height, color1, color2):
        image = Image.new('RGB', (width, height), color1)
        dc = ImageDraw.Draw(image)
        dc.rectangle((width // 2, 0, width, height // 2), fill=color2)
        dc.rectangle((0, height // 2, width // 2, height), fill=color2)
        return image

    def setup_tray_icon(self):
        image = self.create_image(64, 64, 'black', 'white')
        menu = (
            item('显示', lambda: self.system_queue.put('show'), default=True),
            item('退出', lambda: self.system_queue.put('quit'))
        )
        self.tray_icon = pystray.Icon("AudioFocusManager", image, "Audio Focus Manager", menu)
        
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()

    def show_window(self):
        try:
            if not hasattr(self, 'app_list_window') or not self.app_list_window or not self.app_list_window.winfo_exists():
                logger.log_info("UI不存在或已被销毁，正在重新创建...")
                self.app_list_window = AppListWindow(self)
                self.app_list_window.pack(fill="both", expand=True)
                self.app_list_window.set_callbacks(
                    select_callback=self.on_target_app_selected,
                    control_callback=self.on_app_control
                )
                
                if self.target_app_info:
                    self.app_list_window.target_app_source = self.target_app_info.get('source')
                    self.app_list_window.update_status(target_name=self.target_app_info.get('display_name'))
                
                self.worker_queue.put({'type': 'force_refresh', 'data': None})
        except tk.TclError:
            logger.log_error("主窗口恢复失败。")
            return

        self.deiconify()
        self.lift()
        self.focus_force()

    def __del__(self):
        print("[GC] AudioFocusApp has been garbage collected.")

    def quit_app(self):
        logger.log_info("开始执行退出程序...")
        
        if self.worker:
            logger.log_info("正在向后台线程发送停止信号...")
            self.worker.stop()
        
        if hasattr(self, 'worker_thread') and self.worker_thread.is_alive():
            logger.log_info("正在等待后台线程终止...")
            self.worker_thread.join(timeout=2)
            if self.worker_thread.is_alive():
                logger.log_warning("后台线程在超时后仍在运行。")
            else:
                logger.log_info("后台线程已成功终止。")

        if self.tray_icon:
            logger.log_info("正在停止系统托盘图标...")
            self.tray_icon.stop()

        logger.log_info("正在销毁主窗口...")
        self.destroy()
        logger.log_info("退出程序完成。")

    def on_app_control(self, command, app_info):
        """处理来自AppEntry的右键菜单命令。"""
        logger.log_debug(f"收到应用控制命令: {command} for {app_info.get('display_name')}")
        
        if command == 'toggle_play_pause':
            self.worker_queue.put({
                'type': 'control_app',
                'data': {'source': app_info['source'], 'command': 'toggle'}
            })
        elif command == 'show_properties':
            if self.properties_window and self.properties_window.winfo_exists():
                self.properties_window.lift()
                return

            source = app_info.get('source')
            latest_info = self.latest_app_infos.get(source)
            if not latest_info:
                logger.log_warning(f"没有找到 {app_info.get('display_name')} 的最新详细信息。")
                latest_info = app_info

            self.properties_window = PropertiesWindow(self, latest_info)
            self.properties_window.protocol("WM_DELETE_WINDOW", self._on_properties_window_close)
            
        elif command == 'is_target':
            # 这个命令现在不再从右键菜单调用，但保留以防万一
            return self.target_app_info and self.target_app_info['source'] == app_info['source']
        
        return None

    def on_target_app_selected(self, app_info):
        if app_info:
            logger.log_info(f"主程序：已选择 {app_info['display_name']} 作为目标。")
            self.target_app_info = app_info
            self.was_paused_by_app = False
            self.app_list_window.update_status(target_name=self.target_app_info['display_name'])
        else:
            logger.log_info("主程序：已取消目标应用。")
            self.target_app_info = None
            self.was_paused_by_app = False
            self.app_list_window.update_status(target_name=None)
        
        self._send_state_to_worker()

    def _on_properties_window_close(self):
        if self.properties_window:
            self.properties_window.destroy()
        self.properties_window = None

    def _update_properties_window_if_open(self):
        if self.properties_window and self.properties_window.winfo_exists():
            source = self.properties_window.app_info.get('source')
            if source in self.latest_app_infos:
                latest_info = self.latest_app_infos[source]
                self.properties_window.update_info(latest_info)
            else:
                self._on_properties_window_close()

    def on_closing(self):
        logger.log_info("关闭窗口以释放资源，程序仍在后台运行。")
        if hasattr(self, 'app_list_window') and self.app_list_window and self.app_list_window.winfo_exists():
            self.app_list_window.destroy()
        self.app_list_window = None
        self.worker_queue.put({'type': 'ui_destroyed', 'data': None})
        self.withdraw()
        
        logger.log_info("正在执行垃圾回收...")
        gc.collect()
