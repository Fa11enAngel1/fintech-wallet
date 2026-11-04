"""REST API и веб-интерфейс электронного кошелька (Flask)."""
import os
from functools import wraps

from flask import Flask, jsonify, render_template, request, session

from .loans import annuity, differentiated
from .money import MoneyError, from_kopecks
from .services import AuthError, OperationError, WalletService
from .storage import Database


def create_app(db_path: str | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or os.urandom(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=not testing,
        TESTING=testing,
    )
    service = WalletService(Database(db_path or os.environ.get("WALLET_DB", "wallet.db")))
    app.extensions["wallet"] = service

    def auth_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "client_id" not in session:
                return jsonify(error="Требуется вход"), 401
            return fn(session["client_id"], *args, **kwargs)
        return wrapper

    @app.errorhandler(OperationError)
    @app.errorhandler(MoneyError)
    def business_error(exc):
        return jsonify(error=str(exc)), 422

    @app.errorhandler(AuthError)
    def auth_error(exc):
        return jsonify(error=str(exc)), 401

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        return resp

    def body():
        return request.get_json(silent=True) or {}

    def money_json(r):
        return {**r, "balance": str(from_kopecks(r["balance"]))} if "balance" in r else r

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/register")
    def register():
        d = body()
        cid = service.register(d.get("login", ""), d.get("full_name", ""), d.get("password", ""))
        return jsonify(client_id=cid), 201

    @app.post("/api/login")
    def login():
        d = body()
        session.clear()
        session["client_id"] = service.login(d.get("login", ""), d.get("password", ""))
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/accounts")
    @auth_required
    def accounts(cid):
        return jsonify([money_json(a) for a in service.accounts(cid)])

    @app.post("/api/accounts")
    @auth_required
    def open_account(cid):
        return jsonify(number=service.open_account(cid)), 201

    @app.get("/api/accounts/<number>/history")
    @auth_required
    def history(cid, number):
        rows = service.history(cid, number)
        for r in rows:
            r["amount"] = str(from_kopecks(r["amount"]))
        return jsonify(rows)

    def op_response(res):
        code = {"DONE": 200, "ON_REVIEW": 202}.get(res.status, 422)
        return jsonify(tx_id=res.tx_id, status=res.status, reason=res.reason), code

    @app.post("/api/accounts/<number>/deposit")
    @auth_required
    def deposit(cid, number):
        return op_response(service.deposit(cid, number, body().get("amount"), request.headers.get("Idempotency-Key")))

    @app.post("/api/accounts/<number>/withdraw")
    @auth_required
    def withdraw(cid, number):
        return op_response(service.withdraw(cid, number, body().get("amount"), request.headers.get("Idempotency-Key")))

    @app.post("/api/transfers")
    @auth_required
    def transfer(cid):
        d = body()
        return op_response(service.transfer(cid, d.get("from", ""), d.get("to", ""), d.get("amount"),
                                            request.headers.get("Idempotency-Key")))

    @app.get("/api/loan")
    def loan():
        try:
            months = int(request.args.get("months", "12"))
        except ValueError:
            raise MoneyError("Срок должен быть целым числом")
        kind = request.args.get("kind", "annuity")
        calc = differentiated if kind == "differentiated" else annuity
        sch = calc(request.args.get("amount", "0"), request.args.get("rate", "0"), months)
        return jsonify(
            kind=sch.kind, total=str(sch.total_paid), overpayment=str(sch.overpayment),
            payments=[{"n": p.number, "payment": str(p.payment), "principal": str(p.principal),
                       "interest": str(p.interest), "balance": str(p.balance)} for p in sch.payments])

    return app


if __name__ == "__main__":  # pragma: no cover
    create_app(testing=True).run(debug=False, port=5000)
