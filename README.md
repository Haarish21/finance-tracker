
# Personal Finance Tracker (Flask + Chart.js + ML)

A full-stack web app to track income/expenses, visualize spending, and get ML-powered savings tips.

## Features
- User auth (register/login)
- Add transactions manually
- Upload CSV (date, amount, type, category, description)
- Dashboard with:
  - Summary (income/expense/balance)
  - Monthly trend (income vs expense)
  - Category pie chart
  - Smart recommendations + next-month expense prediction (Linear Regression)
- Export CSV
- SQLite by default; works with Postgres on Render/Railway

## Local Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit SECRET_KEY in .env if needed
python app.py  # http://localhost:5000
```

## CSV Format
```csv
date,amount,type,category,description
2025-07-01,50000,income,Salary,July salary
2025-07-02,300,expense,Food,Lunch
```

## Deploy (Render example)
1. Push to GitHub.
2. Create **Render Web Service**:
   - Start command: `gunicorn app:app`
   - Environment:
     - `DATABASE_URL` = `sqlite:///finance.db` (or Render PostgreSQL URL)
     - `SECRET_KEY` = your-random-key
3. Add a free PostgreSQL instance if you want a managed DB; update `DATABASE_URL`.

## Project Structure
```
finance_tracker/
  app.py
  models.py
  ml/
    __init__.py
    recommender.py
  templates/
    base.html, login.html, register.html, dashboard.html, add_transaction.html, upload.html
  static/main.css
  requirements.txt
  README.md
  .env.example
```

## Notes
- ML is intentionally simple (Linear Regression over monthly totals). Extend with ARIMA/LSTM later.
- All amounts are treated as positive numbers; `type` decides whether it's income or expense.
- For Postgres on Render, make sure `psycopg2-binary` is added if you switch DB engines.
```bash
pip install psycopg2-binary
```
