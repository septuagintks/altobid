"""altobid — 本地多模态验证码解答工具。

包初始化：装配日志系统，并根据配置决定是否启用调试帧落盘目录。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

__version__ = "0.1.0"

# 项目根目录（altobid/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_configured = False


def setup_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """初始化根日志器。重复调用只生效一次。

    Args:
        level: 日志级别名（DEBUG/INFO/WARNING/ERROR）。
        log_file: 若提供，追加写入该文件；否则仅输出到控制台。
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger("altobid")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取带 altobid 前缀的子日志器。"""
    return logging.getLogger(f"altobid.{name}")
