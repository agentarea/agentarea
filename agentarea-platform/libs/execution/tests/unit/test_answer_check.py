"""What the final-answer check flags, mirroring Constractio's output check."""

import pytest
from agentarea_execution.workflows.answer_check import (
    accept_rewrite,
    answer_check_config,
    find_leaks,
    rewrite_messages,
    tool_names_of,
)

TOOLS = [
    {"type": "function", "function": {"name": "mcp__constractio_instrumenty__edit_estimate"}},
    {"type": "function", "function": {"name": "completion"}},
]


def _kinds(text: str, language: str | None = "ru") -> set[str]:
    return {leak.kind for leak in find_leaks(text, tool_names_of(TOOLS), language)}


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("最需要 уточнить размеры", "cjk"),
        ("Вызвал edit_estimate и всё пересчитал", "tool_name"),
        ("Статус: work_plan_ready, можно продолжать", "identifier"),
        ("Error: ENOENT at XLSX.readFile (/root/node_modules/x.js)", "stack_trace"),
        ('Вот данные: {"rooms": 3}', "json"),
        ("Пересчитал по этим же rooms всё как надо", "english"),
    ],
)
def test_each_kind_of_leak_is_found(text, kind):
    assert kind in _kinds(text)


def test_a_clean_russian_answer_has_no_leaks():
    assert _kinds("Смета готова: 3 комнаты, итого 412 000 ₽. Файл — смета.xlsx") == set()


def test_links_file_names_and_code_blocks_are_the_persons_data():
    text = (
        "Скачайте [смету](https://app.example/api/files/estimate_v2.xlsx), "
        "файл estimate_final.pdf, и код:\n```\n{\"rooms\": 3}\n```"
    )
    assert _kinds(text) == set()


def test_english_words_count_only_in_an_otherwise_russian_answer():
    assert "english" not in _kinds("The estimate is ready for review", language="ru")
    assert "english" not in _kinds("Пересчитал по этим rooms", language=None)


def test_cjk_is_not_a_leak_in_a_cjk_language():
    assert "cjk" not in _kinds("最需要", language="zh")


def test_a_rewrite_that_loses_a_link_is_refused():
    original = "Готово: https://app.example/e/1 — смотрите rooms"
    assert accept_rewrite(original, "Готово, смотрите комнаты", strip_cjk=False) is None
    assert accept_rewrite(original, "Готово: https://app.example/e/1", strip_cjk=False)
    assert accept_rewrite(original, "   ", strip_cjk=False) is None


def test_the_rewrite_names_what_is_wrong_and_takes_an_instruction():
    leaks = find_leaks("по этим rooms", [], "ru")
    messages = rewrite_messages("по этим rooms", leaks, "ru", "Свой промпт")
    assert messages[0] == {"role": "system", "content": "Свой промпт"}
    assert "english «rooms»" in messages[1]["content"]


def test_the_check_is_off_unless_the_policy_turns_it_on():
    assert answer_check_config(None) is None
    assert answer_check_config({"content_safety": {"output_sanitizer_enabled": True}}) is None
    off = {"content_safety": {"answer_check": {"enabled": False}}}
    assert answer_check_config(off) is None
    on = {"content_safety": {"answer_check": {"enabled": True, "language": "ru"}}}
    assert answer_check_config(on) == {"enabled": True, "language": "ru"}
