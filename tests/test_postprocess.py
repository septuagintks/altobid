"""后处理与输出测试。"""
import pytest

from altobid.output import OutputHandler
from altobid.postprocess import PostProcessor


# ---- PostProcessor ----


@pytest.fixture
def cleaner():
    return PostProcessor()


def test_removes_answer_prefix_chinese(cleaner):
    assert cleaner.clean("答案：42") == "42"
    assert cleaner.clean("最终答案: 123") == "123"


def test_removes_answer_prefix_english(cleaner):
    assert cleaner.clean("Answer: 42") == "42"
    assert cleaner.clean("Final answer: A") == "A"


def test_extracts_from_code_block(cleaner):
    text = "```python\n42\n```"
    assert cleaner.clean(text) == "42"


def test_takes_last_line_when_multiline(cleaner):
    text = "思考过程：3+2=5\n所以答案是\n5"
    assert cleaner.clean(text) == "5"


def test_combined_cleanup(cleaner):
    text = "让我想想...\n答案：```\n42\n```"
    assert cleaner.clean(text) == "42"


def test_passthrough_clean_answer(cleaner):
    assert cleaner.clean("42") == "42"
    assert cleaner.clean("A") == "A"


# ---- OutputHandler ----


def test_output_handler_console_only(capsys):
    """控制台输出（不开窗口避免阻塞测试）。"""
    handler = OutputHandler(show_window=False)
    handler.output("42")
    captured = capsys.readouterr()
    assert "答案: 42" in captured.out
