"""Billing management routes"""
from flask import Blueprint, request, jsonify, session
# import sqlite3  # COMMENTED OUT - Using PostgreSQL now
import logging
import os
from datetime import datetime, timedelta
from ..config_postgres import get_logs_dir, PLTF_NAME, TRANSLATIONS

# Determine database type based on environment
from ..database_postgres import db_manager

def get_language():
    return session.get('language', 'en')

def get_text(key):
    try:
        lang = get_language()
        return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS['en'].get(key, key))
    except (KeyError, AttributeError, TypeError):
        return key

# Configure logging for billing activities
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
if logger.handlers:
    logger.handlers.clear()

# File handler
log_file = os.path.join(get_logs_dir(), 'billing_routes.log')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(file_formatter)
logger.addHandler(console_handler)

# Prevent propagation to avoid duplicate logs
logger.propagate = False

billing_bp = Blueprint('billing', __name__)

@billing_bp.route('/api/billing/activities')
def get_billing_activities():
    """Get billing activities based on user role, period, and user filter"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    period = request.args.get('period', 'month')  # day, week, month
    selected_user = request.args.get('user')  # user filter
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    is_admin = user and user[0] == 'admin'
    
    # Calculate date range
    now = datetime.now()
    if period == 'day':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = None  # For day, we use >= start_date
    elif period == 'week':
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = None  # For week, we use >= start_date
    elif period == 'previous_month':
        # Calculate previous month
        if now.month == 1:
            # If current month is January, previous month is December of previous year
            start_date = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            # Otherwise, just go to previous month
            start_date = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # month
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = None  # For current month, we use >= start_date
    
    if is_admin:
        # Admin sees activities based on filters
        if selected_user:
            if end_date:
                activities = db_manager.execute_query('''SELECT ba.id, u.username, a.name, ba.action, ba.started_at, ba.stopped_at, 
                           ba.duration_seconds, ba.cost_amount, ba.created_at
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE u.username = %s AND ((ba.started_at >= %s AND ba.started_at < %s) OR (ba.stopped_at >= %s AND ba.stopped_at < %s))
                    ORDER BY ba.created_at DESC
                ''', (selected_user, start_date.isoformat(), end_date.isoformat(), start_date.isoformat(), end_date.isoformat()), fetch_all=True)
            else:
                activities = db_manager.execute_query('''SELECT ba.id, u.username, a.name, ba.action, ba.started_at, ba.stopped_at, 
                           ba.duration_seconds, ba.cost_amount, ba.created_at
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE u.username = %s AND (ba.started_at >= %s OR ba.stopped_at >= %s)
                    ORDER BY ba.created_at DESC
                ''', (selected_user, start_date.isoformat(), start_date.isoformat()), fetch_all=True)
        else:
            if end_date:
                activities = db_manager.execute_query('''SELECT ba.id, u.username, a.name, ba.action, ba.started_at, ba.stopped_at, 
                           ba.duration_seconds, ba.cost_amount, ba.created_at
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE (ba.started_at >= %s AND ba.started_at < %s) OR (ba.stopped_at >= %s AND ba.stopped_at < %s)
                    ORDER BY ba.created_at DESC
                ''', (start_date.isoformat(), end_date.isoformat(), start_date.isoformat(), end_date.isoformat()), fetch_all=True)
            else:
                activities = db_manager.execute_query('''SELECT ba.id, u.username, a.name, ba.action, ba.started_at, ba.stopped_at, 
                           ba.duration_seconds, ba.cost_amount, ba.created_at
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE (ba.started_at >= %s OR ba.stopped_at >= %s)
                    ORDER BY ba.created_at DESC
                ''', (start_date.isoformat(), start_date.isoformat()), fetch_all=True)
    else:
        # Regular user sees only their activities for the period
        if end_date:
            activities = db_manager.execute_query('''SELECT ba.id, u.username, a.name, ba.action, ba.started_at, ba.stopped_at, 
                       ba.duration_seconds, ba.cost_amount, ba.created_at
                FROM billing_activities ba
                JOIN users u ON ba.user_id = u.id
                JOIN applications a ON ba.application_id = a.id
                WHERE ba.user_id = %s AND ((ba.started_at >= %s AND ba.started_at < %s) OR (ba.stopped_at >= %s AND ba.stopped_at < %s))
                ORDER BY ba.created_at DESC
            ''', (session['user_id'], start_date.isoformat(), end_date.isoformat(), start_date.isoformat(), end_date.isoformat()), fetch_all=True)
        else:
            activities = db_manager.execute_query('''SELECT ba.id, u.username, a.name, ba.action, ba.started_at, ba.stopped_at, 
                       ba.duration_seconds, ba.cost_amount, ba.created_at
                FROM billing_activities ba
                JOIN users u ON ba.user_id = u.id
                JOIN applications a ON ba.application_id = a.id
                WHERE ba.user_id = %s AND (ba.started_at >= %s OR ba.stopped_at >= %s)
                ORDER BY ba.created_at DESC
            ''', (session['user_id'], start_date.isoformat(), start_date.isoformat()), fetch_all=True)
    
    return jsonify([{
        'id': row[0],
        'username': row[1],
        'application': row[2],
        'action': row[3],
        'started_at': row[4],
        'stopped_at': row[5],
        'duration_seconds': row[6],
        'cost_amount': row[7],
        'created_at': row[8]
    } for row in activities])

@billing_bp.route('/api/billing/summary')
def get_billing_summary():
    """Get billing summary by period and user filter"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    period = request.args.get('period', 'month')  # day, week, month
    selected_user = request.args.get('user')  # user filter
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    is_admin = user and user[0] == 'admin'
    
    # Calculate date range
    now = datetime.now()
    if period == 'day':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = None
    elif period == 'week':
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = None
    elif period == 'previous_month':
        # Calculate previous month
        if now.month == 1:
            # If current month is January, previous month is December of previous year
            start_date = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            # Otherwise, just go to previous month
            start_date = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # month
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = None
    
    if is_admin:
        # Admin sees summary based on filters
        if selected_user:
            if end_date:
                summary = db_manager.execute_query('''SELECT u.username, a.name, SUM(ba.duration_seconds), SUM(ba.cost_amount)
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE u.username = %s AND ba.created_at >= %s AND ba.created_at < %s
                    GROUP BY u.username, a.name
                    ORDER BY u.username, a.name
                ''', (selected_user, start_date.isoformat(), end_date.isoformat()), fetch_all=True)
            else:
                summary = db_manager.execute_query('''SELECT u.username, a.name, SUM(ba.duration_seconds), SUM(ba.cost_amount)
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE u.username = %s AND ba.created_at >= %s
                    GROUP BY u.username, a.name
                    ORDER BY u.username, a.name
                ''', (selected_user, start_date.isoformat()), fetch_all=True)
        else:
            if end_date:
                summary = db_manager.execute_query('''SELECT u.username, a.name, SUM(ba.duration_seconds), SUM(ba.cost_amount)
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE ba.created_at >= %s AND ba.created_at < %s
                    GROUP BY u.username, a.name
                    ORDER BY u.username, a.name
                ''', (start_date.isoformat(), end_date.isoformat()), fetch_all=True)
            else:
                summary = db_manager.execute_query('''SELECT u.username, a.name, SUM(ba.duration_seconds), SUM(ba.cost_amount)
                    FROM billing_activities ba
                    JOIN users u ON ba.user_id = u.id
                    JOIN applications a ON ba.application_id = a.id
                    WHERE ba.created_at >= %s
                    GROUP BY u.username, a.name
                    ORDER BY u.username, a.name
                ''', (start_date.isoformat(),), fetch_all=True)
    else:
        # Regular user sees only their summary
        if end_date:
            summary = db_manager.execute_query('''SELECT u.username, a.name, SUM(ba.duration_seconds), SUM(ba.cost_amount)
                FROM billing_activities ba
                JOIN users u ON ba.user_id = u.id
                JOIN applications a ON ba.application_id = a.id
                WHERE ba.user_id = %s AND ba.created_at >= %s AND ba.created_at < %s
                GROUP BY u.username, a.name
                ORDER BY a.name
            ''', (session['user_id'], start_date.isoformat(), end_date.isoformat()), fetch_all=True)
        else:
            summary = db_manager.execute_query('''SELECT u.username, a.name, SUM(ba.duration_seconds), SUM(ba.cost_amount)
                FROM billing_activities ba
                JOIN users u ON ba.user_id = u.id
                JOIN applications a ON ba.application_id = a.id
                WHERE ba.user_id = %s AND ba.created_at >= %s
                GROUP BY u.username, a.name
                ORDER BY a.name
            ''', (session['user_id'], start_date.isoformat()), fetch_all=True)
    
    return jsonify([{
        'username': row[0],
        'application': row[1],
        'total_duration_seconds': row[2] or 0,
        'total_cost': row[3] or 0.0
    } for row in summary])

