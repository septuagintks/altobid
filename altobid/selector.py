"""区域框选。

全屏半透明覆盖层，让用户拖拽框出验证码所在矩形，返回可直接喂给 mss.grab 的 bbox。
支持多显示器：以 mss 的虚拟屏（monitors[0]）为坐标基准，处理负偏移。
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional, TypedDict

import mss

from . import get_logger

log = get_logger("selector")


class BBox(TypedDict):
    """mss.grab 兼容的边界框。"""

    left: int
    top: int
    width: int
    height: int


class RegionSelector:
    """全屏覆盖层框选器。

    用法::

        bbox = RegionSelector().select()
        # {'left': .., 'top': .., 'width': .., 'height': ..} 或 None（取消）
    """

    # 覆盖层透明度与拖拽矩形样式
    _ALPHA = 0.3
    _RECT_OUTLINE = "#00ff88"
    _RECT_WIDTH = 2

    def __init__(self) -> None:
        # 虚拟屏原点（可能为负），拖拽坐标需据此换算为绝对屏幕坐标
        with mss.MSS() as sct:
            virtual = sct.monitors[0]
        self._origin_left = int(virtual["left"])
        self._origin_top = int(virtual["top"])
        self._vwidth = int(virtual["width"])
        self._vheight = int(virtual["height"])

        self._start: Optional[tuple[int, int]] = None  # 画布内起点
        self._rect_id: Optional[int] = None
        self._result: Optional[BBox] = None

        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None

    # ---- 公开接口 ----------------------------------------------------------

    def select(self) -> Optional[BBox]:
        """阻塞弹出覆盖层，返回框选 bbox；用户按 Esc 或未拖拽则返回 None。"""
        self._build_window()
        assert self._root is not None
        self._root.mainloop()
        if self._result:
            log.info("已框选区域: %s", self._result)
        else:
            log.info("用户取消框选")
        return self._result

    # ---- 内部：窗口与事件 --------------------------------------------------

    def _build_window(self) -> None:
        root = tk.Tk()
        root.overrideredirect(True)  # 去标题栏
        root.geometry(
            f"{self._vwidth}x{self._vheight}+{self._origin_left}+{self._origin_top}"
        )
        root.attributes("-alpha", self._ALPHA)
        root.attributes("-topmost", True)
        root.configure(bg="black", cursor="crosshair")

        canvas = tk.Canvas(
            root, bg="black", highlightthickness=0, cursor="crosshair"
        )
        canvas.pack(fill="both", expand=True)

        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        root.bind("<Escape>", self._on_cancel)

        # 确保覆盖层拿到焦点，Esc 才可用（overrideredirect 下有时不自动聚焦）
        root.focus_force()

        self._root = root
        self._canvas = canvas

    def _on_press(self, event: "tk.Event") -> None:
        self._start = (event.x, event.y)
        if self._rect_id is not None and self._canvas is not None:
            self._canvas.delete(self._rect_id)
            self._rect_id = None

    def _on_drag(self, event: "tk.Event") -> None:
        if self._start is None or self._canvas is None:
            return
        x0, y0 = self._start
        if self._rect_id is None:
            self._rect_id = self._canvas.create_rectangle(
                x0, y0, event.x, event.y,
                outline=self._RECT_OUTLINE, width=self._RECT_WIDTH,
            )
        else:
            self._canvas.coords(self._rect_id, x0, y0, event.x, event.y)

    def _on_release(self, event: "tk.Event") -> None:
        if self._start is None:
            self._close()
            return
        x0, y0 = self._start
        x1, y1 = event.x, event.y

        left = min(x0, x1)
        top = min(y0, y1)
        width = abs(x1 - x0)
        height = abs(y1 - y0)

        # 过滤误点击（未拖拽或过小）
        if width < 5 or height < 5:
            log.warning("框选区域过小 (%dx%d)，忽略", width, height)
            self._result = None
        else:
            # 画布坐标 -> 绝对屏幕坐标
            self._result = BBox(
                left=self._origin_left + left,
                top=self._origin_top + top,
                width=width,
                height=height,
            )
        self._close()

    def _on_cancel(self, _event: "tk.Event") -> None:
        self._result = None
        self._close()

    def _close(self) -> None:
        if self._root is not None:
            self._root.destroy()
            self._root = None
