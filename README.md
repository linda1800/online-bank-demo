# online-bank-demo

Demo online bank web app with login, accounts, transfers, and a minimal frontend.

This repository contains a simple Flask backend (SQLite for local demo) and a tiny frontend (vanilla JS) so you can run the app locally or containerize it later.

Quickstart (local):

1. Create a virtualenv and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

2. Run the backend

```bash
python backend/app.py
```

3. Open the frontend

Open `frontend/index.html` in your browser (it will use `http://localhost:5000` by default). If you're testing with cookies, serve the frontend via a static file server (e.g., `python -m http.server 8000` in the frontend directory) and open `http://localhost:8000`.

Seeded credentials:
- admin / adminpass (admin user owns a seeded "Big Balance Demo" account)

Notes:
- This is a demo only. Do NOT use with real credentials or money.
