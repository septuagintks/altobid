"""后处理：清洗模型输出。

Qwen2.5-VL 输出可能带噪声（思考过程、"答案："标记、markdown 代码块等），
需要提取最终答案。
"""
from __future__ import annotations

import re

from . import get_logger

log = get_logger("postprocess")

# 常见答案前缀模式（支持中英文）
ANSWER_PREFIXES = [
    r"答案[：:]\s*",
    r"最终答案[：:]\s*",
    r"Answer[：:]\s*",
    r"Final answer[：:]\s*",
]

# Markdown 代码块包裹
CODE_BLOCK = re.compile(r"```(?:\w+)?\s*\n?(.*?)\n?```", re.DOTALL)


class PostProcessor:
    """清洗模型输出，提取最终答案。"""

    def __init__(self) -> None:
        self.answer_prefix_re = re.compile(
            "|".join(ANSWER_PREFIXES), re.IGNORECASE
        )

    def clean(self, raw_output: str) -> str:
        """提取最终答案。

        策略：
        1. 去除 markdown 代码块包裹
        2. 移除"答案："等前缀
        3. 取最后一行（多行输出时最后一行通常是答案）
        4. strip 首尾空白
        """
        text = raw_output

        # 去除代码块
        if "```" in text:
            match = CODE_BLOCK.search(text)
            if match:
                text = match.group(1)

        # 移除答案前缀
        text = self.answer_prefix_re.sub("", text)

        # 取最后非空行
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if lines:
            text = lines[-1]
        else:
            text = text.strip()

        log.debug("后处理: %r -> %r", raw_output, text)
        return text
