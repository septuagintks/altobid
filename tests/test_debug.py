"""调试帧落盘测试。"""
import numpy as np

from altobid.debug import FrameSaver


def _frame() -> np.ndarray:
    return np.zeros((60, 120, 3), np.uint8)


def test_disabled_is_noop(tmp_path):
    saver = FrameSaver(enabled=False, out_dir=str(tmp_path))
    assert saver.save(_frame(), "42") is None
    assert list(tmp_path.iterdir()) == []


def test_enabled_writes_png(tmp_path):
    saver = FrameSaver(enabled=True, out_dir=str(tmp_path))
    path = saver.save(_frame(), "42")
    assert path is not None
    assert path.exists()
    assert path.suffix == ".png"
    assert "42" in path.name


def test_answer_sanitized_in_filename(tmp_path):
    saver = FrameSaver(enabled=True, out_dir=str(tmp_path))
    path = saver.save(_frame(), "answer/is:5?")  # 含非法文件名字符
    assert path is not None
    assert path.exists()  # 不因非法字符崩溃


def test_empty_answer_uses_placeholder(tmp_path):
    saver = FrameSaver(enabled=True, out_dir=str(tmp_path))
    path = saver.save(_frame(), "")
    assert path is not None
    assert "na" in path.name
