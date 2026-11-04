"""Простой нагрузочный замер: сколько переводов в секунду выдерживает сервис."""
import time

from fintech.services import WalletService
from fintech.storage import Database


def main(n: int = 5000, path: str = ":memory:"):
    svc = WalletService(Database(path))
    a = svc.register("load_a", "Нагрузка А", "password1")
    b = svc.register("load_b", "Нагрузка Б", "password2")
    acc_a, acc_b = svc.open_account(a), svc.open_account(b)
    svc.deposit(a, acc_a, "900000")
    start = time.perf_counter()
    for i in range(n):
        svc.transfer(a, acc_a, acc_b, "1", key=f"bench-{i}")
    dt = time.perf_counter() - start
    print(f"{n} переводов за {dt:.2f} с — {n / dt:.0f} оп/с, {dt / n * 1000:.2f} мс на операцию")


if __name__ == "__main__":
    main()
