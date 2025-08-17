
import os
import pickle
import pandas as pd
from datetime import date
from sklearn.linear_model import LinearRegression
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Transaction, db

# Note: In Flask app context, use db.session directly. Here we will use db.session passed implicitly.

def _query_user_df(user_id):
    # Build a DataFrame of user's transactions
    rows = db.session.query(Transaction).filter(Transaction.user_id == user_id).all()
    if not rows:
        return pd.DataFrame(columns=['date','amount','type','category'])
    data = [{
        'date': r.date,
        'amount': r.amount,
        'type': r.ttype,
        'category': r.category
    } for r in rows]
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    return df

def predict_next_month_expense(user_id):
    df = _query_user_df(user_id)
    if df.empty:
        return 0.0
    # Create monthly expense totals
    expenses = df[df['type']=='expense'].copy()
    if expenses.empty:
        return 0.0
    expenses['ym'] = expenses['date'].dt.to_period('M').astype(str)
    m = expenses.groupby('ym')['amount'].sum().reset_index()
    if len(m) < 2:
        # Not enough data to fit
        return float(m['amount'].iloc[-1]) if len(m) else 0.0
    # Turn months into an integer index
    m['idx'] = range(1, len(m)+1)
    X = m[['idx']].values
    y = m['amount'].values
    model = LinearRegression().fit(X, y)
    next_idx = m['idx'].max() + 1
    pred = float(model.predict([[next_idx]])[0])
    return max(pred, 0.0)

def generate_recommendations(user_id):
    df = _query_user_df(user_id)
    recs = []
    if df.empty:
        recs.append('Add at least 2 months of data to get personalized savings insights.')
        return recs
    # Basic ratios
    total_income = df[df['type']=='income']['amount'].sum()
    total_expense = df[df['type']=='expense']['amount'].sum()
    if total_income > 0:
        savings_rate = max((total_income - total_expense) / total_income, 0)
        recs.append(f'Your overall savings rate is {savings_rate*100:.1f}%. Aim for 20%+ as a baseline.')
    else:
        recs.append('Add income entries to compute your savings rate.')
    # Category suggestions (top 3 spend categories)
    cat = df[df['type']=='expense'].groupby('category')['amount'].sum().sort_values(ascending=False)
    top3 = cat.head(3)
    for c, v in top3.items():
        recs.append(f'High spend in "{c}" category: ₹{v:.0f}. Consider setting a monthly cap or finding cheaper alternatives.')
    # Volatility check: if last month higher than prior avg
    if not df[df['type']=='expense'].empty:
        expenses = df[df['type']=='expense'].copy()
        expenses['ym'] = expenses['date'].dt.to_period('M').astype(str)
        monthly = expenses.groupby('ym')['amount'].sum()
        if len(monthly) >= 2:
            last = monthly.iloc[-1]
            prev_avg = monthly.iloc[:-1].mean()
            if last > 1.2 * prev_avg:
                recs.append("Last month's expenses exceeded your previous average by 20%+. Review discretionary categories.")
    # Prediction informed suggestion
    pred = predict_next_month_expense(user_id)
    if total_income > 0:
        target_save = max(total_income*0.2, 0)
        recs.append(f'Predicted next month expense: ₹{pred:.0f}. Set a savings target of at least ₹{target_save:.0f}.')
    else:
        recs.append(f'Predicted next month expense: ₹{pred:.0f}. Add income to compute a savings target.')
    return recs
