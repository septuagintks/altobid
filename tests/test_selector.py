"""区域选择器测试。"""
import tkinter as tk
from unittest.mock import MagicMock, patch

import pytest

from altobid.selector import RegionSelector


def test_region_selector_normal_release():
    """测试正常拖拽释放（左上到右下）。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._start = (100, 200)

    # 模拟释放事件
    event = MagicMock()
    event.x, event.y = 300, 400

    # Mock _close 避免实际销毁窗口
    selector._close = MagicMock()
    selector._on_release(event)

    assert selector._result == {"left": 100, "top": 200, "width": 200, "height": 200}


def test_region_selector_reverse_drag():
    """测试反向拖拽（右下到左上）自动归一化。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._start = (300, 400)

    event = MagicMock()
    event.x, event.y = 100, 200

    selector._close = MagicMock()
    selector._on_release(event)

    assert selector._result == {"left": 100, "top": 200, "width": 200, "height": 200}


def test_region_selector_misclick():
    """测试误点击过滤（拖拽距离 < 5 像素）。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._start = (100, 200)

    event = MagicMock()
    event.x, event.y = 103, 202  # width=3, height=2

    selector._close = MagicMock()
    selector._on_release(event)

    assert selector._result is None


def test_region_selector_escape_cancel():
    """测试 Esc 取消。"""
    selector = RegionSelector()
    selector._close = MagicMock()

    event = MagicMock()
    selector._on_cancel(event)

    assert selector._result is None
    selector._close.assert_called_once()


def test_region_selector_multi_monitor():
    """测试多显示器虚拟屏坐标偏移（左上角为负）。"""
    selector = RegionSelector()
    selector._origin_left = -1920
    selector._origin_top = 0
    selector._start = (100, 50)

    event = MagicMock()
    event.x, event.y = 300, 250

    selector._close = MagicMock()
    selector._on_release(event)

    # 画布坐标 (100, 50) -> 绝对屏幕坐标 (-1920+100, 0+50) = (-1820, 50)
    assert selector._result == {"left": -1820, "top": 50, "width": 200, "height": 200}


def test_region_selector_no_start():
    """测试未按下鼠标就释放（start=None）。"""
    selector = RegionSelector()
    selector._start = None
    selector._close = MagicMock()

    event = MagicMock()
    selector._on_release(event)

    assert selector._result is None
    selector._close.assert_called_once()
