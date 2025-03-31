from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime
import sqlite3
import hashlib
import uuid
import os
import tempfile
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import pytz

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Database configuration
PERSISTENT_STORAGE = '/var/data'
DB_DIR = PERSISTENT_STORAGE if os.path.exists(PERSISTENT_STORAGE) else os.environ.get('DATABASE_DIR', tempfile.gettempdir())
DB_PATH = os.environ.get('DATABASE_URL', os.path.join(DB_DIR, 'visitor_data.db'))

# Timezone configuration - fixed to Pacific Standard Time
LOCAL_TIMEZONE = 'America/Los_Angeles'  # PST/PDT

def get_db_connection():
    """Create a database connection with proper configuration"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}")
        raise

def setup_database():
    """Initialize database with enhanced structure"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Enhanced visitors table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            id-integer INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            page_url TEXT,
            timestamp TEXT,
            referrer TEXT,
            hostname TEXT,
            forwarded_for TEXT,
            session_duration INTEGER DEFAULT 0
        )
        ''')
        
        # Enhanced visit counts table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visit_counts (
            date TEXT PRIMARY KEY,
            daily_visits INTEGER DEFAULT 0,
            daily_unique INTEGER DEFAULT 0,
            total_visits INTEGER DEFAULT 0,
            total_unique INTEGER DEFAULT 0
        )
        ''')
        
        # Initialize today's counts
        today = datetime.now(pytz.timezone(LOCAL_TIMEZONE)).strftime('%Y-%m-%d')
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
        if conn:
            conn.close()

# Initialize database on startup
try:
    setup_database()
except Exception as e:
    print(f"Failed to initialize database: {e}")

# Authentication configuration
ADMIN_USERNAME = os.environ.get('usuario', 'admin')
password_env = os.environ.get('senha', 'password')
ADMIN_PASSWORD = password_env if password_env.startswith('pbkdf2:sha256:') else generate_password_hash(password_env)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def home():
    today = datetime.now(pytz.timezone(LOCAL_TIMEZONE))
    tracking_url = url_for('track_visitor', page='/', _external=True)
    return render_template("index.html", current_year=today.year, tracking_url=tracking_url)

def generate_visitor_id(ip, user_agent):
    data = f"{ip}_{user_agent}_{str(uuid.uuid4())}"
    return hashlib.sha256(data.encode()).hexdigest()

@app.route('/track', methods=['GET'])
def track_visitor():
    conn = None
    try:
        # Get detailed visitor info
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
        forwarded_for = request.headers.get('X-Forwarded-For', '')
        user_agent = request.headers.get('User-Agent', '')
        hostname = request.headers.get('Host', '')
        page_url = request.args.get('page', 'unknown')
        referrer = request.headers.get('Referer', '')
        
        visitor_id = generate_visitor_id(ip_address, user_agent)
        local_tz = pytz.timezone(LOCAL_TIMEZONE)
        current_time = datetime.now(local_tz).strftime('%Y-%m-%d %H:%M:%S')
        current_date = datetime.now(local_tz).strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Log visit with additional details
        cursor.execute('''
        INSERT INTO visitors (visitor_id, ip_address, user_agent, page_url, timestamp, referrer, hostname, forwarded_for) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
        (visitor_id, ip_address, user_agent, page_url, current_time, referrer, hostname, forwarded_for))
        
        # Check if visitor is new today
        cursor.execute('SELECT COUNT(*) FROM visitors WHERE visitor_id = ? AND timestamp LIKE ?', 
                      (visitor_id, f'{current_date}%'))
        is_new_unique_today = cursor.fetchone()[0] == 1
        
        # Get overall totals
        cursor.execute('SELECT COUNT(*) FROM visitors')
        total_visits = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT visitor_id) FROM visitors')
        total_unique = cursor.fetchone()[0]
        
        # Update daily counts
        cursor.execute('SELECT daily_visits, daily_unique FROM visit_counts WHERE date = ?', (current_date,))
        current = cursor.fetchone()
        
        if current:
            daily_visits = current['daily_visits'] + 1
            daily_unique = current['daily_unique'] + (1 if is_new_unique_today else 0)
        else:
            daily_visits = 1
            daily_unique = 1
        
        # Update visit_counts table
        cursor.execute('''
        INSERT OR REPLACE INTO visit_counts 
        (date, daily_visits, daily_unique, total_visits, total_unique)
        VALUES (?, ?, ?, ?, ?)
        ''', (current_date, daily_visits, daily_unique, total_visits, total_unique))
        
        conn.commit()
        
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
        
        today = datetime.now(pytz.timezone(LOCAL_TIMEZONE)).strftime('%Y-%m-%d')
        
        # Get overall totals directly from visitors table
        cursor.execute('SELECT COUNT(*) FROM visitors')
        total_visits = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT visitor_id) FROM visitors')
        total_unique = cursor.fetchone()[0]
        
        cursor.execute('SELECT daily_visits FROM visit_counts WHERE date = ?', (today,))
        today_visits = cursor.fetchone()
        today_visits = today_visits['daily_visits'] if today_visits else 0
        
        cursor.execute('SELECT date, daily_visits, daily_unique FROM visit_counts ORDER BY date DESC')
        daily_stats = cursor.fetchall()
        
        cursor.execute('SELECT page_url, COUNT(*) as views FROM visitors GROUP BY page_url ORDER BY views DESC')
        page_stats = cursor.fetchall()
        
        cursor.execute('SELECT referrer, COUNT(*) as count FROM visitors WHERE referrer != "" GROUP BY referrer ORDER BY count DESC LIMIT 10')
        referrer_stats = cursor.fetchall()
        
        return jsonify({
            'total_visits': total_visits,
            'total_unique_visitors': total_unique,
            'today_visits': today_visits,
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

@app.route('/stats/visitors', methods=['GET'])
@login_required
def get_visitor_details():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Removed date filter to show all visitors
        cursor.execute('''
            SELECT visitor_id, ip_address, user_agent, page_url, timestamp, referrer, hostname, forwarded_for
            FROM visitors 
            ORDER BY timestamp DESC
        ''')
        
        visitors = cursor.fetchall()
        
        return jsonify({
            'visitors': [dict(row) for row in visitors]
        })
    except sqlite3.Error as e:
        print(f"Visitor details error: {e}")
        return jsonify({'error': 'Database error'}), 500
    finally:
        if conn:
            conn.close()

@app.route('/health')
def health_check():
    return jsonify({'status': 'ok'})

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting server on port: {port}")
    print(f"Database path: {DB_PATH}")
    print(f"Admin username: {ADMIN_USERNAME}")
    print(f"Using timezone: {LOCAL_TIMEZONE}")
    app.run(debug=False, host='0.0.0.0', port=port)