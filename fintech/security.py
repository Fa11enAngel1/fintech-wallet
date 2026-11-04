"""Функции безопасности: хеширование паролей, маскирование, проверка номера счёта."""
import hashlib
import hmac
import re
import secrets

PBKDF2_ITERATIONS = 200_000
MAX_FAILED_LOGINS = 3


def hash_password(password: str, salt: bytes | None = None) -> str:
    """PBKDF2-HMAC-SHA256 с солью. Пароль в открытом виде не хранится."""
    if len(password) < 8:
        raise ValueError("Пароль должен содержать не менее 8 символов")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Проверка пароля с защитой от атак по времени (compare_digest)."""
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def mask_account(number: str) -> str:
    """40817810000000001234 -> 4081 **** **** 1234 (для логов и интерфейса)."""
    return f"{number[:4]} **** **** {number[-4:]}"


# Весовые коэффициенты для расчёта контрольного ключа счёта (Положение Банка России № 579-П)
_WEIGHTS = ([7, 1, 3] * 8)[:23]


def account_control_ok(bik: str, account: str) -> bool:
    """Проверка контрольного разряда 20-значного счёта по БИК.

    Берутся 3 последние цифры БИК + 20 цифр счёта, перемножаются на веса
    7-1-3, сумма младших разрядов произведений должна оканчиваться на 0.
    """
    if not re.fullmatch(r"\d{9}", bik) or not re.fullmatch(r"\d{20}", account):
        return False
    digits = bik[-3:] + account
    total = sum((int(d) * w) % 10 for d, w in zip(digits, _WEIGHTS))
    return total % 10 == 0


def make_account_number(bik: str, prefix: str, serial: int) -> str:
    """Генерирует 20-значный номер счёта с корректным контрольным ключом.

    prefix — балансовый счёт 2-го порядка + код валюты (8 цифр, например 40817810),
    9-я цифра — контрольный ключ, далее 11 цифр порядкового номера.
    """
    body = f"{prefix}0{serial:011d}"
    digits = bik[-3:] + body
    total = sum((int(d) * w) % 10 for d, w in zip(digits, _WEIGHTS))
    key = ((total % 10) * 3) % 10
    return body[:8] + str(key) + body[9:]
