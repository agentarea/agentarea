"""Unit tests for slug utility (workspace-scoped immutable slugs)."""

import pytest
from agentarea_common.utils.slug import ensure_unique_slug, generate_slug


class TestGenerateSlug:
    def test_basic_lowercases_and_hyphenates(self):
        assert generate_slug("My Agent") == "my-agent"

    def test_strips_special_characters(self):
        assert generate_slug("Hello, World!") == "hello-world"

    def test_collapses_repeating_separators(self):
        assert generate_slug("a  b___c---d") == "a-b-c-d"

    def test_strips_leading_and_trailing_hyphens(self):
        assert generate_slug("---foo bar---") == "foo-bar"

    def test_unicode_transliterates_to_ascii(self):
        # Combining accents are stripped by NFKD + ASCII encode
        assert generate_slug("Café") == "cafe"
        # Cyrillic falls through entirely (no ASCII equivalent)
        # so it must NOT crash and must produce the fallback for empty result
        assert generate_slug("Привет") == "item"

    def test_empty_string_returns_item(self):
        assert generate_slug("") == "item"

    def test_only_special_chars_returns_item(self):
        assert generate_slug("!!!---???") == "item"

    def test_only_emoji_returns_item(self):
        assert generate_slug("\U0001f600\U0001f600\U0001f600") == "item"

    def test_truncates_to_100_chars(self):
        long = "a" * 250
        result = generate_slug(long)
        assert len(result) <= 100
        assert result == "a" * 100

    def test_truncation_does_not_leave_trailing_hyphen(self):
        # 99 'a's, then a hyphen, then a 'b' -> after truncation to 100 the
        # last char is the hyphen which must be stripped.
        name = ("a" * 99) + " b"
        result = generate_slug(name)
        assert not result.endswith("-")
        assert len(result) <= 100

    def test_digits_are_preserved(self):
        assert generate_slug("agent 42 v2") == "agent-42-v2"


class TestEnsureUniqueSlug:
    def test_returns_base_when_no_collision(self):
        existing: set[str] = set()
        result = ensure_unique_slug("foo", lambda s: s in existing)
        assert result == "foo"

    def test_appends_suffix_on_collision(self):
        existing = {"foo"}
        result = ensure_unique_slug("foo", lambda s: s in existing)
        assert result == "foo-2"

    def test_increments_until_unique(self):
        existing = {"foo", "foo-2", "foo-3"}
        result = ensure_unique_slug("foo", lambda s: s in existing)
        assert result == "foo-4"

    def test_raises_when_exhausted(self):
        # Pretend everything up to and including foo-999 is taken
        taken = {"foo"} | {f"foo-{i}" for i in range(2, 1000)}
        with pytest.raises(ValueError):
            ensure_unique_slug("foo", lambda s: s in taken)
