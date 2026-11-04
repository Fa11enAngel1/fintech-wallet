# Архитектура FinWallet

```
Браузер (index.html, fetch)
        │  JSON / HTTPS
        ▼
web.py      Flask: маршруты, сессии, заголовки безопасности, коды ответов
        │
services.py WalletService: правила, лимиты, идемпотентность, аудит
        │            ├── loans.py     кредитный калькулятор
        │            ├── security.py  пароли, маски, контрольный ключ
        │            └── money.py     Decimal / копейки
        ▼
storage.py  SQLite: clients, accounts, transactions, audit_log
```

Слои зависят только сверху вниз, бизнес-логика не знает про HTTP и тестируется без веб-сервера.

## Схема данных

* `clients(id, login, full_name, password_hash, failed_logins, blocked)`
* `accounts(number PK, client_id FK, balance ≥ 0, currency, status)`
* `transactions(id, idempotency_key UNIQUE, kind, from_account, to_account, amount > 0, status, reason)`
* `audit_log(id, client_id, action, details)`

## Ключевые решения

| Решение | Почему |
|---|---|
| Суммы в копейках (`INTEGER`) | нет ошибок округления, простые CHECK-ограничения |
| `BEGIN IMMEDIATE` на каждую операцию | атомарность и отсутствие гонок при одновременных списаниях |
| Уникальный `idempotency_key` | защита от двойного платежа при повторе запроса |
| PBKDF2-SHA256, 200 000 итераций | стойкость к перебору, только стандартная библиотека |
| SQLite | прототип без внешних зависимостей; замена на PostgreSQL — через слой storage |

## План тестирования

1. Модульные тесты: деньги, кредиты, безопасность (граничные значения, ошибки ввода).
2. Тесты бизнес-правил: перевод, нехватка средств, чужой счёт, лимит, 115-ФЗ, блокировка входа, идемпотентность.
3. API-тесты: авторизация, коды ответов, заголовки безопасности.
4. Нагрузочный замер `bench.py`.
5. CI: тесты на каждый push (GitHub Actions).
