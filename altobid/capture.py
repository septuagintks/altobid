"""区域截图。

用 mss 循环抓取指定 bbox，返回 numpy BGR 帧。

线程注意：mss 实例非线程安全。Capturer 采用**惰性创建**——首次 grab 时
在调用线程内建立 mss 实例，因此请在实际执行采集循环的那个线程里调用 grab。
"""
from __future__ import annotations

from types import TracebackType
from typing import Optional

import mss
import numpy as np

from . import get_logger
from .selector import BBox

log = get_logger("capture")


class Capturer:
    """按需抓取屏幕某矩形区域。

    用法::

        cap = Capturer(bbox)
        frame = cap.grab()      # (H, W, 3) uint8, BGR
        cap.close()

    或作为上下文管理器::

        with Capturer(bbox) as cap:
            frame = cap.grab()
    """

    def __init__(self, bbox: BBox) -> None:
        self._bbox = bbox
        self._sct: Optional["mss.base.MSSBase"] = None

    def _ensure(self) -> "mss.base.MSSBase":
        if self._sct is None:
            self._sct = mss.mss()
            log.debug("mss 实例已在当前线程创建, bbox=%s", self._bbox)
        return self._sct

    def grab(self) -> np.ndarray:
        """抓取一帧，返回 BGR 的 (H, W, 3) uint8 数组。"""
        sct = self._ensure()
        shot = sct.grab(self._bbox)  # BGRA
        frame = np.asarray(shot, dtype=np.uint8)  # (H, W, 4) BGRA
        return frame[:, :, :3]  # 丢弃 alpha -> BGR

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    def __enter__(self) -> "Capturer":
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()
