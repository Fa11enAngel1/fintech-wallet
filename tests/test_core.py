from decimal import Decimal

import pytest

from fintech import security
from fintech.loans import annuity, differentiated
from fintech.money import MoneyError, fmt, positive_kopecks, to_kopecks
from fintech.services import AuthError, OperationError, WalletService


# ---------- деньги ----------
@pytest.mark.parametrize("raw,expected", [("100", 10000), ("0.1", 10), ("10,555", 1056), (0.1 + 0.2, 30)])
def test_to_kopecks(raw, expected):
    assert to_kopecks(raw) == expected


@pytest.mark.parametrize("bad", ["abc", "", "NaN", "inf", None])
def test_bad_money(bad):
    with pytest.raises(MoneyError):
        to_kopecks(bad)


@pytest.mark.parametrize("bad", ["0", "-5", "0.001"])
def test_non_positive(bad):
    with pytest.raises(MoneyError):
        positive_kopecks(bad)


def test_fmt():
    assert fmt(123456789) == "1 234 567.89 ₽"


# ---------- безопасность ----------
def test_password_hash_roundtrip():
    h = security.hash_password("Secret123")
    assert "Secret123" not in h
    assert security.verify_password("Secret123", h)
    assert not security.verify_password("secret123", h)


def test_short_password():
    with pytest.raises(ValueError):
        security.hash_password("1234567")


def test_account_number_control_key():
    for serial in range(1, 50):
        n = security.make_account_number("044525225", "40817810", serial)
        assert len(n) == 20 and security.account_control_ok("044525225", n)
    n = security.make_account_number("044525225", "40817810", 7)
    broken = n[:-1] + str((int(n[-1]) + 1) % 10)
    assert not security.account_control_ok("044525225", broken)


def test_mask():
    assert security.mask_account("40817810000000001234") == "4081 **** **** 1234"


# ---------- кредиты ----------
def test_annuity_known_value():
    s = annuity(100000, 12, 12)
    assert s.payments[0].payment == Decimal("8884.88")
    assert s.payments[-1].balance == Decimal("0.00")
    assert sum(p.principal for p in s.payments) == Decimal("100000.00")


def test_differentiated_decreasing():
    s = differentiated(120000, 12, 12)
    pays = [p.payment for p in s.payments]
    assert pays == sorted(pays, reverse=True)
    assert s.payments[0].payment == Decimal("11200.00")
    assert s.overpayment < annuity(120000, 12, 12).overpayment


def test_zero_rate():
    s = annuity(1200, 0, 12)
    assert all(p.payment == Decimal("100.00") for p in s.payments)


@pytest.mark.parametrize("args", [(0, 10, 12), (1000, -1, 12), (1000, 10, 0), (1000, 10, 601)])
def test_loan_validation(args):
    with pytest.raises(MoneyError):
        annuity(*args)


# ---------- сервис ----------
@pytest.fixture
def svc():
    return WalletService()


@pytest.fixture
def two_accounts(svc):
    a = svc.register("ivan", "Иванов Иван", "password1")
    b = svc.register("petr", "Петров Пётр", "password2")
    acc_a, acc_b = svc.open_account(a), svc.open_account(b)
    svc.deposit(a, acc_a, "1000")
    return a, b, acc_a, acc_b


def test_transfer_ok(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    r = svc.transfer(a, acc_a, acc_b, "250.50")
    assert r.status == "DONE"
    assert svc.balance(a, acc_a) == 74950
    assert svc.balance(b, acc_b) == 25050


def test_insufficient_funds(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    r = svc.transfer(a, acc_a, acc_b, "1000.01")
    assert r.status == "REJECTED" and svc.balance(a, acc_a) == 100000


def test_cannot_use_foreign_account(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    with pytest.raises(OperationError):
        svc.withdraw(b, acc_a, "1")


def test_idempotency(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    r1 = svc.transfer(a, acc_a, acc_b, "100", key="k-1")
    r2 = svc.transfer(a, acc_a, acc_b, "100", key="k-1")
    assert r1.tx_id == r2.tx_id
    assert svc.balance(b, acc_b) == 10000


def test_review_threshold(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    svc.deposit(a, acc_a, "700000")
    r = svc.transfer(a, acc_a, acc_b, "600000")
    assert r.status == "ON_REVIEW" and svc.balance(b, acc_b) == 0
    assert svc.approve_review(r.tx_id, True).status == "DONE"
    assert svc.balance(b, acc_b) == 60_000_000


def test_daily_limit(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    svc.deposit(a, acc_a, "2000000")
    for _ in range(2):
        assert svc.transfer(a, acc_a, acc_b, "500000").status == "DONE"
    r = svc.transfer(a, acc_a, acc_b, "1")
    assert r.status == "REJECTED" and "лимит" in r.reason


def test_bad_recipient_number(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    with pytest.raises(OperationError):
        svc.transfer(a, acc_a, "40817810000000000000", "1")


def test_login_lockout(svc):
    svc.register("anna", "Анна", "goodpass1")
    for _ in range(3):
        with pytest.raises(AuthError):
            svc.login("anna", "wrong")
    with pytest.raises(AuthError, match="заблокирована"):
        svc.login("anna", "goodpass1")


def test_audit_has_no_full_account_numbers(svc, two_accounts):
    a, b, acc_a, acc_b = two_accounts
    svc.transfer(a, acc_a, acc_b, "1")
    details = " ".join(r["details"] or "" for r in svc.db.query("SELECT details FROM audit_log"))
    assert acc_a not in details and acc_b not in details
