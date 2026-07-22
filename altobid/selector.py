"""区域框选与常驻监控框。

- 启动后静默监听全局快捷键（默认 Ctrl+F1）
- 热键触发后弹出全屏覆盖层框选区域
- 框选完成后仅保留细边框标记区域，覆盖层销毁
- 按住 Ctrl 后框线响应鼠标，可拖动或调整大小
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
    """区域框选 + 常驻框线 + 全局热键。

    用法::

        selector = RegionSelector(hotkey="<ctrl>+<f1>")
        selector.start(on_region_ready=callback)
        # 静默等待，用户按 Ctrl+F1 触发框选
        # 框选后回调 callback(bbox)，并显示可调整的框线
    """

    _OVERLAY_ALPHA = 0.3       # 框选时覆盖层透明度
    _KEY_COLOR = "#010101"     # 透明色键（近黑，极不可能与边框冲突）
    _RECT_COLOR = "#00ff88"
    _RECT_WIDTH = 2
    _HANDLE_SIZE = 8

    def __init__(self, hotkey: str = "<ctrl>+<f1>") -> None:
        self._hotkey = hotkey

        with mss.MSS() as sct:
            virtual = sct.monitors[0]
        self._origin_left = int(virtual["left"])
        self._origin_top = int(virtual["top"])
        self._vwidth = int(virtual["width"])
        self._vheight = int(virtual["height"])

        self._callback: Optional[Callable[[BBox], None]] = None
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._tk_root: Optional[tk.Tk] = None

        # 临时框选窗口（全屏覆盖层）
        self._overlay_root: Optional[tk.Tk] = None
        self._overlay_canvas: Optional[tk.Canvas] = None
        self._selecting = False
        self._start: Optional[tuple[int, int]] = None
        self._rect_id: Optional[int] = None

        # 常驻框线窗口（无背景，仅边框）
        self._frame_root: Optional[tk.Tk] = None
        self._frame_canvas: Optional[tk.Canvas] = None
        self._region: Optional[tuple[int, int, int, int]] = None  # 绝对屏幕坐标 (left, top, right, bottom)

        # Ctrl 拖动状态
        self._ctrl_pressed = False
        self._dragging = False
        self._drag_start: Optional[tuple[int, int]] = None
        self._resize_corner: Optional[str] = None

    def start(self, on_region_ready: Callable[[BBox], None]) -> None:
        """启动热键监听（阻塞主线程，等待 Tkinter 事件循环）。"""
        self._callback = on_region_ready
        self._start_hotkey_listener()
        self._start_keyboard_listener()  # 监听 Ctrl 按键
        log.info("静默启动，按 %s 触发框选", self._hotkey)

        # 创建隐藏的 root 维持 Tkinter 主循环；所有 Tk 操作都在此线程执行
        self._tk_root = tk.Tk()
        self._tk_root.withdraw()  # 不显示
        self._tk_root.mainloop()

    def _start_hotkey_listener(self) -> None:
        """启动全局热键监听（独立线程）。"""
        self._listener = keyboard.GlobalHotKeys({self._hotkey: self._trigger_select})
        self._listener.start()

    def _start_keyboard_listener(self) -> None:
        """监听 Ctrl 按键（独立线程）。回调经 after 调度回 Tk 主线程。"""
        def on_press(key):
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                self._marshal(lambda: self._on_ctrl(True))

        def on_release(key):
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                self._marshal(lambda: self._on_ctrl(False))

        self._keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._keyboard_listener.start()

    def _marshal(self, fn: Callable[[], None]) -> None:
        """把 Tk 操作调度到主循环线程执行（Tkinter 非线程安全）。"""
        if self._tk_root is not None:
            try:
                self._tk_root.after(0, fn)
            except RuntimeError:
                pass  # 主循环已退出

    def _trigger_select(self) -> None:
        """热键触发（来自监听线程）：调度到主线程弹出覆盖层。"""
        self._marshal(self._show_overlay)

    def _show_overlay(self) -> None:
        """显示全屏覆盖层（在 Tk 主线程执行）。"""
        if self._overlay_root is not None:
            return  # 已在框选中，忽略重复触发
        overlay = tk.Toplevel()
        overlay.overrideredirect(True)
        overlay.geometry(
            f"{self._vwidth}x{self._vheight}+{self._origin_left}+{self._origin_top}"
        )
        overlay.attributes("-alpha", self._OVERLAY_ALPHA)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black", cursor="crosshair")

        canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        canvas.bind("<ButtonPress-1>", lambda e: self._on_overlay_press(e, canvas))
        canvas.bind("<B1-Motion>", lambda e: self._on_overlay_drag(e, canvas))
        canvas.bind("<ButtonRelease-1>", lambda e: self._on_overlay_release(e, canvas, overlay))
        overlay.bind("<Escape>", lambda e: self._close_overlay())

        overlay.focus_force()

        self._overlay_root = overlay
        self._overlay_canvas = canvas
        self._selecting = True
        self._start = None
        self._rect_id = None

        log.info("框选模式：拖拽框出区域，Esc 取消")

    def _close_overlay(self) -> None:
        """销毁覆盖层并复位状态，保证后续可再次触发框选。"""
        if self._overlay_root is not None:
            try:
                self._overlay_root.destroy()
            except tk.TclError:
                pass
        self._overlay_root = None
        self._overlay_canvas = None
        self._selecting = False
        self._start = None
        self._rect_id = None

    def _on_overlay_press(self, event: "tk.Event", canvas: tk.Canvas) -> None:
        self._start = (event.x, event.y)
        if self._rect_id is not None:
            canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_overlay_drag(self, event: "tk.Event", canvas: tk.Canvas) -> None:
        if self._start is None:
            return
        x0, y0 = self._start
        if self._rect_id is None:
            self._rect_id = canvas.create_rectangle(
                x0, y0, event.x, event.y,
                outline=self._RECT_COLOR, width=self._RECT_WIDTH,
            )
        else:
            canvas.coords(self._rect_id, x0, y0, event.x, event.y)

    def _on_overlay_release(self, event: "tk.Event", canvas: tk.Canvas, overlay: tk.Toplevel) -> None:
        if self._start is None:
            self._close_overlay()
            return

        x0, y0 = self._start
        x1, y1 = event.x, event.y
        width = abs(x1 - x0)
        height = abs(y1 - y0)

        if width < 5 or height < 5:
            log.warning("框选区域过小，忽略")
            self._close_overlay()
            return

        # 转换为绝对屏幕坐标
        left = self._origin_left + min(x0, x1)
        top = self._origin_top + min(y0, y1)
        right = left + width
        bottom = top + height

        self._region = (left, top, right, bottom)
        self._close_overlay()

        log.info("框选完成: (%d,%d,%d,%d)", left, top, right, bottom)

        # 显示常驻框线
        self._show_frame()
        self._notify_region()

    def _show_frame(self) -> None:
        """显示/更新常驻框线：仅绿色边框，框内透明可见可穿透。"""
        if self._region is None:
            return
        self._ensure_frame_window()
        self._update_frame()

    def _ensure_frame_window(self) -> None:
        """惰性创建框线窗口（只建一次，之后复用，避免拖动时销毁重建闪烁）。"""
        if self._frame_root is not None:
            return

        frame = tk.Toplevel()
        frame.overrideredirect(True)
        frame.attributes("-topmost", True)
        frame.configure(bg=self._KEY_COLOR)
        # 用透明色键：与 _KEY_COLOR 相同的像素完全透明且可穿透，
        # 只有绿色边框/角柄是实心可见的，框内可看清验证码。
        try:
            frame.attributes("-transparentcolor", self._KEY_COLOR)
        except tk.TclError:
            log.warning("当前平台不支持 -transparentcolor，框内可能不透明")

        canvas = tk.Canvas(frame, bg=self._KEY_COLOR, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        canvas.bind("<ButtonPress-1>", self._on_frame_press)
        canvas.bind("<B1-Motion>", self._on_frame_drag)
        canvas.bind("<ButtonRelease-1>", self._on_frame_release)
        canvas.bind("<Motion>", self._on_frame_motion)

        self._frame_root = frame
        self._frame_canvas = canvas
        # 初始鼠标穿透（未按 Ctrl 时边框也不挡点击）
        self._set_transparent_to_mouse(frame, True)
        log.info("框线已显示，按住 Ctrl 可调整")

    def _update_frame(self) -> None:
        """按 self._region 更新框线窗口几何与画布内容（不重建窗口）。"""
        if self._frame_root is None or self._frame_canvas is None or self._region is None:
            return
        left, top, right, bottom = self._region
        width = max(1, right - left)
        height = max(1, bottom - top)

        self._frame_root.geometry(f"{width}x{height}+{left}+{top}")

        canvas = self._frame_canvas
        canvas.delete("all")
        canvas.create_rectangle(
            1, 1, width - 1, height - 1,
            outline=self._RECT_COLOR, width=self._RECT_WIDTH,
        )
        hs = self._HANDLE_SIZE
        for cx, cy in [(0, 0), (width, 0), (0, height), (width, height)]:
            canvas.create_rectangle(
                cx - hs // 2, cy - hs // 2, cx + hs // 2, cy + hs // 2,
                fill=self._RECT_COLOR, outline="",
            )

    def _set_transparent_to_mouse(self, window: tk.Tk, transparent: bool) -> None:
        """设置窗口鼠标穿透（Windows）。"""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            if transparent:
                style |= 0x80020  # WS_EX_LAYERED | WS_EX_TRANSPARENT
            else:
                style &= ~0x20    # 移除 WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
        except Exception as e:
            log.warning("设置鼠标穿透失败: %s", e)

    def _on_ctrl(self, pressed: bool) -> None:
        """Ctrl 状态变化。"""
        self._ctrl_pressed = pressed
        if self._frame_root is not None and not self._selecting:
            self._set_transparent_to_mouse(self._frame_root, not pressed)
            if self._frame_canvas:
                self._frame_canvas.config(cursor="arrow" if pressed else "arrow")

    def _on_frame_press(self, event: "tk.Event") -> None:
        if not self._ctrl_pressed or self._region is None:
            return

        left, top, right, bottom = self._region
        width = right - left
        height = bottom - top

        # 角柄命中用画布相对坐标（按下瞬间窗口未动，坐标准确）
        corner = self._hit_test_corner(event.x, event.y, 0, 0, width, height)
        # 拖动位移用屏幕绝对坐标 x_root/y_root，不受窗口随拖动移动的影响，避免抖动
        if corner:
            self._resize_corner = corner
            self._drag_start = (event.x_root, event.y_root)
        elif 0 <= event.x <= width and 0 <= event.y <= height:
            self._dragging = True
            self._drag_start = (event.x_root, event.y_root)

    def _on_frame_drag(self, event: "tk.Event") -> None:
        if not self._ctrl_pressed or self._drag_start is None or self._region is None:
            return

        # 用屏幕绝对坐标算增量，稳定不抖
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        left, top, right, bottom = self._region

        if self._resize_corner:
            # 调整大小
            if self._resize_corner == "tl":
                left += dx
                top += dy
            elif self._resize_corner == "tr":
                right += dx
                top += dy
            elif self._resize_corner == "bl":
                left += dx
                bottom += dy
            elif self._resize_corner == "br":
                right += dx
                bottom += dy
            self._region = (left, top, right, bottom)
        elif self._dragging:
            # 拖动整体
            width = right - left
            height = bottom - top
            self._region = (left + dx, top + dy, left + dx + width, top + dy + height)

        self._drag_start = (event.x_root, event.y_root)
        self._show_frame()

    def _on_frame_release(self, event: "tk.Event") -> None:
        if self._resize_corner or self._dragging:
            self._resize_corner = None
            self._dragging = False
            self._drag_start = None
            if self._region:
                self._notify_region()

    def _on_frame_motion(self, event: "tk.Event") -> None:
        if not self._ctrl_pressed or self._region is None or not self._frame_canvas:
            return

        left, top, right, bottom = self._region
        width = right - left
        height = bottom - top

        corner = self._hit_test_corner(event.x, event.y, 0, 0, width, height)
        if corner in ("tl", "br"):
            self._frame_canvas.config(cursor="size_nw_se")
        elif corner in ("tr", "bl"):
            self._frame_canvas.config(cursor="size_ne_sw")
        elif 0 <= event.x <= width and 0 <= event.y <= height:
            self._frame_canvas.config(cursor="fleur")
        else:
            self._frame_canvas.config(cursor="arrow")

    def _hit_test_corner(self, x: int, y: int, x0: int, y0: int, x1: int, y1: int) -> Optional[str]:
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

    def _notify_region(self) -> None:
        """通知回调当前区域。"""
        if not self._region or not self._callback:
            return
        left, top, right, bottom = self._region
        bbox = BBox(
            left=left,
            top=top,
            width=right - left,
            height=bottom - top,
        )
        log.info("区域更新: %s", bbox)
        threading.Thread(target=self._callback, args=(bbox,), daemon=True).start()
