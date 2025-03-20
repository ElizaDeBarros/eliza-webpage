from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime
import sqlite3
import hashlib
import uuid
import os
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Use environment variable for DB path or fallback to persistent location
DB_PATH = os.environ.get('DATABASE_URL', '/data/visitor_data.db')

def get_db_connection():
    """Create a database connection with proper configuration"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    """Initialize database with error handling and directory creation"""
    try:
        # Ensure directory exists if using local file
        if not DB_PATH.startswith('sqlite:///'):
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check SQLite version
        # conn = sqlite3.connect(DB_PATH)
        # print(sqlite3.sqlite_version)  # Prints the SQLite version, e.g., "3.42.0"
        # conn.close()
        
        # Create tables with improved structure
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            page_url TEXT,
            timestamp TEXT,
            referrer TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visit_counts (
            date TEXT PRIMARY KEY,
            daily_visits INTEGER DEFAULT 0,
            daily_unique INTEGER DEFAULT 0,
            total_visits INTEGER DEFAULT 0,
            total_unique INTEGER DEFAULT 0
        )
        ''')
        
        # Initialize today's counts if not exists
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
        INSERT OR IGNORE INTO visit_counts 
        (date, daily_visits, daily_unique, total_visits, total_unique) 
        VALUES (?, 0, 0, 0, 0)
        ''', (today,))
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database setup error: {e}")
        raise
    finally:
        conn.close()

# Initialize database on startup
try:
    setup_database()
except Exception as e:
    print(f"Failed to initialize database: {e}")

ADMIN_USERNAME = os.environ.get('usuario')
ADMIN_PASSWORD = generate_password_hash(os.environ.get('senha', ''))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def home():
    today = datetime.now()
    tracking_url = url_for('track_visitor', page='/', _external=True)
    return render_template("index.html", current_year=today.year, tracking_url=tracking_url)

def generate_visitor_id(ip, user_agent):
    data = f"{ip}_{user_agent}_{str(uuid.uuid4())}"
    return hashlib.md5(data.encode()).hexdigest()

@app.route('/track', methods=['GET'])
def track_visitor():
    conn = None
    try:
        ip_address = request.remote_addr or 'unknown'
        user_agent = request.headers.get('User-Agent', '')
        page_url = request.args.get('page', 'unknown')
        referrer = request.headers.get('Referer', '')
        
        visitor_id = generate_visitor_id(ip_address, user_agent)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Log visit
        cursor.execute('''
        INSERT INTO visitors (visitor_id, ip_address, user_agent, page_url, timestamp, referrer) VALUES (?, ?, ?, ?, ?, ?)''', (visitor_id, ip_address, user_agent, page_url, current_time, referrer))
        
        # Check if visitor is new today
        cursor.execute('SELECT COUNT(*) FROM visitors WHERE visitor_id = ? AND timestamp LIKE ?', 
                      (visitor_id, f'{current_date}%'))
        existing_visits = cursor.fetchone()[0]
        is_new_unique_today = existing_visits == 1
        
        # Get or initialize current counts
        cursor.execute('SELECT * FROM visit_counts WHERE date = ?', (current_date,))
        current = cursor.fetchone()
        
        if current:
            daily_visits = current['daily_visits'] + 1
            daily_unique = current['daily_unique'] + (1 if is_new_unique_today else 0)
            total_visits = current['total_visits'] + 1
            total_unique = current['total_unique']
        else:
            daily_visits = 1
            daily_unique = 1
            total_visits = 1
            total_unique = 1
        
        # Update total unique count
        cursor.execute('SELECT COUNT(DISTINCT visitor_id) FROM visitors')
        total_unique = cursor.fetchone()[0]
        
        # Update counts
        cursor.execute('''
        INSERT OR REPLACE INTO visit_counts 
        (date, daily_visits, daily_unique, total_visits, total_unique)
        VALUES (?, ?, ?, ?, ?)
        ''', (current_date, daily_visits, daily_unique, total_visits, total_unique))
        
        conn.commit()
        
        # Return 1x1 transparent GIF
        return app.response_class(
            response=b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b',
            status=200,
            mimetype='image/gif'
        )
    except sqlite3.Error as e:
        print(f"Tracking error: {e}")
        return jsonify({'error': 'Database error'}), 500
    finally:
        if conn:
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
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT total_visits, total_unique FROM visit_counts ORDER BY date DESC LIMIT 1')
        totals = cursor.fetchone() or {'total_visits': 0, 'total_unique': 0}
        
        cursor.execute('SELECT date, daily_visits, daily_unique, total_visits, total_unique FROM visit_counts ORDER BY date DESC')
        daily_stats = cursor.fetchall()
        
        cursor.execute('SELECT page_url, COUNT(*) as views FROM visitors GROUP BY page_url ORDER BY views DESC')
        page_stats = cursor.fetchall()
        
        cursor.execute('SELECT referrer, COUNT(*) as count FROM visitors WHERE referrer != "" GROUP BY referrer ORDER BY count DESC LIMIT 10')
        referrer_stats = cursor.fetchall()
        
        return jsonify({
            'total_visits': totals['total_visits'],
            'total_unique_visitors': totals['total_unique'],
            'daily_stats': [dict(row) for row in daily_stats],
            'page_stats': [{'page': row['page_url'], 'views': row['views']} for row in page_stats],
            'referrer_stats': [{'referrer': row['referrer'], 'count': row['count']} for row in referrer_stats]
        })
    except sqlite3.Error as e:
        print(f"Stats error: {e}")
        return jsonify({'error': 'Database error'}), 500
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))