"""图片预处理。

把油猴脚本送来的验证码图转成模型输入的 PIL RGB Image：
1. 转 RGB；
2. 按 Qwen2.5-VL 的 smart_resize 规则缩放，使总像素落在 [min_pixels, max_pixels]，
   且宽高对齐到 factor(28) 的倍数。

自带 smart_resize 实现，输出尺寸与 Qwen processor 期望一致，避免二次缩放，
也不依赖尚未安装的 qwen_vl_utils。
"""
from __future__ import annotations

import math

from PIL import Image

from . import get_logger

log = get_logger("preprocess")

# Qwen2.5-VL 视觉 patch 对齐因子（14 patch × 2 merge）
IMAGE_FACTOR = 28
MAX_RATIO = 200  # 极端长宽比保护


def smart_resize(
    height: int,
    width: int,
    factor: int = IMAGE_FACTOR,
    min_pixels: int = 512 * 512,
    max_pixels: int = 768 * 768,
) -> tuple[int, int]:
    """返回对齐到 factor、且总像素落在 [min_pixels, max_pixels] 的 (h, w)。

    保持长宽比，逻辑与 Qwen2.5-VL 官方 smart_resize 一致。
    """
    if max(height, width) / min(height, width) > MAX_RATIO:
        raise ValueError(
            f"长宽比 {max(height, width) / min(height, width):.1f} 超过 {MAX_RATIO}"
        )

    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)

    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(factor, math.floor(height / beta / factor) * factor)
        w_bar = max(factor, math.floor(width / beta / factor) * factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor

    return h_bar, w_bar


class Preprocessor:
    """把 BGR 帧转成模型输入的 PIL RGB Image。"""

    def __init__(
        self,
        min_pixels: int = 512 * 512,
        max_pixels: int = 768 * 768,
        factor: int = IMAGE_FACTOR,
    ) -> None:
        self.min_pixels = min_pixels
        self.max_pixels = max_pixels
        self.factor = factor

    def process(self, image: Image.Image) -> Image.Image:
        """PIL Image（任意模式）-> RGB、按 smart_resize 对齐的 PIL Image。

        分辨率细节最终仍交给 Qwen processor 的 min/max_pixels，这里只做 RGB 归一
        + 超大图预缩放，避免把巨图直接喂给模型。
        """
        rgb = image.convert("RGB")
        w, h = rgb.size
        new_h, new_w = smart_resize(
            h, w, self.factor, self.min_pixels, self.max_pixels
        )
        if (new_h, new_w) != (h, w):
            # 缩小用 LANCZOS，放大用 BICUBIC
            resample = Image.LANCZOS if new_w * new_h < w * h else Image.BICUBIC
            rgb = rgb.resize((new_w, new_h), resample=resample)
            log.debug("预处理 %dx%d -> %dx%d", w, h, new_w, new_h)
        return rgb
