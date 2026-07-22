"""后处理：从模型输出中提取最终答案。

模型被 prompt 约束为「只输出答案」，但小模型仍可能带上思考过程、
"答案："前缀、markdown 代码块或首尾标点。这里做**轻量清洗**：
去包裹、去前缀、取末行、剥首尾标点空白——但**完整保留答案本体**。

不做数字优先抽取：验证码答案可能是多位数字（728）、字母数字混合（4a2b）、
纯字母等，按单个数字/字母切会切坏。清洗后原样返回。
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
# 首尾需要剥掉的标点/引号/空白（保留答案内部字符）
TRIM_CHARS = " \t\r\n。，,、；;：:！!？?\"'“”‘’()（）[]【】<>《》."


class PostProcessor:
    """轻量清洗模型输出，完整保留答案本体。"""

    def __init__(self) -> None:
        self.answer_prefix_re = re.compile("|".join(ANSWER_PREFIXES), re.IGNORECASE)

    def clean(self, raw_output: str) -> str:
        """清洗并返回最终答案。

        1. 去 markdown 代码块包裹；
        2. 去"答案："等前缀；
        3. 取最后一非空行；
        4. 剥首尾标点/引号/空白。
        """
        text = self._strip_wrappers(raw_output)
        result = self._last_line(text).strip(TRIM_CHARS)
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
