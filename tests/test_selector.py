"""区域选择器测试。"""
import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock mss 和 pynput，避免依赖问题
sys.modules['mss'] = MagicMock()
sys.modules['mss.mss'] = MagicMock()
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

    # 模拟覆盖层窗口
    overlay = MagicMock()
    canvas = MagicMock()
    selector._overlay_root = overlay
    selector._overlay_canvas = canvas

    # Mock _show_frame 和 _notify_region
    selector._show_frame = MagicMock()
    selector._notify_region = MagicMock()

    event = MagicMock()
    event.x, event.y = 300, 400

    selector._on_overlay_release(event, canvas, overlay)

    assert selector._region == (100, 200, 300, 400)
    assert not selector._selecting
    selector._show_frame.assert_called_once()
    selector._notify_region.assert_called_once()


def test_region_selector_reverse_drag():
    """测试反向拖拽（右下到左上）自动归一化。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._selecting = True
    selector._start = (300, 400)

    overlay = MagicMock()
    canvas = MagicMock()
    selector._overlay_root = overlay

    selector._show_frame = MagicMock()
    selector._notify_region = MagicMock()

    event = MagicMock()
    event.x, event.y = 100, 200

    selector._on_overlay_release(event, canvas, overlay)

    assert selector._region == (100, 200, 300, 400)


def test_region_selector_misclick():
    """测试误点击过滤（拖拽距离 < 5 像素）。"""
    selector = RegionSelector()
    selector._origin_left = 0
    selector._origin_top = 0
    selector._selecting = True
    selector._start = (100, 200)

    overlay = MagicMock()
    canvas = MagicMock()
    selector._overlay_root = overlay

    event = MagicMock()
    event.x, event.y = 103, 202  # width=3, height=2

    selector._on_overlay_release(event, canvas, overlay)

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

    overlay = MagicMock()
    canvas = MagicMock()
    selector._overlay_root = overlay

    selector._show_frame = MagicMock()
    selector._notify_region = MagicMock()

    event = MagicMock()
    event.x, event.y = 300, 250

    selector._on_overlay_release(event, canvas, overlay)

    # 转换为绝对屏幕坐标
    assert selector._region == (-1920 + 100, 50, -1920 + 300, 250)


def test_region_selector_no_start():
    """测试未按下鼠标就释放（start=None）。"""
    selector = RegionSelector()
    selector._selecting = True
    selector._start = None

    overlay = MagicMock()
    canvas = MagicMock()

    event = MagicMock()
    selector._on_overlay_release(event, canvas, overlay)

    # 不应设置 region
    assert selector._region is None


def test_notify_region_conversion():
    """测试 _notify_region 坐标转换为 BBox。"""
    selector = RegionSelector()
    selector._region = (50, 60, 250, 260)
    selector._callback = MagicMock()

    selector._notify_region()

    # 检查回调收到的 BBox（左上右下 -> left/top/width/height）
    assert selector._callback.call_count == 1
    # 因为是 threading.Thread 调用，直接检查参数
    call_args = selector._callback.call_args
    bbox = call_args[0][0] if call_args else None
    assert bbox is not None
    assert bbox["left"] == 50
    assert bbox["top"] == 60
    assert bbox["width"] == 200
    assert bbox["height"] == 200


def test_ctrl_drag_adjustment():
    """测试按住 Ctrl 后拖动框体。"""
    selector = RegionSelector()
    selector._ctrl_pressed = True
    selector._region = (100, 100, 300, 300)
    selector._drag_start = (10, 10)
    selector._dragging = True
    selector._resize_corner = None

    selector._show_frame = MagicMock()

    event = MagicMock()
    event.x, event.y = 30, 40  # dx=20, dy=30

    selector._on_frame_drag(event)

    # 整体移动：所有坐标 + (20, 30)
    assert selector._region == (120, 130, 320, 330)


def test_ctrl_resize_corner():
    """测试按住 Ctrl 后拖拽右下角调整大小。"""
    selector = RegionSelector()
    selector._ctrl_pressed = True
    selector._region = (100, 100, 300, 300)
    selector._drag_start = (200, 200)  # 相对框体坐标
    selector._resize_corner = "br"
    selector._dragging = False

    selector._show_frame = MagicMock()

    event = MagicMock()
    event.x, event.y = 250, 220  # dx=50, dy=20

    selector._on_frame_drag(event)

    # 右下角：right += dx, bottom += dy
    assert selector._region == (100, 100, 350, 320)
