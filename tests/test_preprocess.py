"""预处理测试。"""
import pytest
from PIL import Image

from altobid.preprocess import IMAGE_FACTOR, Preprocessor, smart_resize

MIN_P = 512 * 512
MAX_P = 768 * 768


def _img(h: int, w: int, mode: str = "RGB") -> Image.Image:
    return Image.new(mode, (w, h))


# ---- smart_resize ----

def test_aligns_to_factor():
    h, w = smart_resize(1000, 1300, IMAGE_FACTOR, MIN_P, MAX_P)
    assert h % IMAGE_FACTOR == 0
    assert w % IMAGE_FACTOR == 0


def test_large_image_capped_to_max_pixels():
    h, w = smart_resize(2000, 3000, IMAGE_FACTOR, MIN_P, MAX_P)
    assert h * w <= MAX_P


def test_small_image_raised_to_min_pixels():
    h, w = smart_resize(100, 120, IMAGE_FACTOR, MIN_P, MAX_P)
    assert h * w >= MIN_P


def test_in_range_preserves_roughly():
    # 目标区间内的尺寸，缩放后仍在区间
    h, w = smart_resize(640, 640, IMAGE_FACTOR, MIN_P, MAX_P)
    assert MIN_P <= h * w <= MAX_P


def test_aspect_ratio_roughly_preserved():
    h0, w0 = 600, 1200  # 1:2
    h, w = smart_resize(h0, w0, IMAGE_FACTOR, MIN_P, MAX_P)
    assert abs((w / h) - (w0 / h0)) < 0.15


def test_extreme_ratio_raises():
    with pytest.raises(ValueError):
        smart_resize(10, 5000, IMAGE_FACTOR, MIN_P, MAX_P)


# ---- Preprocessor ----

def test_process_returns_rgb_pil():
    p = Preprocessor(MIN_P, MAX_P)
    img = p.process(_img(300, 400))
    assert isinstance(img, Image.Image)
    assert img.mode == "RGB"


def test_process_output_within_pixel_budget():
    p = Preprocessor(MIN_P, MAX_P)
    img = p.process(_img(2000, 2000))
    w, h = img.size
    assert h * w <= MAX_P


def test_process_converts_non_rgb_to_rgb():
    # 传入 RGBA / L 等模式应统一转 RGB
    for mode in ("RGBA", "L", "P"):
        img = Preprocessor(MIN_P, MAX_P).process(_img(560, 560, mode))
        assert img.mode == "RGB"
