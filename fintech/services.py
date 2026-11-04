"""Бизнес-логика электронного кошелька: клиенты, счета, операции.

Правила (упрощённая модель требований банка):
* суммы > 0, баланс не может стать отрицательным;
* суточный лимит расходных операций по счёту — DAILY_LIMIT;
* операции на сумму от REVIEW_THRESHOLD (600 000 ₽, порог обязательного
  контроля по 115-ФЗ) не проводятся сразу, а уходят на проверку (ON_REVIEW);
* повтор запроса с тем же ключом идемпотентности не создаёт вторую операцию;
* после MAX_FAILED_LOGINS неудачных входов клиент блокируется;
* все значимые действия пишутся в журнал аудита (номера счетов — в маске).
"""
from dataclasses import dataclass

from . import security
from .money import positive_kopecks
from .storage import Database

BANK_BIK = "044525225"            # учебный БИК для генерации номеров
ACCOUNT_PREFIX = "40817810"       # счёт физлица, рубли
DAILY_LIMIT = 100_000_000         # 1 000 000.00 ₽ в копейках
REVIEW_THRESHOLD = 60_000_000     # 600 000.00 ₽ в копейках


class OperationError(Exception):
    """Операция отклонена по бизнес-правилам."""


class AuthError(Exception):
    """Ошибка аутентификации."""


@dataclass
class Result:
    tx_id: int
    status: str
    reason: str | None = None


