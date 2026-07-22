"""输出处理：悬浮窗 + 控制台 + 日志。

支持三种输出方式：
1. Tkinter 悬浮窗（可选，配置中 output.show_window 控制）
2. 控制台打印（彩色）
3. 日志记录
"""
from __future__ import annotations

import sys
import tkinter as tk
from typing import TYPE_CHECKING

from . import get_logger

if TYPE_CHECKING:
    pass

log = get_logger("output")

# ANSI 颜色
GREEN = "\033[92m"
RESET = "\033[0m"


class OutputHandler:
    """处理推理结果输出：悬浮窗 + 控制台 + 日志。"""

    def __init__(self, show_window: bool = True, window_duration: int = 3000) -> None:
        self.show_window = show_window
        self.window_duration = window_duration

    def output(self, answer: str) -> None:
        """输出答案到各个通道。"""
        # 控制台（彩色）
        print(f"{GREEN}答案: {answer}{RESET}", flush=True)

        # 日志
        log.info("答案: %s", answer)

        # 悬浮窗（可选）
        if self.show_window:
            self._show_popup(answer)

    def _show_popup(self, text: str) -> None:
        """显示悬浮窗，自动关闭。"""
        root = tk.Tk()
        root.title("验证码答案")
        root.attributes("-topmost", True)  # 置顶

        # 窗口居中
        width, height = 300, 100
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")

        # 内容
        label = tk.Label(
            root,
            text=f"答案: {text}",
            font=("Arial", 24, "bold"),
            fg="#C4612F",  # 赤土色（与 design_sense 一致）
        )
        label.pack(expand=True)

        # 自动关闭
        root.after(self.window_duration, root.destroy)

        root.mainloop()
