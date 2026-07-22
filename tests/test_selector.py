"""区域选择器测试。"""
import sys
from unittest.mock import MagicMock, patch

import pytest

# 仅当真实依赖缺失时才 mock（避免污染 sys.modules 影响其它测试文件）。
# 在装齐依赖的环境用真实模块，在无依赖环境（如 Python 3.14）回退 mock。
for _mod in ("mss", "pynput", "pynput.keyboard"):
    try:
        __import__(_mod)
    except ImportError:
        sys.modules[_mod] = MagicMock()

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
    selector._overlay_root = MagicMock()

    overlay = MagicMock()
    canvas = MagicMock()

    event = MagicMock()
    selector._on_overlay_release(event, canvas, overlay)

    # 不应设置 region
    assert selector._region is None


def test_close_overlay_resets_state():
    """关闭覆盖层应复位状态，保证可再次触发框选（修复 Esc 后卡死）。"""
    selector = RegionSelector()
    selector._overlay_root = MagicMock()
    selector._overlay_canvas = MagicMock()
    selector._selecting = True
    selector._start = (10, 10)
    selector._rect_id = 5

    selector._close_overlay()

    assert selector._overlay_root is None
    assert selector._overlay_canvas is None
    assert not selector._selecting
    assert selector._start is None
    assert selector._rect_id is None
    # 复位后 _show_overlay 的重复触发守卫不再阻塞（_overlay_root is None）


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
    """测试按住 Ctrl 后拖动框体（用屏幕绝对坐标 x_root/y_root）。"""
    selector = RegionSelector()
    selector._ctrl_pressed = True
    selector._region = (100, 100, 300, 300)
    selector._drag_start = (10, 10)
    selector._dragging = True
    selector._resize_corner = None

    selector._show_frame = MagicMock()

    event = MagicMock()
    event.x_root, event.y_root = 30, 40  # dx=20, dy=30

    selector._on_frame_drag(event)

    # 整体移动：所有坐标 + (20, 30)
    assert selector._region == (120, 130, 320, 330)


def test_ctrl_resize_corner():
    """测试按住 Ctrl 后拖拽右下角调整大小（用屏幕绝对坐标）。"""
    selector = RegionSelector()
    selector._ctrl_pressed = True
    selector._region = (100, 100, 300, 300)
    selector._drag_start = (200, 200)  # 屏幕绝对坐标
    selector._resize_corner = "br"
    selector._dragging = False

    selector._show_frame = MagicMock()

    event = MagicMock()
    event.x_root, event.y_root = 250, 220  # dx=50, dy=20

    selector._on_frame_drag(event)

    # 右下角：right += dx, bottom += dy
    assert selector._region == (100, 100, 350, 320)


def test_show_frame_reuses_window():
    """框线窗口只创建一次，拖动时复用（修复销毁重建闪烁）。"""
    selector = RegionSelector()
    selector._region = (100, 100, 300, 300)

    calls = {"ensure": 0}
    real_ensure = selector._ensure_frame_window

    def counting_ensure():
        calls["ensure"] += 1
        # 首次真正创建一个假窗口
        if selector._frame_root is None:
            selector._frame_root = MagicMock()
            selector._frame_canvas = MagicMock()

    selector._ensure_frame_window = counting_ensure
    selector._update_frame = MagicMock()

    selector._show_frame()
    selector._show_frame()
    selector._show_frame()

    # ensure 被调 3 次但只有首次真正建窗口，update 每次都调
    assert calls["ensure"] == 3
    assert selector._update_frame.call_count == 3
    # 窗口对象始终是同一个（未重建）
    assert selector._frame_root is not None


def test_update_frame_sets_geometry():
    """_update_frame 应按 region 设置窗口几何。"""
    selector = RegionSelector()
    selector._region = (50, 60, 250, 260)  # 200x200 at (50,60)
    selector._frame_root = MagicMock()
    selector._frame_canvas = MagicMock()

    selector._update_frame()

    # 几何字符串应为 "200x200+50+60"
    selector._frame_root.geometry.assert_called_once_with("200x200+50+60")
    # 画布应清空并重绘
    selector._frame_canvas.delete.assert_called_once_with("all")
