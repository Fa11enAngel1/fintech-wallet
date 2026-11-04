"""Работа с денежными суммами.

Все суммы хранятся в копейках (int), а на входе/выходе представляются
как Decimal с точностью до 0.01. Тип float для денег не используется,
чтобы исключить ошибки округления двоичной арифметики.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENT = Decimal("0.01")


class MoneyError(ValueError):
    """Некорректная денежная сумма."""


def to_decimal(value) -> Decimal:
    """Преобразует строку/число в Decimal с округлением до копеек."""
    if isinstance(value, float):
        value = repr(value)
    try:
        amount = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise MoneyError(f"Некорректная сумма: {value!r}") from exc
    if not amount.is_finite():
        raise MoneyError("Сумма должна быть конечным числом")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def to_kopecks(value) -> int:
    """Сумма в рублях -> целое число копеек."""
    return int(to_decimal(value) * 100)


def from_kopecks(kopecks: int) -> Decimal:
    """Целое число копеек -> Decimal в рублях."""
    return (Decimal(kopecks) / 100).quantize(CENT)


def positive_kopecks(value) -> int:
    """Возвращает сумму в копейках, требуя, чтобы она была > 0."""
    kopecks = to_kopecks(value)
    if kopecks <= 0:
        raise MoneyError("Сумма операции должна быть больше нуля")
    return kopecks


def fmt(kopecks: int) -> str:
    """Форматирование для вывода: 1 234 567.89 ₽"""
    rub = from_kopecks(kopecks)
    sign = "-" if rub < 0 else ""
    integer, frac = f"{abs(rub):.2f}".split(".")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}{' '.join(groups)}.{frac} ₽"
