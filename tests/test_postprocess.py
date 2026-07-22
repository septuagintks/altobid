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


def test_extracts_number_from_sentence(cleaner):
    assert cleaner.clean("答案是5。") == "5"
    assert cleaner.clean("经过计算，答案是 -7") == "-7"
    assert cleaner.clean("等于8") == "8"
    assert cleaner.clean("The answer is 42.") == "42"


def test_extracts_from_equation(cleaner):
    assert cleaner.clean("3 + 2 = 5") == "5"
    assert cleaner.clean("结果为 12") == "12"


def test_extracts_option_letter(cleaner):
    assert cleaner.clean("答案是 C") == "C"
    assert cleaner.clean("选 b") == "B"


def test_decimal_number(cleaner):
    assert cleaner.clean("答案：3.5") == "3.5"


def test_unrecognized_passthrough(cleaner):
    # 无数字无字母选项时返回清洗后的末行
    assert cleaner.clean("无法识别") == "无法识别"


# ---- OutputHandler ----


def test_output_handler_console_only(capsys):
    """控制台输出（不开窗口、不复制，避免阻塞/副作用）。"""
    handler = OutputHandler(show_window=False, copy_to_clipboard=False)
    handler.output("42")
    captured = capsys.readouterr()
    assert "答案: 42" in captured.out


def test_output_handler_clipboard(capsys):
    """剪贴板复制不应抛异常（tkinter 兜底）。"""
    handler = OutputHandler(show_window=False, copy_to_clipboard=True)
    handler.output("99")  # 不崩即通过
    captured = capsys.readouterr()
    assert "答案: 99" in captured.out
