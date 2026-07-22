"""调试辅助：把触发推理的帧落盘，便于人工核对采集/变化检测是否抓对了画面。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import get_logger

if TYPE_CHECKING:
    import numpy as np

log = get_logger("debug")


class FrameSaver:
    """按需把帧保存为 PNG，文件名带时间戳与答案。

    仅当 enabled=True 时生效；关闭时所有方法为廉价空操作。
    """

    def __init__(self, enabled: bool = False, out_dir: Optional[str] = None) -> None:
        self.enabled = enabled
        self.out_dir = Path(out_dir) if out_dir else None
        if self.enabled and self.out_dir is not None:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            log.info("调试帧落盘已开启 -> %s", self.out_dir)

    def save(self, frame: "np.ndarray", answer: str = "") -> Optional[Path]:
        """保存一帧（BGR），返回落盘路径；未开启则返回 None。"""
        if not self.enabled or self.out_dir is None:
            return None
        try:
            import cv2

            ts = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            safe = "".join(c for c in answer if c.isalnum() or c in "-.") or "na"
            path = self.out_dir / f"{ts}_{safe}.png"
            cv2.imwrite(str(path), frame)
            log.debug("已保存调试帧: %s", path)
            return path
        except Exception as e:  # 落盘失败不应影响主流程
            log.warning("保存调试帧失败: %s", e)
            return None
