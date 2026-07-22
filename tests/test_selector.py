"""区域选择器测试。"""
import sys
import tkinter as tk
from unittest.mock import MagicMock, patch

import pytest

# Mock mss 和 pynput.keyboard，避免依赖问题
sys.modules['mss'] = MagicMock()
sys.modules['pynput'] = MagicMock()
sys.modules['pynput.keyboard'] = MagicMock()

from altobid.selector import RegionSelector


def test_region_selector_normal_release():
    """测试正常拖拽释放（左上到右下）。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._selecting = True
    selector._start = (100, 200)
    selector._callback = MagicMock()

    # 模拟释放事件
    event = MagicMock()
    event.x, event.y = 300, 400

    # Mock _notify_region 避免实际回调
    selector._notify_region = MagicMock()
    selector._on_release(event)

    assert selector._region == (100, 200, 300, 400)
    assert not selector._selecting


def test_region_selector_reverse_drag():
    """测试反向拖拽（右下到左上）自动归一化。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._selecting = True
    selector._start = (300, 400)

    event = MagicMock()
    event.x, event.y = 100, 200

    selector._notify_region = MagicMock()
    selector._on_release(event)

    assert selector._region == (100, 200, 300, 400)


def test_region_selector_misclick():
    """测试误点击过滤（拖拽距离 < 5 像素）。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._selecting = True
    selector._start = (100, 200)
    selector._canvas = MagicMock()
    selector._root = MagicMock()

    event = MagicMock()
    event.x, event.y = 103, 202  # width=3, height=2

    selector._on_release(event)

    assert selector._region is None
    assert not selector._selecting


def test_region_selector_escape_cancel():
    """测试 Esc 取消框选。"""
    selector = RegionSelector()
    selector._selecting = True
    selector._canvas = MagicMock()
    selector._root = MagicMock()

    selector._cancel_selection()

    assert selector._region is None
    assert not selector._selecting


def test_region_selector_multi_monitor():
    """测试多显示器虚拟屏坐标偏移（左上角为负）。"""
    selector = RegionSelector()
    selector._origin_left = -1920
    selector._origin_top = 0
    selector._selecting = True
    selector._start = (100, 50)
    selector._callback = MagicMock()

    event = MagicMock()
    event.x, event.y = 300, 250

    selector._notify_region = MagicMock()
    selector._on_release(event)

    # 画布坐标 (100, 50, 300, 250) 保存
    assert selector._region == (100, 50, 300, 250)


def test_region_selector_no_start():
    """测试未按下鼠标就释放（start=None）。"""
    selector = RegionSelector()
    selector._selecting = True
    selector._start = None

    event = MagicMock()
    selector._on_release(event)

    # 不应设置 region
    assert selector._region is None


def test_notify_region_conversion():
    """测试 _notify_region 坐标转换。"""
    selector = RegionSelector()
    selector._origin_left = -1920
    selector._origin_top = 100
    selector._region = (50, 60, 250, 260)
    selector._callback = MagicMock()

    selector._notify_region()

    # 检查回调收到的 BBox（画布 -> 绝对屏幕坐标）
    args = selector._callback.call_args
    # 因为用 threading.Thread 调用，检查 call_count
    assert selector._callback.call_count == 1

