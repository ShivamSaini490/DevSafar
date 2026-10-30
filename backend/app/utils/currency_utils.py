
from collections.abc import Iterable
from decimal import Decimal


def sum_known_amounts(amounts: Iterable[Decimal | None]) -> Decimal:
    return sum((amount for amount in amounts if amount is not None), Decimal("0"))


def all_amounts_known(amounts: Iterable[Decimal | None]) -> bool:
    return all(amount is not None for amount in amounts)
