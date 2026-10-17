#!/usr/bin/env python3
"""Simple Flask demo bank with login (session-based) and SQLite storage.

This is a demo scaffold for local development. It seeds an admin user and a "Big Balance Demo" account.
"""
import os
import sqlite3
from contextlib import closing
from functools import wraps
from flask import Flask, request, jsonify, session, g
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.environ.get("DB_PATH", "bank_demo.db")
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY") or "dev-secret-change-me"

app = Flask(__name__, static_folder="../frontend", static_url_path="")
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

def get_db():
    if hasattr(g, "db") and g.db:
        return g.db
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    g.db = conn
    return conn

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "db", None)
    if db:
        db.close()

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            balance_cents INTEGER NOT NULL DEFAULT 0 CHECK(balance_cents >= 0),
            FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            related_account INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );
        ''')
        cur = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",))
        if cur.fetchone() is None:
            pw_hash = generate_password_hash("adminpass")
            conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                         ("admin", pw_hash))
            admin_id = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()[0]
            big_cents = 100_000_000_000 * 100
            conn.execute("INSERT INTO accounts (owner_user_id, name, balance_cents) VALUES (?, ?, ?)",
                         (admin_id, "Big Balance Demo", big_cents))
        conn.commit()

# Authentication helpers
def login_user(user_id):
    session.clear()
    session["user_id"] = user_id

def logout_user():
    session.clear()

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_db()
    row = db.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper

# Routes
@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    db = get_db()
    try:
        pw_hash = generate_password_hash(password)
        cur = db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, pw_hash),
        )
        db.commit()
        user_id = cur.lastrowid
        login_user(user_id)
        return jsonify({"status": "ok", "user": {"id": user_id, "username": username}}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "username already exists"}), 400

@app.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    db = get_db()
    row = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "invalid credentials"}), 401

    login_user(row["id"])
    return jsonify({"status": "ok", "user": {"id": row["id"], "username": username}})

@app.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify({"status": "ok"})

@app.get("/me")
@login_required
def me():
    user = current_user()
    return jsonify({"user": user})

# Account endpoints
@app.get("/accounts")
@login_required
def list_accounts():
    user = current_user()
    db = get_db()
    rows = db.execute(
        "SELECT id, name, balance_cents FROM accounts WHERE owner_user_id = ? ORDER BY id",
        (user["id"],)
    ).fetchall()
    return jsonify({
        "accounts": [
            {"id": r["id"], "name": r["name"], "balance_cents": r["balance_cents"],
             "balance_usd": f"${r['balance_cents']/100:.2f}"}
            for r in rows
        ]
    })

@app.post("/accounts")
@login_required
def create_account():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    initial_cents = data.get("initial_balance_cents", 0)
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not isinstance(initial_cents, int) or initial_cents < 0:
        return jsonify({"error": "initial_balance_cents must be a non-negative integer"}), 400

    user = current_user()
    db = get_db()
    cur = db.execute(
        "INSERT INTO accounts (owner_user_id, name, balance_cents) VALUES (?, ?, ?)",
        (user["id"], name, initial_cents)
    )
    db.commit()
    account_id = cur.lastrowid
    if initial_cents > 0:
        db.execute(
            "INSERT INTO transactions (account_id, type, amount_cents) VALUES (?, ?, ?)",
            (account_id, "deposit", initial_cents)
        )
        db.commit()
    return jsonify({"id": account_id, "name": name, "balance_cents": initial_cents}), 201

@app.get("/accounts/<int:account_id>")
@login_required
def get_account(account_id):
    user = current_user()
    db = get_db()
    row = db.execute(
        "SELECT id, name, balance_cents, owner_user_id FROM accounts WHERE id = ?",
        (account_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "account not found"}), 404
    if row["owner_user_id"] != user["id"] and not user.get("is_admin"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify({
        "id": row["id"],
        "name": row["name"],
        "balance_cents": row["balance_cents"],
        "balance_usd": f"${row['balance_cents']/100:.2f}"
    })

@app.post("/accounts/<int:account_id>/deposit")
@login_required
def deposit(account_id):
    data = request.get_json(silent=True) or {}
    amount_cents = data.get("amount_cents")
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        return jsonify({"error": "amount_cents must be a positive integer"}), 400

    user = current_user()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT owner_user_id, balance_cents FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            db.rollback()
            return jsonify({"error": "account not found"}), 404
        if row["owner_user_id"] != user["id"] and not user.get("is_admin"):
            db.rollback()
            return jsonify({"error": "forbidden"}), 403

        new_balance = row["balance_cents"] + amount_cents
        db.execute("UPDATE accounts SET balance_cents = ? WHERE id = ?", (new_balance, account_id))
        db.execute("INSERT INTO transactions (account_id, type, amount_cents) VALUES (?, 'deposit', ?)",
                   (account_id, amount_cents))
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": "internal error", "detail": str(e)}), 500

    return jsonify({"status": "ok", "account_id": account_id, "new_balance_cents": new_balance,
                    "new_balance_usd": f"${new_balance/100:.2f}"})

@app.post("/accounts/<int:account_id>/withdraw")
@login_required
def withdraw(account_id):
    data = request.get_json(silent=True) or {}
    amount_cents = data.get("amount_cents")
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        return jsonify({"error": "amount_cents must be a positive integer"}), 400

    user = current_user()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT owner_user_id, balance_cents FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            db.rollback()
            return jsonify({"error": "account not found"}), 404
        if row["owner_user_id"] != user["id"] and not user.get("is_admin"):
            db.rollback()
            return jsonify({"error": "forbidden"}), 403
        if row["balance_cents"] < amount_cents:
            db.rollback()
            return jsonify({"error": "insufficient funds"}), 400

        new_balance = row["balance_cents"] - amount_cents
        db.execute("UPDATE accounts SET balance_cents = ? WHERE id = ?", (new_balance, account_id))
        db.execute("INSERT INTO transactions (account_id, type, amount_cents) VALUES (?, 'withdraw', ?)",
                   (account_id, amount_cents))
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": "internal error", "detail": str(e)}), 500

    return jsonify({"status": "ok", "account_id": account_id, "new_balance_cents": new_balance,
                    "new_balance_usd": f"${new_balance/100:.2f}"})

@app.post("/accounts/transfer")
@login_required
def transfer():
    data = request.get_json(silent=True) or {}
    from_id = data.get("from_account_id")
    to_id = data.get("to_account_id")
    amount_cents = data.get("amount_cents")

    if not isinstance(from_id, int) or not isinstance(to_id, int):
        return jsonify({"error": "from_account_id and to_account_id must be integers"}), 400
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        return jsonify({"error": "amount_cents must be a positive integer"}), 400
    if from_id == to_id:
        return jsonify({"error": "from and to accounts must differ"}), 400

    user = current_user()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        src = db.execute("SELECT owner_user_id, balance_cents FROM accounts WHERE id = ?", (from_id,)).fetchone()
        dst = db.execute("SELECT owner_user_id, balance_cents FROM accounts WHERE id = ?", (to_id,)).fetchone()
        if not src or not dst:
            db.rollback()
            return jsonify({"error": "one or both accounts not found"}), 404
        if src["owner_user_id"] != user["id"] and not user.get("is_admin"):
            db.rollback()
            return jsonify({"error": "forbidden: you do not own the source account"}), 403
        if src["balance_cents"] < amount_cents:
            db.rollback()
            return jsonify({"error": "insufficient funds"}), 400

        new_src = src["balance_cents"] - amount_cents
        new_dst = dst["balance_cents"] + amount_cents

        db.execute("UPDATE accounts SET balance_cents = ? WHERE id = ?", (new_src, from_id))
        db.execute("UPDATE accounts SET balance_cents = ? WHERE id = ?", (new_dst, to_id))

        db.execute("INSERT INTO transactions (account_id, type, amount_cents, related_account) VALUES (?, 'transfer_out', ?, ?)",
                   (from_id, amount_cents, to_id))
        db.execute("INSERT INTO transactions (account_id, type, amount_cents, related_account) VALUES (?, 'transfer_in', ?, ?)",
                   (to_id, amount_cents, from_id))

        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": "internal error", "detail": str(e)}), 500

    return jsonify({
        "status": "ok",
        "from_account_id": from_id,
        "to_account_id": to_id,
        "amount_cents": amount_cents,
        "from_new_balance_cents": new_src,
        "to_new_balance_cents": new_dst
    })

# Serve frontend static file index
@app.get("/")
def index():
    return app.send_static_file('index.html')

if __name__ == "__main__":
    init_db()
    print("Starting demo bank on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
