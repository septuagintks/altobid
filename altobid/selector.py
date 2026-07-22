"""区域框选与常驻监控框。

- 启动后监听全局快捷键（默认 Ctrl+F1）触发框选
- 框选完成后保留半透明框，显示监控区域
- 按住 Ctrl 可取消鼠标穿透，拖动框体或调整大小
- 支持多显示器：以 mss 虚拟屏（monitors[0]）为坐标基准
"""
from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable, Optional, TypedDict

import mss
from pynput import keyboard

from . import get_logger

log = get_logger("selector")


class BBox(TypedDict):
    """mss.grab 兼容的边界框。"""

    left: int
    top: int
    width: int
    height: int


class RegionSelector:
    """常驻选区框 + 全局热键触发框选。

    用法::

        selector = RegionSelector(hotkey="<ctrl>+<f1>")
        selector.start(on_region_ready=callback)
        # callback 会在用户框选完成后被调用，传入 BBox
        # 框选后框体保留，按住 Ctrl 可拖动/调整
    """

    # 覆盖层透明度与框体样式
    _ALPHA = 0.15  # 常驻框透明度更低，减少干扰
    _RECT_OUTLINE = "#00ff88"
    _RECT_WIDTH = 2
    _HANDLE_SIZE = 8  # 角拖拽柄大小

    def __init__(self, hotkey: str = "<ctrl>+<f1>") -> None:
        """
        Args:
            hotkey: 全局热键（pynput 格式，如 "<ctrl>+<f1>"）
        """
        self._hotkey = hotkey

        # 虚拟屏原点（可能为负）
        with mss.MSS() as sct:
            virtual = sct.monitors[0]
        self._origin_left = int(virtual["left"])
        self._origin_top = int(virtual["top"])
        self._vwidth = int(virtual["width"])
        self._vheight = int(virtual["height"])

        self._callback: Optional[Callable[[BBox], None]] = None
        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None
        self._listener: Optional[keyboard.GlobalHotKeys] = None

        # 拖拽状态
        self._selecting = False  # 是否正在框选新区域
        self._start: Optional[tuple[int, int]] = None
        self._rect_id: Optional[int] = None
        self._handles: list[int] = []  # 四角拖拽柄 canvas id

        # 已确定的区域（画布坐标）
        self._region: Optional[tuple[int, int, int, int]] = None  # (x0, y0, x1, y1)

        # Ctrl 是否按下（用于取消鼠标穿透）
        self._ctrl_pressed = False
        self._dragging = False  # 是否正在拖动已有框
        self._drag_start: Optional[tuple[int, int]] = None
        self._resize_corner: Optional[str] = None  # 'tl'|'tr'|'bl'|'br'

    def start(self, on_region_ready: Callable[[BBox], None]) -> None:
        """启动常驻窗口 + 全局热键监听（阻塞主线程）。

        Args:
            on_region_ready: 框选完成回调，传入 BBox
        """
        self._callback = on_region_ready
        self._build_window()
        self._start_hotkey_listener()
        log.info("按 %s 触发框选，按 Ctrl 可调整已有框", self._hotkey)
        assert self._root is not None
        self._root.mainloop()

    def _build_window(self) -> None:
        """构建常驻覆盖层。"""
        root = tk.Tk()
        root.overrideredirect(True)
        root.geometry(
            f"{self._vwidth}x{self._vheight}+{self._origin_left}+{self._origin_top}"
        )
        root.attributes("-alpha", self._ALPHA)
        root.attributes("-topmost", True)
        root.configure(bg="black")

        canvas = tk.Canvas(root, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        # 初始鼠标穿透（Windows）
        self._set_transparent_to_mouse(root, True)

        # 绑定键盘事件（检测 Ctrl）
        root.bind("<KeyPress-Control_L>", lambda e: self._on_ctrl(True))
        root.bind("<KeyPress-Control_R>", lambda e: self._on_ctrl(True))
        root.bind("<KeyRelease-Control_L>", lambda e: self._on_ctrl(False))
        root.bind("<KeyRelease-Control_R>", lambda e: self._on_ctrl(False))

        # 鼠标事件
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_motion)

        root.bind("<Escape>", lambda e: self._cancel_selection())

        self._root = root
        self._canvas = canvas

    def _set_transparent_to_mouse(self, window: tk.Tk, transparent: bool) -> None:
        """设置窗口鼠标穿透（仅 Windows）。"""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            if transparent:
                # 添加 WS_EX_TRANSPARENT (0x20) 和 WS_EX_LAYERED (0x80000)
                style |= 0x80020
            else:
                # 移除 WS_EX_TRANSPARENT
                style &= ~0x20
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
        except Exception as e:
            log.warning("设置鼠标穿透失败（可能非 Windows）: %s", e)

    def _start_hotkey_listener(self) -> None:
        """启动全局热键监听（独立线程）。"""
        self._listener = keyboard.GlobalHotKeys({self._hotkey: self._trigger_select})
        self._listener.start()

    def _trigger_select(self) -> None:
        """热键触发：开始框选新区域。"""
        if self._root is not None:
            self._root.after(0, self._enter_select_mode)

    def _enter_select_mode(self) -> None:
        """进入框选模式：清空旧框，切换光标。"""
        log.info("进入框选模式，拖拽鼠标框出区域")
        self._selecting = True
        self._region = None
        if self._canvas:
            self._canvas.delete("all")
            self._canvas.config(cursor="crosshair")
            self._rect_id = None
            self._handles.clear()
        if self._root:
            self._set_transparent_to_mouse(self._root, False)

    def _cancel_selection(self) -> None:
        """取消框选，恢复到无框状态。"""
        if self._selecting:
            log.info("取消框选")
            self._selecting = False
            self._start = None
            if self._canvas:
                self._canvas.delete("all")
                self._canvas.config(cursor="arrow")
            if self._root:
                self._set_transparent_to_mouse(self._root, True)

    def _on_ctrl(self, pressed: bool) -> None:
        """Ctrl 按下/释放：切换鼠标穿透。"""
        self._ctrl_pressed = pressed
        if self._root and not self._selecting:
            self._set_transparent_to_mouse(self._root, not pressed)
            if self._canvas:
                self._canvas.config(cursor="arrow" if pressed else "arrow")

    def _on_press(self, event: "tk.Event") -> None:
        """鼠标按下：开始框选或拖动。"""
        if self._selecting:
            # 框选新区域
            self._start = (event.x, event.y)
            if self._rect_id is not None and self._canvas:
                self._canvas.delete("all")
                self._rect_id = None
                self._handles.clear()
        elif self._ctrl_pressed and self._region:
            # 拖动或调整已有框
            x0, y0, x1, y1 = self._region
            # 检查是否点击角柄
            corner = self._hit_test_corner(event.x, event.y, x0, y0, x1, y1)
            if corner:
                self._resize_corner = corner
                self._drag_start = (event.x, event.y)
                log.debug("开始调整大小：%s", corner)
            elif x0 <= event.x <= x1 and y0 <= event.y <= y1:
                # 点在框内，拖动整体
                self._dragging = True
                self._drag_start = (event.x, event.y)
                log.debug("开始拖动框体")

    def _on_drag(self, event: "tk.Event") -> None:
        """鼠标拖动：更新框选或拖动框体。"""
        if self._selecting and self._start:
            # 框选新区域
            x0, y0 = self._start
            if self._canvas:
                if self._rect_id is None:
                    self._rect_id = self._canvas.create_rectangle(
                        x0, y0, event.x, event.y,
                        outline=self._RECT_OUTLINE, width=self._RECT_WIDTH,
                    )
                else:
                    self._canvas.coords(self._rect_id, x0, y0, event.x, event.y)
        elif self._resize_corner and self._drag_start and self._region:
            # 调整大小
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            x0, y0, x1, y1 = self._region
            if self._resize_corner == "tl":
                x0 += dx
                y0 += dy
            elif self._resize_corner == "tr":
                x1 += dx
                y0 += dy
            elif self._resize_corner == "bl":
                x0 += dx
                y1 += dy
            elif self._resize_corner == "br":
                x1 += dx
                y1 += dy
            self._region = (x0, y0, x1, y1)
            self._drag_start = (event.x, event.y)
            self._redraw_region()
        elif self._dragging and self._drag_start and self._region:
            # 拖动框体
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            x0, y0, x1, y1 = self._region
            self._region = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            self._drag_start = (event.x, event.y)
            self._redraw_region()

    def _on_release(self, event: "tk.Event") -> None:
        """鼠标释放：完成框选或拖动。"""
        if self._selecting and self._start:
            x0, y0 = self._start
            x1, y1 = event.x, event.y
            width = abs(x1 - x0)
            height = abs(y1 - y0)
            if width < 5 or height < 5:
                log.warning("框选区域过小，忽略")
                self._cancel_selection()
                return
            # 保存区域（画布坐标，标准化为左上右下）
            self._region = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            self._selecting = False
            self._start = None
            self._redraw_region()
            self._notify_region()
            log.info("框选完成，按住 Ctrl 可调整")
            if self._root:
                self._set_transparent_to_mouse(self._root, True)
        elif self._resize_corner or self._dragging:
            # 完成拖动/调整
            self._resize_corner = None
            self._dragging = False
            self._drag_start = None
            if self._region:
                self._notify_region()

    def _on_motion(self, event: "tk.Event") -> None:
        """鼠标移动：更新光标。"""
        if not self._ctrl_pressed or self._selecting or not self._region or not self._canvas:
            return
        x0, y0, x1, y1 = self._region
        corner = self._hit_test_corner(event.x, event.y, x0, y0, x1, y1)
        if corner in ("tl", "br"):
            self._canvas.config(cursor="size_nw_se")
        elif corner in ("tr", "bl"):
            self._canvas.config(cursor="size_ne_sw")
        elif x0 <= event.x <= x1 and y0 <= event.y <= y1:
            self._canvas.config(cursor="fleur")
        else:
            self._canvas.config(cursor="arrow")

    def _hit_test_corner(self, x: int, y: int, x0: int, y0: int, x1: int, y1: int) -> Optional[str]:
        """检测是否点击角柄，返回 'tl'|'tr'|'bl'|'br' 或 None。"""
        hs = self._HANDLE_SIZE
        if abs(x - x0) <= hs and abs(y - y0) <= hs:
            return "tl"
        if abs(x - x1) <= hs and abs(y - y0) <= hs:
            return "tr"
        if abs(x - x0) <= hs and abs(y - y1) <= hs:
            return "bl"
        if abs(x - x1) <= hs and abs(y - y1) <= hs:
            return "br"
        return None

    def _redraw_region(self) -> None:
        """重绘已确定的框 + 四角拖拽柄。"""
        if not self._canvas or not self._region:
            return
        x0, y0, x1, y1 = self._region
        self._canvas.delete("all")
        self._rect_id = self._canvas.create_rectangle(
            x0, y0, x1, y1,
            outline=self._RECT_OUTLINE, width=self._RECT_WIDTH,
        )
        # 四角拖拽柄
        hs = self._HANDLE_SIZE
        for cx, cy in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]:
            self._canvas.create_rectangle(
                cx - hs // 2, cy - hs // 2, cx + hs // 2, cy + hs // 2,
                fill=self._RECT_OUTLINE, outline="",
            )

    def _notify_region(self) -> None:
        """通知回调当前区域（转换为绝对屏幕坐标）。"""
        if not self._region or not self._callback:
            return
        x0, y0, x1, y1 = self._region
        bbox = BBox(
            left=self._origin_left + x0,
            top=self._origin_top + y0,
            width=x1 - x0,
            height=y1 - y0,
        )
        log.info("区域更新: %s", bbox)
        threading.Thread(target=self._callback, args=(bbox,), daemon=True).start()
