def format_cents(cents: int) -> str:
    # Planted bug: 1205 cents prints as "$12.5" instead of "$12.05".
    return f"${cents // 100}.{cents % 100}"


def add_tax(cents: int, rate: float) -> int:
    return round(cents * (1 + rate))
