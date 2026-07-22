"""截图模块测试。"""
import pytest

from altobid.capture import Capturer


def test_capturer_context_manager():
    """测试 Capturer 上下文管理器。"""
    bbox = {"left": 0, "top": 0, "width": 100, "height": 100}
    with Capturer(bbox) as cap:
        assert cap._sct is None  # 惰性初始化
        frame = cap.grab()
        assert cap._sct is not None
        assert frame.shape == (100, 100, 3)


def test_capturer_lazy_init():
    """测试 mss 惰性初始化。"""
    bbox = {"left": 0, "top": 0, "width": 100, "height": 100}
    cap = Capturer(bbox)
    assert cap._sct is None

    # 首次 grab 触发初始化
    frame = cap.grab()

    assert cap._sct is not None
    assert frame.shape == (100, 100, 3)  # BGR
    assert frame.dtype == "uint8"

    cap.close()
    assert cap._sct is None


def test_capturer_real_screen():
    """真实截屏测试（抓取屏幕左上角 200x150）。"""
    bbox = {"left": 0, "top": 0, "width": 200, "height": 150}
    with Capturer(bbox) as cap:
        frame = cap.grab()

        assert frame.shape == (150, 200, 3)
        assert frame.dtype == "uint8"
