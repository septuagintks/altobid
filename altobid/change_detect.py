"""变化检测与防抖。

- ChangeDetector：判断当前帧相对“已提交基准帧”是否发生有意义的变化。
- Debouncer：确认画面变完并稳定（连续 N 帧帧间差异低）后才放行，并维护冷却期。

两者共用同一套“缩小灰度 + 差异占比”的度量。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from . import get_logger

log = get_logger("change_detect")


# ---- 共享度量 --------------------------------------------------------------

def to_small_gray(frame: np.ndarray, size: int) -> np.ndarray:
    """转灰度并缩到 size×size，抗噪声与轻微抖动。"""
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)


def diff_ratio(a: np.ndarray, b: np.ndarray, pixel_delta: int) -> float:
    """两张同尺寸灰度小图中“变化像素”的占比。

    单像素灰度差 > pixel_delta 才计为变化像素。
    """
    delta = cv2.absdiff(a, b)
    changed = int(np.count_nonzero(delta > pixel_delta))
    return changed / delta.size


def phash(frame: np.ndarray, hash_size: int = 8) -> int:
    """感知哈希（DCT），返回 hash_size² 位整数。"""
    gray = to_small_gray(frame, hash_size * 4)  # 32×32 for hash_size=8
    dct = cv2.dct(np.float32(gray))
    low = dct[:hash_size, :hash_size]
    med = np.median(low[1:, 1:])  # 排除 DC 分量
    bits = (low > med).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    """两个整数哈希的汉明距离。"""
    return bin(a ^ b).count("1")


# ---- 变化检测 --------------------------------------------------------------

class ChangeDetector:
    """相对“基准帧”判断是否变化。基准帧由外部在提交后显式 update。"""

    def __init__(
        self,
        method: str = "absdiff",
        downscale: int = 64,
        pixel_delta: int = 25,
        change_threshold: float = 0.02,
        phash_size: int = 8,
    ) -> None:
        self.method = method
        self.downscale = downscale
        self.pixel_delta = pixel_delta
        self.change_threshold = change_threshold
        self.phash_size = phash_size

        self._baseline_small: np.ndarray | None = None
        self._baseline_hash: int | None = None

    def changed(self, frame: np.ndarray) -> bool:
        """当前帧是否相对基准发生变化。首帧只设基准、返回 False。"""
        if self.method == "phash":
            return self._changed_phash(frame)
        return self._changed_absdiff(frame)

    def _changed_absdiff(self, frame: np.ndarray) -> bool:
        small = to_small_gray(frame, self.downscale)
        if self._baseline_small is None:
            self._baseline_small = small
            return False
        ratio = diff_ratio(small, self._baseline_small, self.pixel_delta)
        return ratio > self.change_threshold

    def _changed_phash(self, frame: np.ndarray) -> bool:
        h = phash(frame, self.phash_size)
        if self._baseline_hash is None:
            self._baseline_hash = h
            return False
        bits = self.phash_size * self.phash_size
        return hamming(h, self._baseline_hash) / bits > self.change_threshold

    def update(self, frame: np.ndarray) -> None:
        """把 frame 设为新基准（通常在成功提交推理后调用）。"""
        if self.method == "phash":
            self._baseline_hash = phash(frame, self.phash_size)
        else:
            self._baseline_small = to_small_gray(frame, self.downscale)

    def reset(self) -> None:
        self._baseline_small = None
        self._baseline_hash = None


# ---- 防抖 ------------------------------------------------------------------

class Debouncer:
    """帧间稳定判定 + 冷却期。

    push(frame) 在“连续 stable_frames 帧帧间差异都 <= stable_threshold”时返回 True，
    随后进入 cooldown_s 冷却期，期间 push 一律返回 False（防结果动画自触发）。
    """

    def __init__(
        self,
        stable_frames: int = 3,
        stable_threshold: float = 0.01,
        cooldown_s: float = 1.5,
        downscale: int = 64,
        pixel_delta: int = 25,
    ) -> None:
        self.stable_frames = stable_frames
        self.stable_threshold = stable_threshold
        self.cooldown_s = cooldown_s
        self.downscale = downscale
        self.pixel_delta = pixel_delta

        self._prev_small: np.ndarray | None = None
        self._stable_count = 0
        self._cooldown_until = 0.0

    def push(self, frame: np.ndarray) -> bool:
        """喂入一帧；返回是否应放行推理。"""
        now = time.monotonic()
        if now < self._cooldown_until:
            return False

        small = to_small_gray(frame, self.downscale)
        if self._prev_small is None:
            self._prev_small = small
            self._stable_count = 1
            return False

        ratio = diff_ratio(small, self._prev_small, self.pixel_delta)
        self._prev_small = small
        if ratio <= self.stable_threshold:
            self._stable_count += 1
        else:
            self._stable_count = 1  # 仍在变，重新计数

        if self._stable_count >= self.stable_frames:
            self._cooldown_until = now + self.cooldown_s
            self.reset()
            return True
        return False

    def reset(self) -> None:
        """清空稳定计数（不影响冷却期）。"""
        self._prev_small = None
        self._stable_count = 0
