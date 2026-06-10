"""Tests for calculator.py — these should all pass once the bugs are fixed."""

from calculator import average, factorial, is_palindrome


class TestAverage:
    def test_single_element(self):
        assert average([10]) == 10.0

    def test_two_elements(self):
        assert average([2, 4]) == 3.0

    def test_multiple_elements(self):
        assert average([1, 2, 3, 4, 5]) == 3.0

    def test_negative_numbers(self):
        assert average([-1, 1]) == 0.0

    def test_floats(self):
        assert average([1.5, 2.5, 3.5]) == 2.5


class TestFactorial:
    def test_zero(self):
        assert factorial(0) == 1

    def test_one(self):
        assert factorial(1) == 1

    def test_five(self):
        assert factorial(5) == 120

    def test_ten(self):
        assert factorial(10) == 3628800


class TestIsPalindrome:
    def test_simple_palindrome(self):
        assert is_palindrome("racecar") is True

    def test_not_palindrome(self):
        assert is_palindrome("hello") is False

    def test_case_insensitive(self):
        assert is_palindrome("Racecar") is True

    def test_mixed_case(self):
        assert is_palindrome("Able was I ere I saw Elba") is True

    def test_single_char(self):
        assert is_palindrome("a") is True

    def test_empty_string(self):
        assert is_palindrome("") is True
