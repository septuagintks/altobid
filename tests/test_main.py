"""主流程线程管理测试（聚焦采集线程停止与区域重启）。"""
import queue
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# 与 test_selector 同样的条件 mock（无依赖环境回退）
for _mod in ("mss", "pynput", "pynput.keyboard"):
    try:
        __import__(_mod)
    except ImportError:
        sys.modules[_mod] = MagicMock()

from altobid import main as main_mod
from altobid.change_detect import ChangeDetector, Debouncer


class _FakeCapturer:
    """假 Capturer：grab 返回固定灰帧，支持上下文管理器。"""

    def __init__(self, bbox):
        self.bbox = bbox

    def grab(self):
        return np.full((40, 60, 3), 128, np.uint8)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_capture_loop_stops_on_stop_event():
    """置位 stop 事件后，采集循环应及时退出（修复多线程堆积/阻塞）。"""
    detector = ChangeDetector()
    debouncer = Debouncer()
    q: queue.Queue = queue.Queue(maxsize=1)
    stop = threading.Event()

    with patch.object(main_mod, "Capturer", _FakeCapturer):
        t = threading.Thread(
            target=main_mod.capture_loop,
            args=(
                {"left": 0, "top": 0, "width": 60, "height": 40},
                detector, debouncer, q, 0.01, stop,
            ),
            daemon=True,
        )
        t.start()
        time.sleep(0.1)  # 让它跑几圈
        stop.set()
        t.join(timeout=2.0)
        assert not t.is_alive(), "stop 置位后采集线程应退出"


def test_capture_loop_stops_on_global_stop():
    """全局 _stop_event 也应能停止采集循环。"""
    detector = ChangeDetector()
    debouncer = Debouncer()
    q: queue.Queue = queue.Queue(maxsize=1)
    stop = threading.Event()

    main_mod._stop_event.clear()
    with patch.object(main_mod, "Capturer", _FakeCapturer):
        t = threading.Thread(
            target=main_mod.capture_loop,
            args=(
                {"left": 0, "top": 0, "width": 60, "height": 40},
                detector, debouncer, q, 0.01, stop,
            ),
            daemon=True,
        )
        t.start()
        time.sleep(0.05)
        main_mod._stop_event.set()
        t.join(timeout=2.0)
        assert not t.is_alive()
    main_mod._stop_event.clear()  # 复位，避免影响其它测试


def test_enqueue_latest_drops_old_frame():
    """队列满时应丢弃旧帧、保留最新帧。"""
    q: queue.Queue = queue.Queue(maxsize=1)
    old = np.zeros((2, 2, 3), np.uint8)
    new = np.ones((2, 2, 3), np.uint8)
    main_mod._enqueue_latest(q, old)
    main_mod._enqueue_latest(q, new)  # 队列已满，应替换
    got = q.get_nowait()
    assert np.array_equal(got, new)
    assert q.empty()
