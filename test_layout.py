import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import ctypes

def set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIUnaware()
        except (AttributeError, OSError):
            print("警告：无法设置DPI感知。")

def get_dpi_scale_factor():
    try:
        # 获取主屏幕的设备上下文
        hdc = ctypes.windll.user32.GetDC(0)
        # 获取水平方向的DPI
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88) # 88 for LOGPIXELSX
        # 释放设备上下文
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0  # 96 DPI is the standard
    except Exception:
        return 1.0 # Fallback

class AppEntry(tk.Frame):
    def __init__(self, parent, scale_factor=1.0):
        super().__init__(parent, borderwidth=2, relief="groove")
        self.default_bg = self.cget("background")

        # --- Dynamic Sizes ---
        icon_size = int(48 * scale_factor)
        font_size_normal = int(9 * scale_factor)
        font_size_bold = int(10 * scale_factor)

        # --- Grid Layout ---
        self.grid_columnconfigure(1, weight=1)

        # --- Placeholder Icon ---
        placeholder_icon = Image.new("RGBA", (icon_size, icon_size), "blue")
        self.photo = ImageTk.PhotoImage(placeholder_icon)
        self.icon_label = tk.Label(self, image=self.photo, bg=self.default_bg)
        self.icon_label.grid(row=0, column=0, padx=int(10*scale_factor), pady=int(5*scale_factor), sticky="nsew")

        # --- Info Frame ---
        info_frame = tk.Frame(self, bg=self.default_bg)
        info_frame.grid(row=0, column=1, sticky="nsew", padx=int(10*scale_factor))
        info_frame.grid_columnconfigure(0, weight=1)

        self.name_label = tk.Label(info_frame, text="QQMusic", anchor="w", bg=self.default_bg, font=("Segoe UI", font_size_bold, "bold"))
        self.name_label.pack(fill="x", pady=(int(5*scale_factor),0))

        self.title_label = tk.Label(info_frame, text="红玫瑰", anchor="w", bg=self.default_bg, fg="gray", font=("Segoe UI", font_size_normal))
        self.title_label.pack(fill="x")

        # --- Status Label ---
        self.status_label = tk.Label(self, text="⏸️ 已暂停", width=10, anchor="center", bg=self.default_bg, fg="orange")
        self.status_label.grid(row=0, column=2, padx=5, sticky="nsew")

        # --- Select Button ---
        self.select_button = ttk.Button(self, text="锚定")
        self.select_button.grid(row=0, column=3, padx=10, sticky="nsew")


if __name__ == '__main__':
    set_dpi_awareness()
    scale = get_dpi_scale_factor()
    print(f"DPI Scale Factor: {scale}")

    root = tk.Tk()
    root.title("Layout Test")
    root.geometry(f"{int(500*scale)}x{int(100*scale)}")

    entry = AppEntry(root, scale_factor=scale)
    entry.pack(fill="x", pady=int(10*scale), padx=int(10*scale))

    root.mainloop()