from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import date, datetime
import sqlite3
import hashlib
import uuid
import os
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
# from config import usuario, senha

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Generate a random secret key for sessions

# Database setup
def setup_database():
    conn = sqlite3.connect('visitor_data.db')
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
    
    # Create visit_counts table with both daily and cumulative counts
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
    conn.close()

# Initialize the database at startup
setup_database()

# Try to import from config file, otherwise use environment variables
# try:
#     from config import usuario, senha
#     ADMIN_USERNAME = usuario
#     ADMIN_PASSWORD = generate_password_hash(senha)
# except ImportError:
# Use environment variables instead
ADMIN_USERNAME = os.environ.get('usuario')
# Check if the password is already hashed
ADMIN_PASSWORD = generate_password_hash(os.environ.get('senha', ''))

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
    current_year = today.year
    return render_template("index.html", current_year=current_year)

# Generate a unique visitor ID (anonymized)
def generate_visitor_id(ip, user_agent):
    data = f"{ip}_{user_agent}_{str(uuid.uuid4())}"
    return hashlib.md5(data.encode()).hexdigest()

# Track visitor function
@app.route('/track', methods=['GET'])
def track_visitor():
    # Get visitor data
    ip_address = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')
    page_url = request.args.get('page', 'unknown')
    referrer = request.headers.get('Referer', '')
    
    # Generate visitor ID
    visitor_id = generate_visitor_id(ip_address, user_agent)
    
    # Current time
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # Connect to database
    conn = sqlite3.connect('visitor_data.db')
    cursor = conn.cursor()
    
    # Insert visit data
    cursor.execute('''
    INSERT INTO visitors (visitor_id, ip_address, user_agent, page_url, timestamp, referrer)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (visitor_id, ip_address, user_agent, page_url, current_time, referrer))
    
    # Count all visits and unique visitors
    cursor.execute('SELECT COUNT(*) FROM visitors')
    total_visits = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT visitor_id) FROM visitors')
    total_unique = cursor.fetchone()[0]
    
    # Count daily visits and unique visitors
    cursor.execute('''
    SELECT COUNT(*) FROM visitors 
    WHERE timestamp LIKE ?
    ''', (f'{current_date}%',))
    daily_visits = cursor.fetchone()[0]
    
    cursor.execute('''
    SELECT COUNT(DISTINCT visitor_id) FROM visitors 
    WHERE timestamp LIKE ?
    ''', (f'{current_date}%',))
    daily_unique = cursor.fetchone()[0]
    
    # Update or insert the daily record with both daily and total counts
    cursor.execute('SELECT * FROM visit_counts WHERE date = ?', (current_date,))
    if cursor.fetchone():
        cursor.execute('''
        UPDATE visit_counts 
        SET daily_visits = ?, 
            daily_unique = ?, 
            total_visits = ?, 
            total_unique = ? 
        WHERE date = ?
        ''', (daily_visits, daily_unique, total_visits, total_unique, current_date))
    else:
        cursor.execute('''
        INSERT INTO visit_counts 
        (date, daily_visits, daily_unique, total_visits, total_unique) 
        VALUES (?, ?, ?, ?, ?)
        ''', (current_date, daily_visits, daily_unique, total_visits, total_unique))
    
    conn.commit()
    conn.close()
    
    # Return a transparent 1x1 pixel GIF
    return app.response_class(
        response=b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b',
        status=200,
        mimetype='image/gif'
    )

# Login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        print(f"Login attempt: {username}")
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD, password):
            session['logged_in'] = True
            session['username'] = username
            next_page = request.args.get('next')
            return redirect(next_page or url_for('stats_dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

# Logout
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))

# Statistics dashboard
@app.route('/stats-dashboard')
@login_required
def stats_dashboard():
    return render_template('stats_dashboard.html')

# Statistics API endpoint
@app.route('/stats/api', methods=['GET'])
@login_required
def get_stats():
    conn = sqlite3.connect('visitor_data.db')
    cursor = conn.cursor()
    
    # Get the most recent total counts
    cursor.execute('SELECT total_visits, total_unique FROM visit_counts ORDER BY date DESC LIMIT 1')
    totals = cursor.fetchone()
    
    if not totals:
        # If no records exist yet, count directly from visitors table
        cursor.execute('SELECT COUNT(*) FROM visitors')
        total_visits = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT visitor_id) FROM visitors')
        total_unique = cursor.fetchone()[0]
    else:
        total_visits, total_unique = totals
    
    # Get daily stats
    cursor.execute('SELECT date, daily_visits, daily_unique, total_visits, total_unique FROM visit_counts ORDER BY date DESC')
    daily_stats = cursor.fetchall()
    
    # Get page views breakdown
    cursor.execute('''
    SELECT page_url, COUNT(*) as views 
    FROM visitors 
    GROUP BY page_url 
    ORDER BY views DESC
    ''')
    page_stats = cursor.fetchall()
    
    # Get referrer breakdown
    cursor.execute('''
    SELECT referrer, COUNT(*) as count 
    FROM visitors 
    WHERE referrer != '' 
    GROUP BY referrer 
    ORDER BY count DESC 
    LIMIT 10
    ''')
    referrer_stats = cursor.fetchall()
    
    conn.close()
    
    return jsonify({
        'total_visits': total_visits,
        'total_unique_visitors': total_unique,
        'daily_stats': [
            {
                'date': row[0],
                'total_visits': row[1],  # Using daily_visits as total_visits for backward compatibility
                'unique_visitors': row[2],  # Using daily_unique as unique_visitors for backward compatibility
                'cumulative_visits': row[3],
                'cumulative_unique_visitors': row[4]
            } for row in daily_stats
        ],
        'page_stats': [
            {
                'page': row[0],
                'views': row[1]
            } for row in page_stats
        ],
        'referrer_stats': [
            {
                'referrer': row[0],
                'count': row[1]
            } for row in referrer_stats
        ]
    })

if __name__ == "__main__":
    setup_database()
    
    # app.run(debug=True, host='0.0.0.0', port=5000)
    # For production:
    app.run(debug=False, host='0.0.0.0', port=8080)