@billing_bp.route('/api/billing/costs')
def get_application_costs():
    """Get application costs (admin only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    costs_data = db_manager.execute_query('''SELECT a.id, a.name, ac.cost_per_day, ac.updated_at
        FROM applications a
        LEFT JOIN application_costs ac ON a.id = ac.application_id
        ORDER BY a.name
    ''', fetch_all=True)
    
    costs = [{
        'application_id': row[0],
        'application_name': row[1],
        'cost_per_day': row[2] or 1.0,
        'updated_at': row[3]
    } for row in costs_data]
    
    return jsonify(costs)

@billing_bp.route('/api/billing/costs/<int:app_id>', methods=['PUT'])
def update_application_cost(app_id):
    """Update application cost (admin only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json()
    cost_per_day = data.get('cost_per_day', 1.0)
    
    # Check if cost record exists
    existing = db_manager.execute_query(
        'SELECT COUNT(*) FROM application_costs WHERE application_id = %s', 
        (app_id,), fetch_one=True
    )
    
    if existing and existing[0] > 0:
        db_manager.execute_query('''UPDATE application_costs 
            SET cost_per_day = %s, updated_at = CURRENT_TIMESTAMP 
            WHERE application_id = %s
        ''', (cost_per_day, app_id))
    else:
        db_manager.execute_query('''INSERT INTO application_costs (application_id, cost_per_day) 
            VALUES (%s, %s)
        ''', (app_id, cost_per_day))
    
    return jsonify({'message': 'Cost updated successfully'})

@billing_bp.route('/api/billing/invoices')
def get_invoices():
    """Get invoices for the current user"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (user_id,), fetch_one=True
    )
    is_admin = user and user[0] == 'admin'
    
    if is_admin:
        # Admin sees all invoices
        invoices = db_manager.execute_query('''SELECT i.id, u.username, i.invoice_month, i.total_amount, i.status, 
                   i.payment_date, pm.payment_type, i.created_at
            FROM invoicing i
            JOIN users u ON i.user_id = u.id
            LEFT JOIN payment_modes pm ON i.payment_mode_id = pm.id
            ORDER BY i.invoice_month DESC, u.username
        ''', fetch_all=True)
    else:
        # Regular user sees only their invoices
        invoices = db_manager.execute_query('''SELECT i.id, u.username, i.invoice_month, i.total_amount, i.status, 
                   i.payment_date, pm.payment_type, i.created_at
            FROM invoicing i
            JOIN users u ON i.user_id = u.id
            LEFT JOIN payment_modes pm ON i.payment_mode_id = pm.id
            WHERE i.user_id = %s
            ORDER BY i.invoice_month DESC
        ''', (user_id,), fetch_all=True)
    
    return jsonify([{
        'id': row[0],
        'username': row[1],
        'invoice_month': row[2],
        'total_amount': row[3],
        'status': row[4],
        'payment_date': row[5],
        'payment_type': row[6],
        'created_at': row[7]
    } for row in invoices])

@billing_bp.route('/api/billing/users')
def get_billing_users():
    """Get list of users for billing filter (admin only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    # Get all users who have billing activities
    users = db_manager.execute_query('''SELECT DISTINCT u.username
        FROM users u
        JOIN billing_activities ba ON u.id = ba.user_id
        ORDER BY u.username
    ''', fetch_all=True)
    
    return jsonify([row[0] for row in users])

@billing_bp.route('/api/billing/invoices/months')
def get_available_months():
    """Get available months for invoice generation (admin only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    is_admin = user and user[0] == 'admin'
    
    if is_admin:
        selected_user = request.args.get('user')
        
        if selected_user:
            # Get months with billing activities for specific user
            activities = db_manager.execute_query('''SELECT DISTINCT TO_CHAR(ba.created_at, 'YYYY-MM') as month
                FROM billing_activities ba
                JOIN users u ON ba.user_id = u.id
                WHERE u.username = %s AND ba.cost_amount > 0
                ORDER BY month DESC
            ''', (selected_user,), fetch_all=True)

        else:
            # Get all months with billing activities
            activities = db_manager.execute_query('''SELECT DISTINCT TO_CHAR(created_at, 'YYYY-MM') as month
                FROM billing_activities
                WHERE cost_amount > 0
                ORDER BY month DESC
            ''', fetch_all=True)
    else:
        # Regular users see their own months
        activities = db_manager.execute_query('''SELECT DISTINCT TO_CHAR(created_at, 'YYYY-MM') as month
            FROM billing_activities
            WHERE user_id = %s AND cost_amount > 0
            ORDER BY month DESC
        ''', (session['user_id'],), fetch_all=True)
    
    months = [row[0] for row in activities]
    return jsonify(months)

@billing_bp.route('/api/billing/invoices/generate', methods=['POST'])
def generate_invoice():
    """Generate invoice for a specific month (admin only)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s', 
        (session['user_id'],), fetch_one=True
    )
    if not user or user[0] != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json()
    month = data.get('month')
    target_username = data.get('user')  # User to generate invoice for
    
    if not month:
        return jsonify({'error': 'Month is required'}), 400
    
    if not target_username:
        return jsonify({'error': 'User is required'}), 400
    
    # Get target user ID
    target_user = db_manager.execute_query(
        'SELECT id FROM users WHERE username = %s',
        (target_username,), fetch_one=True
    )
    
    if not target_user:
        return jsonify({'error': 'User not found'}), 400
    
    target_user_id = target_user[0]
    
    # Check if invoice already exists for this month
    existing = db_manager.execute_query(
        'SELECT id FROM invoicing WHERE user_id = %s AND invoice_month = %s',
        (target_user_id, month), fetch_one=True
    )
    
    if existing:
        return jsonify({'error': 'Invoice already exists for this month'}), 400
    
    # Debug: Check what activities exist for this user and month
    debug_activities = db_manager.execute_query('''SELECT ba.id, a.name, ba.cost_amount, ba.created_at, TO_CHAR(ba.created_at, 'YYYY-MM') as month_str
        FROM billing_activities ba
        JOIN applications a ON ba.application_id = a.id
        WHERE ba.user_id = %s AND TO_CHAR(ba.created_at, 'YYYY-MM') = %s
        ORDER BY ba.created_at
    ''', (target_user_id, month), fetch_all=True)

    
    logger = logging.getLogger('billing_routes')
    logger.info(f"Debug: Found {len(debug_activities)} activities for user {target_user_id} in month {month}")
    for activity in debug_activities:
        logger.info(f"Activity: {activity[1]}, cost: {activity[2]}, date: {activity[3]}, month: {activity[4]}")
    
    # Calculate total amount for the month
    total = db_manager.execute_query('''SELECT SUM(cost_amount) FROM billing_activities
        WHERE user_id = %s AND TO_CHAR(created_at, 'YYYY-MM') = %s AND cost_amount > 0
    ''', (target_user_id, month), fetch_one=True)
    
    total_amount = total[0] if total and total[0] else 0.0
    logger.info(f"Calculated total amount: {total_amount} for user {target_user_id} in month {month}")
    
    if total_amount <= 0:
        return jsonify({
            'error': 'No billable activities found for this month',
            'debug_info': f'Found {len(debug_activities)} activities but total amount is {total_amount}'
        }), 400
    
    # Create invoice
    invoice_id = db_manager.execute_query('''INSERT INTO invoicing (user_id, invoice_month, total_amount, status)
        VALUES (%s, %s, %s, 'unpaid')
    ''', (target_user_id, month, total_amount))
    
    return jsonify({
        'message': 'Invoice generated successfully',
        'invoice_id': invoice_id,
        'total_amount': total_amount
    })

@billing_bp.route('/api/billing/invoices/<int:invoice_id>/pdf')
def generate_invoice_pdf(invoice_id):
    """Generate PDF for an invoice"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    
    # Get invoice details
    invoice = db_manager.execute_query('''SELECT i.id, i.user_id, u.username, u.email, u.first_name, u.last_name,
               i.invoice_month, i.total_amount, i.status, i.payment_date,
               pm.payment_type, i.created_at
        FROM invoicing i
        JOIN users u ON i.user_id = u.id
        LEFT JOIN payment_modes pm ON i.payment_mode_id = pm.id
        WHERE i.id = %s AND (i.user_id = %s OR %s IN (SELECT id FROM users WHERE username = 'admin'))
    ''', (invoice_id, user_id, user_id), fetch_one=True)
    
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    
    # Get billing activities for this month
    activities = db_manager.execute_query('''SELECT ba.id, a.name, ba.action, ba.started_at, ba.stopped_at,
                ba.duration_seconds, ba.cost_amount, ba.created_at
        FROM billing_activities ba
        JOIN applications a ON ba.application_id = a.id
        WHERE ba.user_id = %s AND TO_CHAR(ba.created_at, 'YYYY-MM') = %s AND ba.cost_amount > 0
        ORDER BY ba.created_at
    ''', (invoice[1], invoice[6]), fetch_all=True)
    
    # Generate simple HTML invoice (could be enhanced with proper PDF generation)
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Invoice #{invoice_id}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .invoice-details {{ margin-bottom: 30px; }}
            .activities-table {{ width: 100%; border-collapse: collapse; }}
            .activities-table th, .activities-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            .activities-table th {{ background-color: #f2f2f2; }}
            .total {{ text-align: right; margin-top: 20px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>{PLTF_NAME} Invoice</h1>
            <h2>Invoice #{invoice_id}</h2>
        </div>
        
        <div class="invoice-details">
            <p><strong>Customer:</strong> {invoice[2]} ({invoice[4]} {invoice[5]})</p>
            <p><strong>Email:</strong> {invoice[3]}</p>
            <p><strong>Invoice Month:</strong> {invoice[6]}</p>
            <p><strong>Status:</strong> {invoice[8]}</p>
            <p><strong>Generated:</strong> {invoice[11]}</p>
        </div>
        
        <table class="activities-table">
            <thead>
                <tr>
                    <th>Application</th>
                    <th>Action</th>
                    <th>Date</th>
                    <th>Duration</th>
                    <th>Cost</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for activity in activities:
        duration = f"{-(-activity[5] // 60)}m" if activity[5] else "-"
        html_content += f"""
                <tr>
                    <td>{activity[1]}</td>
                    <td>{activity[2]}</td>
                    <td>{activity[7][:10]}</td>
                    <td>{duration}</td>
                    <td>${activity[6]:.4f}</td>
                </tr>
        """
    
    html_content += f"""
            </tbody>
        </table>
        
        <div class="total">
            <h3>Total Amount: ${invoice[7]:.2f}</h3>
        </div>
    </body>
    </html>
    """
    
    from flask import Response
    return Response(html_content, mimetype='text/html')

@billing_bp.route('/api/billing/invoices/<int:invoice_id>/pay', methods=['PUT'])
def mark_invoice_paid(invoice_id):
    """Mark an invoice as paid"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    
    # Check if user owns this invoice or is admin
    invoice = db_manager.execute_query(
        'SELECT user_id FROM invoicing WHERE id = %s',
        (invoice_id,), fetch_one=True
    )
    
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    
    # Check if user is admin
    user = db_manager.execute_query(
        'SELECT username FROM users WHERE id = %s',
        (user_id,), fetch_one=True
    )
    is_admin = user and user[0] == 'admin'
    
    if invoice[0] != user_id and not is_admin:
        return jsonify({'error': 'Access denied'}), 403
    
    # Update invoice status
    db_manager.execute_query('''UPDATE invoicing 
        SET status = 'paid', payment_date = CURRENT_TIMESTAMP
        WHERE id = %s
    ''', (invoice_id,))
    
@billing_bp.route('/api/billing/debug/<month>')
def debug_billing_data(month):
    """Debug endpoint to check billing data for a specific month"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    
    # Get all activities for this user and month
    activities = db_manager.execute_query('''SELECT ba.id, a.name, ba.action, ba.cost_amount, ba.duration_seconds,
                ba.created_at, TO_CHAR(ba.created_at, 'YYYY-MM') as month_str
        FROM billing_activities ba
        JOIN applications a ON ba.application_id = a.id
        WHERE ba.user_id = %s
        ORDER BY ba.created_at DESC
    ''', (user_id,), fetch_all=True)
    
    # Filter activities for the specific month
    month_activities = [a for a in activities if a[6] == month]
    
    # Calculate total
    total_with_cost = sum(a[3] for a in month_activities if a[3] and a[3] > 0)
    
    return jsonify({
        'user_id': user_id,
        'month': month,
        'total_activities': len(activities),
        'month_activities': len(month_activities),
        'activities_with_cost': len([a for a in month_activities if a[3] and a[3] > 0]),
        'calculated_total': total_with_cost,
        'activities': [{
            'id': a[0],
            'app': a[1],
            'action': a[2],
            'cost': a[3],
            'duration': a[4],
            'created_at': a[5],
            'month_str': a[6]
        } for a in month_activities]
    })

def record_billing_activity(user_id, application_name, action):
    """Record billing activity for application start/stop"""
    logger = logging.getLogger('billing_routes')
    
    try:
        logger.info(f"Recording billing activity: user_id={user_id}, app={application_name}, action={action}")
        
        # Get application ID
        app_result = db_manager.execute_query(
            'SELECT id FROM applications WHERE name = %s', 
            (application_name,), fetch_one=True
        )
        if not app_result:
            logger.error(f"record_billing_activity(): Application not found: {application_name}")
            return False
        
        application_id = app_result[0]
        logger.debug(f"record_billing_activity(): Found application_id: {application_id}")
        
        if action.upper() == 'START':
            # Record start activity
            result = db_manager.execute_query('''INSERT INTO billing_activities (user_id, application_id, action, started_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ''', (user_id, application_id, action))
            
            if result is not None:
                logger.info(f"record_billing_activity(): Successfully recorded START activity for {application_name}")
                return True
            else:
                logger.error(f"record_billing_activity(): Failed to record START activity for {application_name}")
                return False
        
        elif action.upper()  == 'STOP':
            # Find the most recent start activity for this user and app
            start_activity = db_manager.execute_query('''SELECT id, started_at FROM billing_activities
                WHERE user_id = %s AND application_id = %s AND (action = 'start' OR action = 'START') AND stopped_at IS NULL
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id, application_id), fetch_one=True)
            
            if start_activity:
                start_id, started_at = start_activity
                logger.debug(f"record_billing_activity(): Found matching START activity: {start_id}")
                
                # Calculate duration and cost
                if isinstance(started_at, str):
                    start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                else:
                    # Handle case where started_at is already a datetime object (PostgreSQL)
                    start_time = started_at
                
                # Ensure both datetimes are timezone-naive for comparison
                if start_time.tzinfo is not None:
                    start_time = start_time.replace(tzinfo=None)
                
                stop_time = datetime.now()
                duration_seconds = int((stop_time - start_time).total_seconds())
                
                # Get cost per day for this application
                cost_result = db_manager.execute_query(
                    'SELECT cost_per_day FROM application_costs WHERE application_id = %s', 
                    (application_id,), fetch_one=True
                )
                cost_per_day = cost_result[0] if cost_result else 1.0
                
                # Calculate cost (cost per day / 86400 seconds * duration)
                cost_amount = (cost_per_day / 86400) * duration_seconds
                
                logger.info(f"Calculated billing: duration={duration_seconds}s, cost=${cost_amount:.4f}")
                
                # Update the start activity with stop information
                update_result = db_manager.execute_query('''UPDATE billing_activities 
                    SET stopped_at = CURRENT_TIMESTAMP, duration_seconds = %s, cost_amount = %s
                    WHERE id = %s
                ''', (duration_seconds, cost_amount, start_id))
                
                if update_result is None:
                    logger.error(f"record_billing_activity(): Failed to update START activity {start_id} with STOP information")
            else:
                logger.warning(f"record_billing_activity(): No matching START activity found for STOP action: {application_name}")
            
            # Also record the stop activity
            result = db_manager.execute_query('''INSERT INTO billing_activities (user_id, application_id, action, stopped_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ''', (user_id, application_id, action))
            
            if result is not None:
                logger.info(f"record_billing_activity(): Successfully recorded STOP activity for {application_name}")
                return True
            else:
                logger.error(f"record_billing_activity(): Failed to record STOP activity for {application_name}")
                return False
        
        else:
            logger.warning(f"record_billing_activity(): Unknown action: {action}")
            return False
            
    except Exception as e:
        logger.error(f"record_billing_activity(): Error recording billing activity: {str(e)}")
        return False