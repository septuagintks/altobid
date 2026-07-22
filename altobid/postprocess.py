"""后处理：从模型输出中提取最终答案。

Qwen2.5-VL 虽被 prompt 约束只输出答案，但小模型仍可能带上思考过程、
"答案："前缀、markdown 代码块、算式或标点。这里做稳健提取：
数字（含负数/小数）优先，其次选项字母 A~D，都没有则返回清洗后的文本。
"""
from __future__ import annotations

import re

from . import get_logger

log = get_logger("postprocess")

# 常见答案前缀（带冒号）
ANSWER_PREFIXES = [
    r"最终答案[：:]\s*",
    r"答案[：:]\s*",
    r"结果[：:]\s*",
    r"Final answer[：:]\s*",
    r"Answer[：:]\s*",
]

CODE_BLOCK = re.compile(r"```(?:\w+)?\s*\n?(.*?)\n?```", re.DOTALL)
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
LETTER_RE = re.compile(r"\b([A-Da-d])\b")


class PostProcessor:
    """清洗并提取模型输出中的最终答案。"""

    def __init__(self) -> None:
        self.answer_prefix_re = re.compile("|".join(ANSWER_PREFIXES), re.IGNORECASE)

    def clean(self, raw_output: str) -> str:
        """提取最终答案。

        1. 去 markdown 代码块包裹；
        2. 去"答案："等前缀；
        3. 取最后一非空行；
        4. 提取数字/字母（先在末行，失败则整段兜底）；
        5. 都没有则返回清洗后的末行。
        """
        text = self._strip_wrappers(raw_output)
        last_line = self._last_line(text)

        ans = self._extract(last_line)
        if ans is None:
            ans = self._extract(text)  # 末行无结果时整段兜底
        result = ans if ans is not None else last_line

        log.debug("后处理: %r -> %r", raw_output, result)
        return result

    # ---- 内部 --------------------------------------------------------------

    def _strip_wrappers(self, text: str) -> str:
        if "```" in text:
            m = CODE_BLOCK.search(text)
            if m:
                text = m.group(1)
        return self.answer_prefix_re.sub("", text)

    @staticmethod
    def _last_line(text: str) -> str:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        return lines[-1] if lines else text.strip()

    @staticmethod
    def _extract(s: str) -> str | None:
        """从字符串抽取答案：数字优先，其次 A~D。取不到返回 None。"""
        # 有等号时优先看等号右侧（"3 + 2 = 5" -> "5"）
        segment = s.rsplit("=", 1)[1] if "=" in s else s
        nums = NUMBER_RE.findall(segment) or NUMBER_RE.findall(s)
        if nums:
            return nums[-1]
        m = LETTER_RE.search(s)
        if m:
            return m.group(1).upper()
        return None
