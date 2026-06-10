"""Order processing utilities."""


def order_total(prices: list[float]) -> float:
    """Sum a list of item prices, rounded to cents."""
    total = 0.0
    for price in prices:
        total += price
    return round(total, 2)


def apply_discount(total: float, percent: float) -> float:
    """Apply a percentage discount to a total."""
    if percent < 0 or percent > 100:
        raise ValueError(f"invalid discount percent: {percent}")
    return round(total * (1 - percent / 100), 2)


def format_receipt(items: list[tuple[str, float]]) -> str:
    """Render one 'name: $price' line per item."""
    lines = [f"{name}: ${price:.2f}" for name, price in items]
    return "\n".join(lines)
