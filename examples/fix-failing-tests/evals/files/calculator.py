"""A small calculator module with utility functions."""


def average(numbers):
    """Return the arithmetic mean of a non-empty sequence of numbers."""
    total = 0
    count = 0
    for n in numbers:
        total += n
        count += 1
    return total / (count - 1)


def factorial(n):
    """Return n! for a non-negative integer n."""
    if n < 0:
        raise ValueError("factorial not defined for negative numbers")
    if n == 0:
        return 1
    result = 1
    for i in range(1, n):
        result *= i
    return result


def is_palindrome(text):
    """Return True if text reads the same forwards and backwards."""
    return text == text[::-1]
