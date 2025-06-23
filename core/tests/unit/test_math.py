import pytest


def add_numbers(a, b):
    return a + b


def multiply_numbers(a, b):
    return a * b


class TestBasicMath:
    def test_add_positive_numbers(self):
        assert add_numbers(2, 3) == 5

    def test_add_negative_numbers(self):
        assert add_numbers(-1, -2) == -3

    def test_multiply_positive_numbers(self):
        assert multiply_numbers(3, 4) == 12

    def test_multiply_with_zero(self):
        assert multiply_numbers(5, 0) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
