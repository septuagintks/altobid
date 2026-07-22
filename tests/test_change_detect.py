"""变化检测与防抖测试（确定性合成帧）。"""
import time

import numpy as np

from altobid.change_detect import (
    ChangeDetector,
    Debouncer,
    diff_ratio,
    hamming,
    phash,
    to_small_gray,
)


def _frame(value: int = 0) -> np.ndarray:
    return np.full((100, 200, 3), value, np.uint8)


# ---- 共享度量 ----

def test_to_small_gray_shape():
    small = to_small_gray(_frame(128), 64)
    assert small.shape == (64, 64)
    assert small.ndim == 2


def test_diff_ratio_bounds():
    a = np.zeros((64, 64), np.uint8)
    assert diff_ratio(a, a, 25) == 0.0
    b = np.full((64, 64), 255, np.uint8)
    assert diff_ratio(a, b, 25) == 1.0


def test_hamming():
    assert hamming(0b1010, 0b1000) == 1
    assert hamming(0xFF, 0x00) == 8


# ---- ChangeDetector ----

def test_absdiff_first_frame_sets_baseline():
    d = ChangeDetector(method="absdiff", change_threshold=0.02)
    assert d.changed(_frame(0)) is False


def test_absdiff_detects_big_change():
    d = ChangeDetector(method="absdiff", change_threshold=0.02, pixel_delta=25)
    d.changed(_frame(0))
    assert d.changed(_frame(255)) is True


def test_absdiff_ignores_tiny_noise():
    d = ChangeDetector(method="absdiff", change_threshold=0.02, pixel_delta=25)
    d.changed(_frame(0))
    noisy = _frame(0)
    noisy[0:2, 0:2] = 200
    assert d.changed(noisy) is False


def test_update_resets_baseline():
    d = ChangeDetector(method="absdiff", change_threshold=0.02)
    d.changed(_frame(0))
    big = _frame(255)
    assert d.changed(big) is True
    d.update(big)
    assert d.changed(big.copy()) is False


def test_phash_detects_change():
    d = ChangeDetector(method="phash", change_threshold=0.1)
    assert d.changed(_frame(0)) is False
    rng = np.random.default_rng(0)
    b = rng.integers(0, 255, (100, 200, 3), dtype=np.uint8)
    assert d.changed(b) is True


def test_phash_value_stable():
    a = _frame(50)
    assert phash(a) == phash(a.copy())


# ---- Debouncer ----

def test_debouncer_fires_after_stable_frames():
    db = Debouncer(stable_frames=3, stable_threshold=0.01, cooldown_s=0.3)
    stable = _frame(128)
    results = [db.push(stable.copy()) for _ in range(3)]
    assert results == [False, False, True]


def test_debouncer_cooldown_blocks_refire():
    db = Debouncer(stable_frames=3, stable_threshold=0.01, cooldown_s=0.3)
    stable = _frame(128)
    for _ in range(3):
        db.push(stable.copy())
    assert db.push(stable.copy()) is False  # 冷却期内
    time.sleep(0.35)
    assert db.push(stable.copy()) is False
    assert db.push(stable.copy()) is False
    assert db.push(stable.copy()) is True  # 冷却后重新累积


def test_debouncer_no_fire_while_changing():
    db = Debouncer(stable_frames=3, stable_threshold=0.01, cooldown_s=0.3)
    rng = np.random.default_rng(1)
    fired = any(
        db.push(rng.integers(0, 255, (100, 200, 3), dtype=np.uint8))
        for _ in range(6)
    )
    assert fired is False
