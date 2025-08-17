import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Transaction
from ml.recommender import generate_recommendations, predict_next_month_expense
from sqlalchemy import func, case

def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///finance.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app

app = create_app()

# ---------------------- Auth Helpers ----------------------
def current_user():
    uid = session.get('user_id')
    if uid:
        return User.query.get(uid)
    return None

def login_required(view_func):
    from functools import wraps
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login', next=request.path))
        return view_func(*args, **kwargs)
    return wrapped

# ---------------------- Routes: Auth ----------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        if not name or not email or not password:
            flash('All fields are required.', 'error')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return render_template('register.html')
        user = User(name=name, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid credentials.', 'error')
            return render_template('login.html')
        session['user_id'] = user.id
        flash('Welcome back!', 'success')
        next_url = request.args.get('next') or url_for('dashboard')
        return redirect(next_url)
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'success')
    return redirect(url_for('login'))

# ---------------------- Routes: Pages ----------------------
@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user(), datetime=datetime)

@app.route('/transactions/add', methods=['GET', 'POST'])
@login_required
def add_transaction():
    if request.method == 'POST':
        user = current_user()
        try:
            tdate = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        except Exception:
            flash('Invalid date format.', 'error')
            return render_template('add_transaction.html')
        amount = float(request.form.get('amount', 0))
        ttype = request.form.get('type')
        category = request.form.get('category', 'Other')
        description = request.form.get('description', '')
        if ttype not in ('income', 'expense'):
            flash('Type must be income or expense.', 'error')
            return render_template('add_transaction.html')
        tx = Transaction(user_id=user.id, date=tdate, amount=amount, ttype=ttype, category=category, description=description)
        db.session.add(tx)
        db.session.commit()
        flash('Transaction added.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('add_transaction.html')

@app.route('/transactions/upload', methods=['GET', 'POST'])
@login_required
def upload_transactions():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash('No file uploaded.', 'error')
            return render_template('upload.html')
        import csv, io
        stream = io.StringIO(file.stream.read().decode('utf-8'))
        reader = csv.DictReader(stream)
        required = {'date', 'amount', 'type', 'category', 'description'}
        if not required.issubset(set(h.lower() for h in reader.fieldnames)):
            flash('CSV must have headers: date, amount, type, category, description', 'error')
            return render_template('upload.html')
        count = 0
        for row in reader:
            try:
                tdate = datetime.strptime(row['date'], '%Y-%m-%d').date()
                amount = float(row['amount'])
                ttype = row['type'].lower()
                category = row.get('category', 'Other')
                description = row.get('description', '')
                if ttype not in ('income', 'expense'):
                    continue
                tx = Transaction(user_id=current_user().id, date=tdate, amount=amount, ttype=ttype, category=category, description=description)
                db.session.add(tx)
                count += 1
            except Exception:
                continue
        db.session.commit()
        flash(f'Imported {count} transactions.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('upload.html')

# ---------------------- Delete Transaction ----------------------
@app.route('/transactions/delete/<int:txn_id>', methods=['POST'])
@login_required
def delete_transaction(txn_id):
    txn = Transaction.query.filter_by(id=txn_id, user_id=session['user_id']).first()
    if not txn:
        return jsonify({'success': False, 'message': 'Transaction not found.'})
    db.session.delete(txn)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Transaction deleted.'})



# ---------------------- API Helpers ----------------------
def _apply_year_month_filters(query, year: int | None, month: int | None):
    if year:
        query = query.filter(func.strftime('%Y', Transaction.date) == f'{year:04d}')
    if month:
        query = query.filter(func.strftime('%m', Transaction.date) == f'{month:02d}')
    return query

# ---------------------- API Endpoints ----------------------
@app.route('/api/available_years')
@login_required
def api_available_years():
    user = current_user()
    years_rows = db.session.query(func.strftime('%Y', Transaction.date).label('y')).filter(Transaction.user_id == user.id).distinct().order_by('y').all()
    years = [int(y[0]) for y in years_rows] or [datetime.now().year]
    return jsonify(years)

@app.route('/api/summary')
@login_required
def api_summary():
    user = current_user()
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    t_type = request.args.get('type')  # 'income', 'expense', or None

    if t_type == 'income':
        q = db.session.query(func.sum(Transaction.amount).label('income')).filter_by(user_id=user.id, ttype='income')
        q = _apply_year_month_filters(q, year, month)
        totals = q.first()
        return jsonify({'income': float(totals.income or 0), 'expense': 0, 'balance': float(totals.income or 0)})
    elif t_type == 'expense':
        q = db.session.query(func.sum(Transaction.amount).label('expense')).filter_by(user_id=user.id, ttype='expense')
        q = _apply_year_month_filters(q, year, month)
        totals = q.first()
        return jsonify({'income': 0, 'expense': float(totals.expense or 0), 'balance': -float(totals.expense or 0)})

    q = db.session.query(
        func.sum(case((Transaction.ttype == 'income', Transaction.amount), else_=0)).label('income'),
        func.sum(case((Transaction.ttype == 'expense', Transaction.amount), else_=0)).label('expense')
    ).filter(Transaction.user_id == user.id)
    q = _apply_year_month_filters(q, year, month)
    totals = q.first()
    return jsonify({
        'income': float(totals.income or 0),
        'expense': float(totals.expense or 0),
        'balance': float((totals.income or 0) - (totals.expense or 0))
    })

@app.route('/api/category_breakdown')
@login_required
def api_category_breakdown():
    user = current_user()
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    t_type = request.args.get('type')  # optional filter

    q = db.session.query(
        Transaction.category,
        func.sum(case((Transaction.ttype == 'expense', Transaction.amount), else_=0)).label('amount')
    ).filter(Transaction.user_id == user.id)
    q = _apply_year_month_filters(q, year, month)
    rows = q.group_by(Transaction.category).all()
    return jsonify([{'category': r[0], 'amount': float(r[1] or 0)} for r in rows if (r[1] or 0) > 0])

@app.route('/api/monthly_trend')
@login_required
def api_monthly_trend():
    """Return monthly income/expense for a given year. Fill 0 for months with no transactions."""
    user = current_user()
    year = request.args.get('year', type=int)
    t_type = request.args.get('type')  # optional filter

    if not year:
        year_row = db.session.query(func.strftime('%Y', Transaction.date).label('y')).filter(Transaction.user_id==user.id).distinct().order_by('y').all()
        year = int(year_row[-1][0]) if year_row else datetime.now().year

    rows = db.session.query(
        func.strftime('%m', Transaction.date).label('m'),
        func.sum(case((Transaction.ttype=='income', Transaction.amount), else_=0)).label('income'),
        func.sum(case((Transaction.ttype=='expense', Transaction.amount), else_=0)).label('expense')
    ).filter(Transaction.user_id==user.id, func.strftime('%Y', Transaction.date)==f'{year:04d}').group_by('m').order_by('m').all()

    monthly = {str(m).zfill(2): {'income':0, 'expense':0} for m in range(1,13)}
    for r in rows:
        monthly[r[0]] = {'income': float(r[1] or 0), 'expense': float(r[2] or 0)}

    return jsonify([{'month': f'{year}-{m}', 'income': monthly[m]['income'], 'expense': monthly[m]['expense']} for m in sorted(monthly.keys())])

@app.route('/api/recommendations')
@login_required
def api_recommendations():
    user = current_user()
    recs = generate_recommendations(user.id)
    pred = predict_next_month_expense(user.id)
    return jsonify({'recommendations': recs, 'next_month_expense_prediction': pred})

@app.route('/api/transactions')
@login_required
def api_transactions():
    """Return user's transactions filtered by year/month/type for dashboard."""
    user = current_user()
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    t_type = request.args.get('type')  # 'income', 'expense', or None

    q = Transaction.query.filter_by(user_id=user.id)
    if year:
        q = q.filter(func.strftime('%Y', Transaction.date) == f'{year:04d}')
    if month:
        q = q.filter(func.strftime('%m', Transaction.date) == f'{month:02d}')
    if t_type in ['income', 'expense']:
        q = q.filter_by(ttype=t_type)

    txs = q.order_by(Transaction.date.desc()).all()
    return jsonify([{
        'id': tx.id,
        'date': tx.date.isoformat(),
        'amount': tx.amount,
        'type': tx.ttype,
        'category': tx.category,
        'description': tx.description or ''
    } for tx in txs])

# ---------------------- Export CSV ----------------------
@app.route('/export.csv')
@login_required
def export_csv():
    import csv, io
    user = current_user()
    transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.date.desc()).all()
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['date','amount','type','category','description'])
    for t in transactions:
        writer.writerow([t.date.isoformat(), t.amount, t.ttype, t.category, t.description or ''])
    output = si.getvalue().encode('utf-8')
    return (output, 200, {'Content-Type':'text/csv; charset=utf-8','Content-Disposition':'attachment; filename=transactions.csv'})

@app.route('/transactions/delete_month', methods=['POST'])
@login_required
def delete_month():
    user = current_user()
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    if not year or not month:
        return jsonify({'success': False, 'message': 'Year and month required.'})
    txs = Transaction.query.filter_by(user_id=user.id).filter(
        func.strftime('%Y', Transaction.date) == f'{year:04d}',
        func.strftime('%m', Transaction.date) == f'{month:02d}'
    ).all()
    count = len(txs)
    for t in txs:
        db.session.delete(t)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Deleted {count} transactions for {month}/{year}.'})

@app.route('/transactions/delete_year', methods=['POST'])
@login_required
def delete_year():
    user = current_user()
    year = request.form.get('year', type=int)
    if not year:
        return jsonify({'success': False, 'message': 'Year required.'})
    txs = Transaction.query.filter_by(user_id=user.id).filter(
        func.strftime('%Y', Transaction.date) == f'{year:04d}'
    ).all()
    count = len(txs)
    for t in txs:
        db.session.delete(t)
    db.session.commit()
    return jsonify({'success': True, 'message': f'Deleted {count} transactions for year {year}.'})


# ---------------------- Run App ----------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=True)
