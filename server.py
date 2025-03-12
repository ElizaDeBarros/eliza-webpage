from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import date, datetime
import sqlite3
import hashlib
import uuid
import os
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # Use env var or generate random key

# Database path (ensure it's in a writable location)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'visitor_data.db')

# Database setup with error handling
def setup_database():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create visitors table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT,
            ip_address TEXT,
            user_agent TEXT,
            page_url TEXT,
            timestamp TEXT,
            referrer TEXT
        )
        ''')
        
        # Create visit_counts table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visit_counts (
            date TEXT PRIMARY KEY,
            daily_visits INTEGER DEFAULT 0,
            daily_unique INTEGER DEFAULT 0,
            total_visits INTEGER DEFAULT 0,
            total_unique INTEGER DEFAULT 0
        )
        ''')
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database setup error: {e}")
    finally:
        conn.close()

# Initialize database
setup_database()

# Admin credentials from environment variables with defaults
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'password'))

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def home():
    today = date.today()
    return render_template("index.html", current_year=today.year)

def generate_visitor_id(ip, user_agent):
    data = f"{ip}_{user_agent}_{str(uuid.uuid4())}"
    return hashlib.md5(data.encode()).hexdigest()

@app.route('/track', methods=['GET'])
def track_visitor():
    try:
        ip_address = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')
        page_url = request.args.get('page', 'unknown')
        referrer = request.headers.get('Referer', '')
        
        visitor_id = generate_visitor_id(ip_address, user_agent)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Insert visitor data
        cursor.execute('''
        INSERT INTO visitors (visitor_id, ip_address, user_agent, page_url, timestamp, referrer)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (visitor_id, ip_address, user_agent, page_url, current_time, referrer))
        
        # Update counts
        cursor.execute('SELECT total_visits, total_unique FROM visit_counts ORDER BY date DESC LIMIT 1')
        previous = cursor.fetchone()
        total_visits = (previous['total_visits'] if previous else 0) + 1
        
        cursor.execute('SELECT COUNT(DISTINCT visitor_id) FROM visitors')
        total_unique = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM visitors WHERE timestamp LIKE ?', (f'{current_date}%',))
        daily_visits = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT visitor_id) FROM visitors WHERE timestamp LIKE ?', (f'{current_date}%',))
        daily_unique = cursor.fetchone()[0]
        
        # Upsert visit counts
        cursor.execute('''
        INSERT INTO visit_counts (date, daily_visits, daily_unique, total_visits, total_unique)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            daily_visits = excluded.daily_visits,
            daily_unique = excluded.daily_unique,
            total_visits = excluded.total_visits,
            total_unique = excluded.total_unique
        ''', (current_date, daily_visits, daily_unique, total_visits, total_unique))
        
        conn.commit()
        
        # Return 1x1 pixel GIF
        return app.response_class(
            response=b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b',
            status=200,
            mimetype='image/gif'
        )
    except sqlite3.Error as e:
        print(f"Tracking error: {e}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD, password):
            session['logged_in'] = True
            session['username'] = username
            next_page = request.args.get('next')
            return redirect(next_page or url_for('stats_dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/stats-dashboard')
@login_required
def stats_dashboard():
    return render_template('stats_dashboard.html')

@app.route('/stats/api', methods=['GET'])
@login_required
def get_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT total_visits, total_unique FROM visit_counts ORDER BY date DESC LIMIT 1')
        totals = cursor.fetchone() or {'total_visits': 0, 'total_unique': 0}
        
        cursor.execute('SELECT date, daily_visits, daily_unique, total_visits, total_unique FROM visit_counts ORDER BY date DESC')
        daily_stats = cursor.fetchall()
        
        cursor.execute('SELECT page_url, COUNT(*) as views FROM visitors GROUP BY page_url ORDER BY views DESC')
        page_stats = cursor.fetchall()
        
        cursor.execute('SELECT referrer, COUNT(*) as count FROM visitors WHERE referrer != "" GROUP BY referrer ORDER BY count DESC LIMIT 10')
        referrer_stats = cursor.fetchall()
        
        conn.close()
        
        return jsonify({
            'total_visits': totals['total_visits'],
            'total_unique_visitors': totals['total_unique'],
            'daily_stats': [dict(row) for row in daily_stats],
            'page_stats': [{'page': row['page_url'], 'views': row['views']} for row in page_stats],
            'referrer_stats': [{'referrer': row['referrer'], 'count': row['count']} for row in referrer_stats]
        })
    except sqlite3.Error as e:
        print(f"Stats error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == "__main__":
    setup_database()
    app.run(debug=False, host='0.0.0.0', port=8080)