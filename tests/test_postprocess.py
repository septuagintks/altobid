"""后处理测试。

新策略：轻量清洗，完整保留答案（去包裹/前缀/首尾标点空白），
不做数字优先抽取——避免把字母数字混合验证码（如 4a2b）切坏。
"""
import pytest

from altobid.postprocess import PostProcessor


@pytest.fixture
def cleaner():
    return PostProcessor()


# ---- 去前缀 ----

def test_removes_answer_prefix_chinese(cleaner):
    assert cleaner.clean("答案：42") == "42"
    assert cleaner.clean("最终答案: 123") == "123"


def test_removes_answer_prefix_english(cleaner):
    assert cleaner.clean("Answer: 42") == "42"
    assert cleaner.clean("Final answer: A") == "A"


# ---- 去代码块包裹 ----

def test_strips_code_block(cleaner):
    assert cleaner.clean("```python\n42\n```") == "42"


def test_combined_cleanup(cleaner):
    assert cleaner.clean("让我想想...\n答案：```\n42\n```") == "42"


# ---- 取末行 ----

def test_takes_last_line_when_multiline(cleaner):
    assert cleaner.clean("思考过程：3+2=5\n所以答案是\n5") == "5"


# ---- 直通干净答案 ----

def test_passthrough_clean_answer(cleaner):
    assert cleaner.clean("42") == "42"
    assert cleaner.clean("A") == "A"


def test_strips_trailing_punctuation(cleaner):
    assert cleaner.clean("答案：3.5。") == "3.5"
    assert cleaner.clean("“728”") == "728"


# ---- 关键：字母数字混合验证码完整保留（回归此前会被切坏的行为）----

def test_alphanumeric_preserved(cleaner):
    assert cleaner.clean("4a2b") == "4a2b"
    assert cleaner.clean("答案：zx8k") == "zx8k"
    assert cleaner.clean("```\nAB12\n```") == "AB12"


def test_multi_digit_preserved(cleaner):
    # 彩色数字/多位校验码不应被切成单个数字
    assert cleaner.clean("728") == "728"
    assert cleaner.clean("答案：1234") == "1234"


def test_pure_text_passthrough(cleaner):
    assert cleaner.clean("无法识别") == "无法识别"
