"""What the final-answer check flags, mirroring Constractio's output check."""

import pytest
from agentarea_execution.workflows.answer_check import (
    accept_rewrite,
    answer_check_config,
    find_leaks,
    rewrite_messages,
    tool_names_of,
)


def _reply(answer: str, changes: str = "перевёл rooms") -> str:
    return f"<changes>{changes}</changes>\n<answer>\n{answer}\n</answer>"


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
        'файл estimate_final.pdf, и код:\n```\n{"rooms": 3}\n```'
    )
    assert _kinds(text) == set()


def test_english_words_count_only_in_an_otherwise_russian_answer():
    assert "english" not in _kinds("The estimate is ready for review", language="ru")
    assert "english" not in _kinds("Пересчитал по этим rooms", language=None)


def test_cjk_is_not_a_leak_in_a_cjk_language():
    assert "cjk" not in _kinds("最需要", language="zh")


def test_a_rewrite_that_loses_a_link_is_refused():
    original = "Готово: https://app.example/e/1 — смотрите rooms"
    assert accept_rewrite(original, _reply("Готово, смотрите комнаты"), strip_cjk=False) is None
    kept = accept_rewrite(original, _reply("Готово: https://app.example/e/1"), strip_cjk=False)
    assert kept is not None and kept.answer == "Готово: https://app.example/e/1"
    assert accept_rewrite(original, _reply("   "), strip_cjk=False) is None


def test_only_the_answer_reaches_the_person_and_the_critique_is_kept_apart():
    content = (
        "<changes>\n- перевёл «rooms»\n- убрал edit_estimate\n</changes>\n"
        "<answer>\nСмета пересчитана по тем же комнатам.\n</answer>"
    )
    rewrite = accept_rewrite("Смета пересчитана по rooms", content, strip_cjk=False)
    assert rewrite is not None
    assert rewrite.answer == "Смета пересчитана по тем же комнатам."
    assert "edit_estimate" in rewrite.changes
    assert "Что не так" not in rewrite.answer  # noqa: RUF001


@pytest.mark.parametrize(
    "content",
    [
        "Что не так: english «rooms».\n\nОтвет:\nСмета пересчитана.",  # noqa: RUF001
        "<answer>Смета пересчитана.",
        "<answer>Первый</answer><answer>Второй</answer>",
        None,
    ],
)
def test_a_reply_without_exactly_one_closed_answer_block_is_refused(content):
    assert accept_rewrite("Смета пересчитана по rooms", content, strip_cjk=False) is None


def test_the_cjk_floor_applies_to_the_parsed_answer():
    rewrite = accept_rewrite("最需要 размеры", _reply("Уточните 最 размеры"), strip_cjk=True)
    assert rewrite is not None and rewrite.answer == "Уточните размеры"


def test_the_rewrite_names_what_is_wrong_and_takes_an_instruction():
    leaks = find_leaks("по этим rooms", [], "ru")
    messages = rewrite_messages("по этим rooms", leaks, "ru", "Свой промпт")
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith("Свой промпт")
    # A custom instruction still gets the reply format the parser reads.
    assert "<answer>" in messages[0]["content"]
    assert "english «rooms»" in messages[1]["content"]
    assert "<answer>\nпо этим rooms\n</answer>" in messages[1]["content"]


def test_the_check_is_off_unless_the_policy_or_the_agent_turns_it_on():
    assert answer_check_config(None, None) is None
    assert answer_check_config({"content_safety": {"output_sanitizer_enabled": True}}, None) is None
    off = {"content_safety": {"answer_check": {"enabled": False}}}
    assert answer_check_config(off, None) is None
    on = {"content_safety": {"answer_check": {"enabled": True, "language": "ru"}}}
    assert answer_check_config(on, None) == {"enabled": True, "language": "ru"}


def test_the_agent_setting_turns_the_check_on_when_no_rule_sets_it():
    agent = {"enabled": True, "language": "en"}
    assert answer_check_config(None, agent) == agent
    assert answer_check_config({"content_safety": {}}, agent) == agent
    assert answer_check_config(None, {"enabled": False, "language": "ru"}) is None


def test_a_governance_rule_overrides_the_agent_setting_either_way():
    agent_on = {"enabled": True, "language": "en"}
    rule_off = {"content_safety": {"answer_check": {"enabled": False}}}
    assert answer_check_config(rule_off, agent_on) is None
    rule_on = {"content_safety": {"answer_check": {"enabled": True, "language": "ru"}}}
    assert answer_check_config(rule_on, {"enabled": False}) == {"enabled": True, "language": "ru"}
    assert answer_check_config(rule_on, agent_on) == {"enabled": True, "language": "ru"}