class WalletService:
    def __init__(self, db: Database | None = None):
        self.db = db or Database()

    # ---------- клиенты ----------
    def register(self, login: str, full_name: str, password: str) -> int:
        login = login.strip().lower()
        if not login or not full_name.strip():
            raise OperationError("Логин и ФИО обязательны")
        if self.db.one("SELECT 1 FROM clients WHERE login=?", (login,)):
            raise OperationError("Логин уже занят")
        pwd = security.hash_password(password)
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT INTO clients(login, full_name, password_hash) VALUES (?,?,?)",
                (login, full_name.strip(), pwd),
            )
            self._audit(c, cur.lastrowid, "REGISTER", login)
        return cur.lastrowid

    def login(self, login: str, password: str) -> int:
        row = self.db.one("SELECT * FROM clients WHERE login=?", (login.strip().lower(),))
        if row is None:
            raise AuthError("Неверный логин или пароль")
        if row["blocked"]:
            raise AuthError("Учётная запись заблокирована")
        with self.db.transaction() as c:
            if security.verify_password(password, row["password_hash"]):
                c.execute("UPDATE clients SET failed_logins=0 WHERE id=?", (row["id"],))
                self._audit(c, row["id"], "LOGIN_OK")
                return row["id"]
            failed = row["failed_logins"] + 1
            blocked = int(failed >= security.MAX_FAILED_LOGINS)
            c.execute("UPDATE clients SET failed_logins=?, blocked=? WHERE id=?", (failed, blocked, row["id"]))
            self._audit(c, row["id"], "LOGIN_FAIL", f"attempt={failed}")
        raise AuthError("Учётная запись заблокирована" if blocked else "Неверный логин или пароль")

    # ---------- счета ----------
    def open_account(self, client_id: int) -> str:
        with self.db.transaction() as c:
            serial = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] + 1
            number = security.make_account_number(BANK_BIK, ACCOUNT_PREFIX, serial)
            c.execute("INSERT INTO accounts(number, client_id) VALUES (?,?)", (number, client_id))
            self._audit(c, client_id, "OPEN_ACCOUNT", security.mask_account(number))
        return number

    def balance(self, client_id: int, number: str) -> int:
        return self._own_account(client_id, number)["balance"]

    def accounts(self, client_id: int):
        return [dict(r) for r in self.db.query(
            "SELECT number, balance, currency, status FROM accounts WHERE client_id=?", (client_id,))]

    def history(self, client_id: int, number: str, limit: int = 50):
        self._own_account(client_id, number)
        rows = self.db.query(
            "SELECT * FROM transactions WHERE from_account=? OR to_account=? ORDER BY id DESC LIMIT ?",
            (number, number, limit))
        return [dict(r) for r in rows]

    # ---------- операции ----------
    def deposit(self, client_id: int, number: str, amount, key: str | None = None) -> Result:
        kop = positive_kopecks(amount)
        self._own_account(client_id, number)
        if (dup := self._find_idempotent(key)):
            return dup
        with self.db.transaction() as c:
            self._check_open(c, number)
            c.execute("UPDATE accounts SET balance = balance + ? WHERE number=?", (kop, number))
            tx = self._tx(c, key, "DEPOSIT", None, number, kop, "DONE")
            self._audit(c, client_id, "DEPOSIT", f"{security.mask_account(number)} {kop}")
        return Result(tx, "DONE")

    def withdraw(self, client_id: int, number: str, amount, key: str | None = None) -> Result:
        return self._debit(client_id, number, None, amount, key, "WITHDRAW")

    def transfer(self, client_id: int, src: str, dst: str, amount, key: str | None = None) -> Result:
        if src == dst:
            raise OperationError("Счёт списания и зачисления совпадают")
        if not security.account_control_ok(BANK_BIK, dst):
            raise OperationError("Некорректный номер счёта получателя (контрольный ключ)")
        return self._debit(client_id, src, dst, amount, key, "TRANSFER")

    def approve_review(self, tx_id: int, approve: bool) -> Result:
        """Решение офицера финмониторинга по операции на проверке."""
        with self.db.transaction() as c:
            tx = c.execute("SELECT * FROM transactions WHERE id=? AND status='ON_REVIEW'", (tx_id,)).fetchone()
            if tx is None:
                raise OperationError("Операция не найдена или уже обработана")
            if not approve:
                c.execute("UPDATE transactions SET status='REJECTED', reason=? WHERE id=?",
                          ("Отклонено финмониторингом", tx_id))
                return Result(tx_id, "REJECTED", "Отклонено финмониторингом")
            self._move(c, tx["from_account"], tx["to_account"], tx["amount"])
            c.execute("UPDATE transactions SET status='DONE', reason=NULL WHERE id=?", (tx_id,))
            self._audit(c, None, "REVIEW_APPROVED", str(tx_id))
        return Result(tx_id, "DONE")

    # ---------- внутреннее ----------
    def _debit(self, client_id, src, dst, amount, key, kind) -> Result:
        kop = positive_kopecks(amount)
        self._own_account(client_id, src)
        if (dup := self._find_idempotent(key)):
            return dup
        with self.db.transaction() as c:
            self._check_open(c, src)
            if dst:
                self._check_open(c, dst)
            spent = c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE from_account=? "
                "AND status IN ('DONE','ON_REVIEW') AND date(created_at)=date('now')", (src,)).fetchone()[0]
            if spent + kop > DAILY_LIMIT:
                tx = self._tx(c, key, kind, src, dst, kop, "REJECTED", "Превышен суточный лимит")
                return Result(tx, "REJECTED", "Превышен суточный лимит")
            bal = c.execute("SELECT balance FROM accounts WHERE number=?", (src,)).fetchone()[0]
            if bal < kop:
                tx = self._tx(c, key, kind, src, dst, kop, "REJECTED", "Недостаточно средств")
                return Result(tx, "REJECTED", "Недостаточно средств")
            if kop >= REVIEW_THRESHOLD:
                tx = self._tx(c, key, kind, src, dst, kop, "ON_REVIEW", "Обязательный контроль (115-ФЗ)")
                self._audit(c, client_id, "ON_REVIEW", str(tx))
                return Result(tx, "ON_REVIEW", "Обязательный контроль (115-ФЗ)")
            self._move(c, src, dst, kop)
            tx = self._tx(c, key, kind, src, dst, kop, "DONE")
            self._audit(c, client_id, kind, f"{security.mask_account(src)} {kop}")
        return Result(tx, "DONE")

    @staticmethod
    def _move(c, src, dst, kop):
        cur = c.execute("UPDATE accounts SET balance = balance - ? WHERE number=? AND balance >= ?", (kop, src, kop))
        if cur.rowcount != 1:
            raise OperationError("Недостаточно средств")
        if dst:
            c.execute("UPDATE accounts SET balance = balance + ? WHERE number=?", (kop, dst))

    def _own_account(self, client_id, number):
        row = self.db.one("SELECT * FROM accounts WHERE number=?", (number,))
        if row is None or row["client_id"] != client_id:
            raise OperationError("Счёт не найден")
        return row

    @staticmethod
    def _check_open(c, number):
        row = c.execute("SELECT status FROM accounts WHERE number=?", (number,)).fetchone()
        if row is None:
            raise OperationError("Счёт получателя не найден")
        if row[0] != "OPEN":
            raise OperationError(f"Счёт в статусе {row[0]}, операции запрещены")

    def _find_idempotent(self, key):
        if not key:
            return None
        row = self.db.one("SELECT id, status, reason FROM transactions WHERE idempotency_key=?", (key,))
        return Result(row["id"], row["status"], row["reason"]) if row else None

    @staticmethod
    def _tx(c, key, kind, src, dst, kop, status, reason=None) -> int:
        return c.execute(
            "INSERT INTO transactions(idempotency_key, kind, from_account, to_account, amount, status, reason) "
            "VALUES (?,?,?,?,?,?,?)", (key, kind, src, dst, kop, status, reason)).lastrowid

    @staticmethod
    def _audit(c, client_id, action, details=None):
        c.execute("INSERT INTO audit_log(client_id, action, details) VALUES (?,?,?)", (client_id, action, details))
