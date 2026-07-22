"""输出处理：控制台 + 日志 + 可选剪贴板 + 可选悬浮窗。"""
from __future__ import annotations

import tkinter as tk

from . import get_logger

log = get_logger("output")

# ANSI 颜色
GREEN = "\033[92m"
RESET = "\033[0m"


class OutputHandler:
    """处理推理结果输出：控制台 + 日志 + 剪贴板 + 悬浮窗。"""

    def __init__(
        self,
        show_window: bool = False,
        copy_to_clipboard: bool = True,
        window_duration_ms: int = 3000,
    ) -> None:
        self.show_window = show_window
        self.copy_to_clipboard = copy_to_clipboard
        self.window_duration_ms = window_duration_ms

    def output(self, answer: str) -> None:
        """输出答案到各通道。"""
        print(f"{GREEN}答案: {answer}{RESET}", flush=True)
        log.info("答案: %s", answer)

        if self.copy_to_clipboard:
            self._copy(answer)
        if self.show_window:
            self._show_popup(answer)

    def _copy(self, text: str) -> None:
        """复制到剪贴板（pyperclip 可选，缺失则用 tkinter 兜底）。"""
        try:
            import pyperclip

            pyperclip.copy(text)
            log.debug("已复制到剪贴板 (pyperclip)")
            return
        except ImportError:
            pass
        # tkinter 兜底
        try:
            r = tk.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()  # 保证写入生效
            r.destroy()
            log.debug("已复制到剪贴板 (tkinter)")
        except Exception as e:
            log.warning("复制剪贴板失败: %s", e)

    def _show_popup(self, text: str) -> None:
        """悬浮窗展示答案，到时自动关闭。"""
        root = tk.Tk()
        root.title("验证码答案")
        root.attributes("-topmost", True)

        width, height = 300, 100
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")

        tk.Label(
            root, text=f"答案: {text}", font=("Arial", 24, "bold"), fg="#C4612F"
        ).pack(expand=True)

        root.after(self.window_duration_ms, root.destroy)
        root.mainloop()
