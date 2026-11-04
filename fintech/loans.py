"""Кредитный калькулятор: аннуитетный и дифференцированный график платежей.

Проценты начисляются помесячно по ставке r = годовая_ставка / 12.
Последний платёж корректируется так, чтобы остаток долга стал ровно 0
(устраняется накопленная ошибка округления).
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .money import CENT, MoneyError, to_decimal


@dataclass(frozen=True)
class Payment:
    number: int
    payment: Decimal
    principal: Decimal
    interest: Decimal
    balance: Decimal


@dataclass(frozen=True)
class Schedule:
    kind: str
    payments: list[Payment]

    @property
    def total_paid(self) -> Decimal:
        return sum((p.payment for p in self.payments), Decimal("0.00"))

    @property
    def overpayment(self) -> Decimal:
        return sum((p.interest for p in self.payments), Decimal("0.00"))


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _validate(amount, annual_rate, months):
    amount = to_decimal(amount)
    rate = Decimal(str(annual_rate))
    if amount <= 0:
        raise MoneyError("Сумма кредита должна быть больше нуля")
    if not 0 <= rate <= 100:
        raise MoneyError("Ставка должна быть в диапазоне 0..100 % годовых")
    if not isinstance(months, int) or not 1 <= months <= 600:
        raise MoneyError("Срок кредита — от 1 до 600 месяцев")
    return amount, rate / 100 / 12


def annuity(amount, annual_rate, months: int) -> Schedule:
    principal, r = _validate(amount, annual_rate, months)
    if r == 0:
        pay = _q(principal / months)
    else:
        pay = _q(principal * r / (1 - (1 + r) ** -months))
    balance = principal
    rows = []
    for n in range(1, months + 1):
        interest = _q(balance * r)
        body = pay - interest
        if n == months:  # закрываем остаток
            body = balance
        balance = _q(balance - body)
        rows.append(Payment(n, body + interest, body, interest, balance))
    return Schedule("annuity", rows)


def differentiated(amount, annual_rate, months: int) -> Schedule:
    principal, r = _validate(amount, annual_rate, months)
    body = _q(principal / months)
    balance = principal
    rows = []
    for n in range(1, months + 1):
        interest = _q(balance * r)
        part = balance if n == months else body
        balance = _q(balance - part)
        rows.append(Payment(n, part + interest, part, interest, balance))
    return Schedule("differentiated", rows)
