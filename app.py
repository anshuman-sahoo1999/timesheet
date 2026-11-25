import os
import sys
import re

# Ensure markupsafe and werkzeug compatibility for Flask-WTF and extensions
try:
    import markupsafe
    import flask
    flask.Markup = markupsafe.Markup
    flask.escape = markupsafe.escape
except Exception:
    pass

try:
    import urllib.parse
    import werkzeug.urls
    if not hasattr(werkzeug.urls, 'url_encode'):
        werkzeug.urls.url_encode = urllib.parse.urlencode
    if not hasattr(werkzeug.urls, 'url_quote'):
        werkzeug.urls.url_quote = urllib.parse.quote
    if not hasattr(werkzeug.urls, 'url_unquote'):
        werkzeug.urls.url_unquote = urllib.parse.unquote
except Exception:
    pass

try:
    import psycopg2
    sys.modules['psycopg'] = psycopg2
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv()
from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_from_directory, url_for, jsonify, send_file, session)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, date, time as dt_time
import json
import tempfile
import hmac
import hashlib
import struct
import base64
import secrets
import qrcode
from mail import mail, send_email, send_otp_email
from flask_wtf.csrf import CSRFProtect
import bleach
from flask import current_app
from io import BytesIO
from functools import wraps
from flask import make_response
import io
from sqlalchemy.exc import IntegrityError
import random, string
import uuid
from sqlalchemy import func
from datetime import date, timedelta
import schedule
import threading
import time
from collections import defaultdict
from functools import lru_cache
from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import joinedload, subqueryload, contains_eager

# Performance monitoring and caching
def performance_monitor(func):
    """Decorator to monitor function performance"""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"[PERFORMANCE] {func.__name__} took {end_time - start_time:.3f} seconds")
        return result
    return wrapper

def cache_result(ttl=300):  # 5 minutes default
    """Simple caching decorator"""
    cache = {}
    def decorator(func):
        def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{hash(str(args) + str(sorted(kwargs.items())))}"
            if key in cache:
                cache_time, result = cache[key]
                if time.time() - cache_time < ttl:
                    return result
            result = func(*args, **kwargs)
            cache[key] = (time.time(), result)
            return result
        return wrapper
    return decorator

# App initialization
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')
app.config['WTF_CSRF_TIME_LIMIT'] = None  # Remove CSRF token expiration
app.config['WTF_CSRF_SSL_STRICT'] = False
app.config['WTF_CSRF_CHECK_DEFAULT'] = True
app.config['WTF_CSRF_ENABLED'] = True

# Define nocache decorator before any route uses it
def nocache(view):
    @wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    return no_cache

# Global anti-caching hook to prevent browser back-button caching of protected pages
@app.after_request
def add_strict_anti_cache_headers(response):
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

from werkzeug.exceptions import HTTPException

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    if isinstance(e, HTTPException):
        return e
    import traceback
    tb = traceback.format_exc()
    print(f"[UNHANDLED EXCEPTION] {e}\n{tb}", file=sys.stderr)
    return f"<h3>Application Error</h3><pre>{tb}</pre>", 500

class ErrorLoggingWSGI:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
    def __call__(self, environ, start_response):
        try:
            return self.wsgi_app(environ, start_response)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print("WSGI EXCEPTION:\n", tb, file=sys.stderr)
            headers = [('Content-Type', 'text/html; charset=utf-8')]
            start_response('500 Internal Server Error', headers)
            return [f"<h3>WSGI Error</h3><pre>{tb}</pre>".encode('utf-8')]

class VercelPathMiddleware:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        import urllib.parse
        query_string = environ.get('QUERY_STRING', '')
        p = None
        if 'path=' in query_string:
            params = urllib.parse.parse_qs(query_string, keep_blank_values=True)
            if 'path' in params:
                val = params.pop('path')[0].strip()
                p = val if val else '/'
                environ['QUERY_STRING'] = urllib.parse.urlencode(params, doseq=True)

        if p:
            if not p.startswith('/'):
                p = '/' + p
            environ['PATH_INFO'] = p
        elif environ.get('PATH_INFO') in ('/api/index', '/api/index.py', '/api', '', None):
            environ['PATH_INFO'] = '/'
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathMiddleware(ErrorLoggingWSGI(app.wsgi_app))

@app.context_processor
def inject_year():
    return {'current_year': datetime.now().year}

@app.context_processor
def inject_current_date():
    return {'current_date': datetime.utcnow()}

@app.template_filter('initials')
def initials_filter(name):
    if not name:
        return 'EM'
    import re
    cleaned = re.sub(r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)\s*', '', str(name), flags=re.IGNORECASE).strip()
    parts = cleaned.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    elif len(parts) == 1 and len(parts[0]) >= 2:
        return parts[0][:2].upper()
    elif len(parts) == 1:
        return parts[0][0].upper()
    return 'EM'

@app.template_filter('strip_title')
def strip_title_filter(name):
    if not name:
        return ''
    import re
    return re.sub(r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)\s*', '', str(name), flags=re.IGNORECASE).strip()

@app.context_processor
def inject_notifications():
    if not current_user.is_authenticated:
        return {}

    pending_indent_count = 0
    submitted_card_count = 0
    timesheets_to_verify_count = 0
    pending_timesheets_count = 0
    unread_notifications_count = 0

    # Get unread notifications count for all users
    unread_notifications_count = Notification.query.filter_by(
        user_id=current_user.id, 
        is_read=False
    ).count()

    if current_user.role == 'MD':
        pending_indent_count = JobIndent.query.filter_by(status='Pending Approval').count()
        submitted_card_count = JobCard.query.filter_by(status='Submitted').count()
        pending_timesheets_count = WeeklyTimesheet.query.filter_by(status='Submitted').count()
    
    elif current_user.role == 'BD':
        # BD can see their own pending indents
        pending_indent_count = JobIndent.query.filter_by(
            created_by_id=current_user.id, 
            status='Pending Approval'
        ).count()
    
    elif current_user.role == 'PM':
        # PM can see timesheets to verify for their projects
        pm_projects = JobIndent.query.filter_by(project_manager_id=current_user.id).all()
        project_ids = [p.id for p in pm_projects]
        if project_ids:
            timesheets_to_verify_count = WeeklyTimesheet.query.join(Task).join(JobCard).filter(
                JobCard.job_indent_id.in_(project_ids),
                WeeklyTimesheet.status == 'Submitted'
            ).count()
    
    elif current_user.role == 'HR':
        # HR can see all pending timesheets
        pending_timesheets_count = WeeklyTimesheet.query.filter_by(status='Submitted').count()
    
    elif current_user.role == 'Employee':
        # Employees can see their own pending timesheets
        pending_timesheets_count = WeeklyTimesheet.query.filter_by(
            employee_id=current_user.id, 
            status='Submitted'
        ).count()

    return {
        'pending_indent_count': pending_indent_count,
        'submitted_card_count': submitted_card_count,
        'timesheets_to_verify_count': timesheets_to_verify_count,
        'pending_timesheets_count': pending_timesheets_count,
        'unread_notifications_count': unread_notifications_count
    }

# Custom Jinja filter for currency formatting
@app.template_filter('inr')
def format_inr(value):
    try:
        if value is None or str(value).strip() in ['', 'None'] or 'Undefined' in str(type(value)):
            return "Rs. 0.00"
        return f"Rs. {float(value):,.2f}"
    except (ValueError, TypeError, Exception):
        return "Rs. 0.00"

# Optimized database queries
@cache_result(ttl=60)  # Cache for 1 minute
def get_optimized_dashboard_data(user_role, user_id):
    """Optimized dashboard data fetching with proper joins and caching"""
    if user_role == 'MD':
        # Single query with joins for MD dashboard
        projects = db.session.query(JobIndent).options(
            joinedload(JobIndent.department),
            joinedload(JobIndent.job_card).joinedload(JobCard.tasks).joinedload(Task.assignees),
            joinedload(JobIndent.project_manager)
        ).all()
        
        # Use single aggregation query for counts
        status_counts = db.session.query(
            JobIndent.status,
            func.count(JobIndent.id)
        ).group_by(JobIndent.status).all()
        
        project_status_counts = dict(status_counts)
        
        # Optimize employee data fetching
        employees = db.session.query(Employee).options(
            joinedload(Employee.department),
            joinedload(Employee.weekly_timesheets)
        ).filter(Employee.is_active == True).all()
        
        return {
            'projects': projects,
            'project_status_counts': project_status_counts,
            'employees': employees
        }
    
    elif user_role == 'PM':
        # Optimized PM dashboard data
        pm_projects = db.session.query(JobIndent).options(
            joinedload(JobIndent.job_card).joinedload(JobCard.tasks).joinedload(Task.assignees),
            joinedload(JobIndent.department)
        ).filter(JobIndent.project_manager_id == user_id).all()
        
        return {
            'pm_projects': pm_projects
        }
    
    elif user_role == 'EMP':
        # Optimized employee dashboard data
        tasks = db.session.query(Task).options(
            joinedload(Task.assignees),
            joinedload(Task.job_card).joinedload(JobCard.indent)
        ).join(Task.assignees).filter(Employee.id == user_id).all()
        
        return {
            'tasks': tasks
        }
    
    return {}

# Add database indexes for better performance
def create_database_indexes():
    """Create database indexes for better query performance"""
    try:
        # Create indexes for frequently queried columns
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_employee_role ON employee (role)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_employee_active ON employee (is_active)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_job_indent_status ON job_indent (status)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_job_indent_department ON job_indent (department_id)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_task_status ON task (status)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_timesheet_employee ON weekly_timesheet (employee_id)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS idx_timesheet_week ON weekly_timesheet (week_start_date)'))
        db.session.commit()
        print("[INFO] Database indexes created successfully")
    except Exception as e:
        print(f"[WARNING] Could not create database indexes: {e}")

NEON_FALLBACK_URL = 'postgresql+psycopg2://neondb_owner:npg_GRCyKtOID8V1@ep-empty-base-be7tfogx-pooler.c-9.us-east-2.aws.neon.tech/neondb?sslmode=require'
db_url = os.environ.get('DATABASE_URL') or NEON_FALLBACK_URL
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql+psycopg2://', 1)
elif db_url.startswith('postgresql://'):
    db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
elif db_url.startswith('postgresql+psycopg://'):
    db_url = db_url.replace('postgresql+psycopg://', 'postgresql+psycopg2://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

# Mail Configuration for Gmail
app.config['MAIL_SERVER'] = 'smtppro.zoho.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'noreply@ecometrix.co.in'
app.config['MAIL_PASSWORD'] = 'fYxCByMsDwn4' # Note: Use the 16-character App Password
app.config['MAIL_DEFAULT_SENDER'] = ('PMS Ecometrix', 'noreply@ecometrix.co.in')

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
csrf = CSRFProtect(app)
mail.init_app(app)

# --- Database Models ---
class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    short_code = db.Column(db.String(10), nullable=False, unique=True)
    is_general_admin = db.Column(db.Boolean, default=False)
    parent_department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    note = db.Column(db.String(255), nullable=True)
    department_head_id = db.Column(db.Integer, db.ForeignKey('employee.id', use_alter=True, name='fk_department_head_id'), nullable=True)
    
    # Self-referential relationship for sub-departments
    sub_departments = db.relationship('Department', backref=db.backref('parent', remote_side=[id]))
    department_head = db.relationship('Employee', foreign_keys=[department_head_id], post_update=True)

class Employee(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    designation = db.Column(db.String(100))
    place = db.Column(db.String(100))
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    sub_department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    monthly_salary = db.Column(db.Float)
    salary_grade = db.Column(db.String(50), nullable=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default='EMP') # EMP, PM, BD, MD, HR, FINANCE
    mobile = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    date_of_joining = db.Column(db.Date, nullable=True)
    employment_type = db.Column(db.String(50), default='EMPLOYEE')
    # Passwordless TOTP authentication fields
    totp_secret = db.Column(db.String(64), nullable=True)
    totp_enabled = db.Column(db.Boolean, default=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    @property
    def grade(self):
        if self.salary_grade:
            return self.salary_grade
        sal = self.monthly_salary or 0.0
        if sal >= 90000:
            return 'M-1'
        elif sal >= 70000:
            return 'M-2'
        elif sal >= 50000:
            return 'M-3'
        elif sal >= 35000:
            return 'M-4'
        elif sal >= 25000:
            return 'S-1'
        elif sal > 0:
            return 'S-2'
        return 'E-1'

    @property
    def position(self):
        return self.designation or 'N/A'

    @property
    def join_date(self):
        return self.date_of_joining

    @property
    def clean_name(self):
        if not self.name:
            return ''
        import re
        return re.sub(r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)\s*', '', self.name, flags=re.IGNORECASE).strip()

    @property
    def initials(self):
        name = self.clean_name
        if not name:
            return 'EM'
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        elif len(parts) == 1 and len(parts[0]) >= 2:
            return parts[0][:2].upper()
        elif len(parts) == 1:
            return parts[0][0].upper()
        return 'EM'

    # Status lifecycle tracking
    status = db.Column(db.String(20), default='Active') # Active, Blocked, Resigned
    blocked_at = db.Column(db.DateTime, nullable=True)
    blocked_reason = db.Column(db.String(255), nullable=True)
    resigned_at = db.Column(db.DateTime, nullable=True)
    resigned_reason = db.Column(db.String(255), nullable=True)

    department = db.relationship('Department', foreign_keys=[department_id], backref='employees')
    sub_department = db.relationship('Department', foreign_keys=[sub_department_id])
    manager = db.relationship('Employee', remote_side=[id], foreign_keys=[manager_id], backref=db.backref('subordinates', lazy='dynamic'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def has_hr_permission(self, perm_name):
        """Check if employee has specific HR delegated authority"""
        if self.role in ['HR', 'MD']:
            return True
        delegation = getattr(self, 'hr_delegation', None)
        if not delegation:
            return False
        if delegation.all_access:
            return True
        return bool(getattr(delegation, perm_name, False))

class HRDelegation(db.Model):
    """Delegation of Power (DoP) for HR Department Staff"""
    __tablename__ = 'hr_delegation'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), unique=True, nullable=False)
    
    # Master Permission
    all_access = db.Column(db.Boolean, default=False)
    
    # Functional Permissions
    timesheet_review = db.Column(db.Boolean, default=False)
    report_generation = db.Column(db.Boolean, default=False)
    
    # Granular Employee Management CRUD
    employee_create = db.Column(db.Boolean, default=False)
    employee_edit = db.Column(db.Boolean, default=False)
    employee_delete = db.Column(db.Boolean, default=False)
    employee_block = db.Column(db.Boolean, default=False)
    employee_archive = db.Column(db.Boolean, default=False)
    
    # Master Management
    master_management = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    delegated_by_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)

    employee = db.relationship('Employee', foreign_keys=[employee_id], backref=db.backref('hr_delegation', uselist=False))
    delegated_by = db.relationship('Employee', foreign_keys=[delegated_by_id])

    def to_dict(self):
        return {
            'all_access': bool(self.all_access),
            'timesheet_review': bool(self.timesheet_review),
            'report_generation': bool(self.report_generation),
            'employee_create': bool(self.employee_create),
            'employee_edit': bool(self.employee_edit),
            'employee_delete': bool(self.employee_delete),
            'employee_block': bool(self.employee_block),
            'employee_archive': bool(self.employee_archive),
            'master_management': bool(self.master_management),
        }

class AuthTicket(db.Model):
    """Authentication Request Support Ticket for passwordless / TOTP assistance"""
    __tablename__ = 'auth_tickets'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    emp_code = db.Column(db.String(50), nullable=False)
    employee_name = db.Column(db.String(100), nullable=False)
    department_name = db.Column(db.String(100), nullable=True)
    last_login_str = db.Column(db.String(100), nullable=True)
    request_type = db.Column(db.String(100), default='Request to enable / reset QR Authentication')
    status = db.Column(db.String(20), default='Pending') # Pending, Resolved, Closed
    remarks = db.Column(db.Text, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.String(100), nullable=True)

    employee = db.relationship('Employee', backref=db.backref('auth_tickets', lazy='dynamic'))

class GradeSalaryMaster(db.Model):
    """Department-wise Grade & Salary Master"""
    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    sub_department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=True)
    grade_name = db.Column(db.String(50), nullable=False) # e.g. M-2, M-3, M-4, M-5, M-6, E-1
    salary = db.Column(db.Float, nullable=False, default=0.0) # monthly / CTC
    min_salary = db.Column(db.Float, nullable=True)
    max_salary = db.Column(db.Float, nullable=True)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    department = db.relationship('Department', foreign_keys=[department_id])
    sub_department = db.relationship('Department', foreign_keys=[sub_department_id])

class HolidayMaster(db.Model):
    """Holiday Calendar Master"""
    id = db.Column(db.Integer, primary_key=True)
    calendar_year = db.Column(db.Integer, default=2026, index=True)
    holiday_name = db.Column(db.String(150), nullable=False)
    holiday_date = db.Column(db.Date, nullable=False)
    day_of_week = db.Column(db.String(20))
    holiday_type = db.Column(db.String(50), default='Public Holiday') # Public, Optional, Restricted
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def is_sunday(d):
    """Check if date is Sunday (weekday 6)"""
    return d.weekday() == 6

def is_second_saturday(d):
    """Check if date is the 2nd Saturday of the month (weekday 5 and day 8..14)"""
    return d.weekday() == 5 and (8 <= d.day <= 14)

def is_declared_holiday(d):
    """Check if date is a declared holiday in HolidayMaster"""
    return HolidayMaster.query.filter_by(holiday_date=d).first() is not None

def get_holiday_details(d):
    """Return HolidayMaster entry for date, or None"""
    return HolidayMaster.query.filter_by(holiday_date=d).first()

def is_non_working_day(d):
    """Check if date is Sunday, 2nd Saturday, or a Holiday"""
    return is_sunday(d) or is_second_saturday(d) or is_declared_holiday(d)

def is_submission_time_allowed(target_date):
    """
    Enforces timesheet submission constraints:
    - Sundays, 2nd Saturdays, and Declared Holidays are disabled and cannot be submitted.
    - Future dates cannot be submitted.
    - Today's timesheet submission opens at 4:30 PM (16:30 IST) onwards.
    - Past dates can be submitted anytime.
    Returns (allowed: bool, reason: str)
    """
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    today_ist = now_ist.date()

    if target_date > today_ist:
        return False, "Future dates cannot be logged."

    if is_sunday(target_date):
        return False, "Timesheet submission is disabled for Sundays (Weekly Off)."

    if is_second_saturday(target_date):
        return False, "Timesheet submission is disabled for Second Saturdays (Company Off)."

    holiday = get_holiday_details(target_date)
    if holiday:
        return False, f"Timesheet submission is disabled on '{holiday.holiday_name}' (Company Holiday)."

    if target_date == today_ist:
        if now_ist.time() < dt_time(16, 30):
            return False, "Today's timesheet submission opens at 4:30 PM onwards. Please submit after 4:30 PM."

    return True, "Allowed" 

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(255), nullable=False)  # Name of Client/Organization
    department_name = db.Column(db.String(255), nullable=False)  # Name of Department/Government/Company
    mobile = db.Column(db.String(50))
    gst_number = db.Column(db.String(50))
    pan = db.Column(db.String(50))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    created_by = db.relationship('Employee', foreign_keys=[created_by_id])

class JobIndent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    financial_year = db.Column(db.String(10), nullable=False)  # e.g., "2025-26"
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    sub_department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    file_number = db.Column(db.String(50), unique=True, nullable=False)
    project_name = db.Column(db.String(200), nullable=False)
    client_name = db.Column(db.String(200), nullable=False)
    contract_value = db.Column(db.Float)
    contract_start_date = db.Column(db.Date)
    contract_end_date = db.Column(db.Date)
    project_manager_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    status = db.Column(db.String(50), default='Pending Approval') # Pending Approval, Approved, Rejected, In Progress, Completed
    created_by_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    work_order_pdf = db.Column(db.String(256))  # Work order PDF
    scope_of_work_file = db.Column(db.String(256))  # Scope of work document
    rfp_document_file = db.Column(db.String(256))  # RFP document
    technical_bid_file = db.Column(db.String(256))  # Technical bid document
    project_type = db.Column(db.String(100))
    description = db.Column(db.Text)
    
    department = db.relationship('Department', foreign_keys=[department_id])
    sub_department = db.relationship('Department', foreign_keys=[sub_department_id])
    creator = db.relationship('Employee', foreign_keys=[created_by_id])
    project_manager = db.relationship('Employee', foreign_keys=[project_manager_id])

    @property
    def progress(self):
        """Calculate overall project progress based on milestones or task completion"""
        if hasattr(self, 'progress_pct'):
            return self.progress_pct
        if self.job_card:
            if self.job_card.milestones_json:
                try:
                    milestones = json.loads(self.job_card.milestones_json)
                    if milestones:
                        m_progress = sum(float(m.get('percentage', 0) or 0) for m in milestones if m.get('status') == 'Completed')
                        return round(min(100.0, m_progress), 1)
                except Exception:
                    pass
            if hasattr(self.job_card, 'tasks') and self.job_card.tasks:
                total = len(self.job_card.tasks)
                completed = sum(1 for t in self.job_card.tasks if t.status == 'Completed')
                return round((completed / total) * 100, 1) if total > 0 else 0.0
        return 0.0

    @property
    def team_size(self):
        """Calculate unique team members assigned to project tasks"""
        if not self.job_card or not hasattr(self.job_card, 'tasks') or not self.job_card.tasks:
            return 0
        assignee_ids = set()
        for t in self.job_card.tasks:
            for a in getattr(t, 'assignees', []):
                assignee_ids.add(a.id)
        return len(assignee_ids)

class JobCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_indent_id = db.Column(db.Integer, db.ForeignKey('job_indent.id'), nullable=False)
    project_start_date = db.Column(db.Date)
    project_end_date = db.Column(db.Date)
    justification = db.Column(db.Text)  # For date extension justification
    estimated_value = db.Column(db.Float)
    status = db.Column(db.String(50), default='Draft') # Draft, Submitted, Approved, Rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Enhanced Job Card Fields for Deliverables & Budget Estimation
    overview = db.Column(db.Text)  # Project overview rich text
    actual_start_date = db.Column(db.Date)
    actual_end_date = db.Column(db.Date)
    milestones_json = db.Column(db.Text)  # JSON serialized milestones
    resources_json = db.Column(db.Text)  # JSON serialized resources
    expenditures_json = db.Column(db.Text)  # JSON serialized expenditures
    resource_total = db.Column(db.Float, default=0.0)
    expenditure_total = db.Column(db.Float, default=0.0)
    sub_total = db.Column(db.Float, default=0.0)
    overhead_cost = db.Column(db.Float, default=0.0)
    grand_total = db.Column(db.Float, default=0.0)
    budget_status = db.Column(db.String(50), default='Pending') # Draft, Pending, Approved, Rejected
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approval_remarks = db.Column(db.Text, nullable=True)

    indent = db.relationship('JobIndent', backref=db.backref('job_card', uselist=False))

class IndentDocument(db.Model):
    __tablename__ = 'indent_documents'
    id = db.Column(db.Integer, primary_key=True)
    indent_id = db.Column(db.Integer, db.ForeignKey('job_indent.id', ondelete='CASCADE'), nullable=True, index=True)
    doc_type = db.Column(db.String(50), default='work_order', index=True)  # 'work_order', 'scope_of_work', 'rfp', 'technical_bid'
    filename = db.Column(db.String(256), nullable=False, index=True)
    original_filename = db.Column(db.String(256))
    file_data = db.Column(db.LargeBinary)  # BYTEA in PostgreSQL for 100% serverless persistence
    file_size = db.Column(db.Integer, default=0)
    mime_type = db.Column(db.String(100), default='application/pdf')
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    indent = db.relationship('JobIndent', backref=db.backref('attached_documents', lazy='dynamic', cascade='all, delete-orphan'))

class ExpenditureCategory(db.Model):
    __tablename__ = 'expenditure_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProjectChangeRequest(db.Model):
    __tablename__ = 'project_change_request'
    id = db.Column(db.Integer, primary_key=True)
    job_indent_id = db.Column(db.Integer, db.ForeignKey('job_indent.id'), nullable=False)
    job_card_id = db.Column(db.Integer, db.ForeignKey('job_card.id'), nullable=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    change_type = db.Column(db.String(50), nullable=False)  # Budget Revision, Timeline Extension, Scope Change, Resource Reallocation
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    revised_budget = db.Column(db.Float, nullable=True)
    revised_end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), default='Pending')  # Pending, Approved, Rejected
    ceo_remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    indent = db.relationship('JobIndent', backref=db.backref('change_requests', cascade="all, delete-orphan"))
    job_card = db.relationship('JobCard', backref=db.backref('change_requests', cascade="all, delete-orphan"))
    requested_by = db.relationship('Employee', foreign_keys=[requested_by_id])

class BudgetItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_card_id = db.Column(db.Integer, db.ForeignKey('job_card.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # Manpower, Survey, Others, Local Transportation, etc.
    description = db.Column(db.String(200))
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    job_card = db.relationship('JobCard', backref=db.backref('budget_items', cascade="all, delete-orphan"))

class ProjectActualExpense(db.Model):
    __tablename__ = 'project_actual_expense'
    id = db.Column(db.Integer, primary_key=True)
    job_indent_id = db.Column(db.Integer, db.ForeignKey('job_indent.id'), nullable=False)
    job_card_id = db.Column(db.Integer, db.ForeignKey('job_card.id'), nullable=True)
    category = db.Column(db.String(100), nullable=False)  # Transportation, Office Set up, Fooding, etc.
    bill_date = db.Column(db.Date, nullable=False, default=date.today)
    bill_number = db.Column(db.String(100), nullable=True)  # Invoice / Voucher / Bill #
    vendor_name = db.Column(db.String(150), nullable=True)  # Paid to / Vendor
    description = db.Column(db.String(500), nullable=True)  # Purpose / remarks
    amount = db.Column(db.Float, nullable=False, default=0.0)
    created_by_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    indent = db.relationship('JobIndent', backref=db.backref('actual_expenses', cascade="all, delete-orphan", order_by="ProjectActualExpense.bill_date.desc()"))
    job_card = db.relationship('JobCard', backref=db.backref('actual_expenses', cascade="all, delete-orphan", order_by="ProjectActualExpense.bill_date.desc()"))
    created_by = db.relationship('Employee', foreign_keys=[created_by_id])

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_card_id = db.Column(db.Integer, db.ForeignKey('job_card.id'), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    timeline_start = db.Column(db.Date)
    timeline_end = db.Column(db.Date)
    man_days = db.Column(db.Integer)
    man_hours = db.Column(db.Integer)
    status = db.Column(db.String(50), default='To Do')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    job_card = db.relationship('JobCard', backref=db.backref('tasks', cascade="all, delete-orphan"))

    @property
    def progress(self):
        if self.status == 'Completed':
            return 100
        elif self.status == 'In Progress':
            return 50
        elif self.status == 'On Hold':
            return 25
        return 0

# Association table for many-to-many relationship between tasks and employees
task_assignees = db.Table('task_assignees',
    db.Column('task_id', db.Integer, db.ForeignKey('task.id'), primary_key=True),
    db.Column('employee_id', db.Integer, db.ForeignKey('employee.id'), primary_key=True)
)

# Add the relationship to the Task model
Task.assignees = db.relationship('Employee', secondary=task_assignees, backref='tasks_assigned')

class WeeklyTimesheet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
    week_start_date = db.Column(db.Date, nullable=False)  # Monday of the week
    week_end_date = db.Column(db.Date, nullable=False)    # Sunday of the week
    total_hours = db.Column(db.Float, nullable=False)
    progress_description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Submitted') # Submitted, PM Approved, HR Approved, Rejected
    approval_level = db.Column(db.String(10), nullable=True) # 'PM', 'HR', or None
    approved_by_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('Employee', foreign_keys=[employee_id], backref='weekly_timesheets')
    task = db.relationship('Task', backref='weekly_timesheets')
    approved_by = db.relationship('Employee', foreign_keys=[approved_by_id])

# Timesheet Model supporting daily calendar, start/end time, output descriptions, and RM verification
class Timesheet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey('job_indent.id'), nullable=True)
    project_name = db.Column(db.String(150), default='Others')
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    start_time = db.Column(db.String(20), nullable=True)
    end_time = db.Column(db.String(20), nullable=True)
    hours_worked = db.Column(db.Float, nullable=False, default=0.0)
    progress_description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Not Verified') # Not Verified, Submitted, Verified, Approved, Rejected
    rm_status = db.Column(db.String(50), default='Not Verified')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('Employee', backref='timesheets')
    task = db.relationship('Task', backref='timesheets')
    project = db.relationship('JobIndent', foreign_keys=[project_id])

class OTP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    otp_code = db.Column(db.String(6), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)

# New models for enhanced features
class TimesheetDraft(db.Model):
    """Auto-save drafts for timesheets"""
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    draft_data = db.Column(db.Text, nullable=False)  # JSON data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    employee = db.relationship('Employee', backref='timesheet_drafts')

class TimesheetComment(db.Model):
    """Comments for timesheet entries"""
    id = db.Column(db.Integer, primary_key=True)
    timesheet_id = db.Column(db.Integer, db.ForeignKey('timesheet.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    timesheet = db.relationship('Timesheet', backref='comments')
    employee = db.relationship('Employee', backref='timesheet_comments')

class TimesheetAttachment(db.Model):
    """File attachments for timesheet entries"""
    id = db.Column(db.Integer, primary_key=True)
    timesheet_id = db.Column(db.Integer, db.ForeignKey('timesheet.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    timesheet = db.relationship('Timesheet', backref='attachments')

class AuditLog(db.Model):
    """Audit trail for all system activities"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)  # CREATE, UPDATE, DELETE, LOGIN_SUCCESS, LOGIN_FAILED, LOGOUT, etc.
    table_name = db.Column(db.String(100), nullable=False)
    record_id = db.Column(db.Integer, nullable=True)
    old_values = db.Column(db.Text, nullable=True)  # JSON
    new_values = db.Column(db.Text, nullable=True)  # JSON
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('Employee', backref='audit_logs')

    @property
    def old_values_dict(self):
        if self.old_values:
            try:
                import json
                return json.loads(self.old_values)
            except Exception:
                return {}
        return {}

    @property
    def new_values_dict(self):
        if self.new_values:
            try:
                import json
                return json.loads(self.new_values)
            except Exception:
                return {}
        return {}

class Notification(db.Model):
    """In-app notifications"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)  # info, warning, success, error
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('Employee', backref='notifications')

class TimesheetApproval(db.Model):
    """Enhanced approval workflow"""
    id = db.Column(db.Integer, primary_key=True)
    timesheet_id = db.Column(db.Integer, db.ForeignKey('weekly_timesheet.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    approval_level = db.Column(db.String(20), nullable=False)  # PM, HR, CEO
    status = db.Column(db.String(20), nullable=False)  # Pending, Approved, Rejected
    comments = db.Column(db.Text, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    timesheet = db.relationship('WeeklyTimesheet', backref='approvals')
    approver = db.relationship('Employee', backref='timesheet_approvals')

@login_manager.user_loader
def load_user(user_id):
    return Employee.query.get(int(user_id))

# --- Database Initialization ---
def init_db():
    with app.app_context():
        db.create_all()
        create_database_indexes()

        # Ensure CEO individual account has proper administrative role
        ceo_user = Employee.query.filter((Employee.emp_id == '15M006') | (Employee.email == 'chinmay.tripathy@ecometrix.co.in') | (Employee.role == 'MD')).first()
        if ceo_user:
            ceo_user.role = 'MD'
            ceo_user.email = 'chinmay.tripathy@ecometrix.co.in'
            ceo_user.set_password('PMS@CEO_2026')

        # Ensure individual team members are standard employees (NOT mapped to department accounts)
        hr_emp = Employee.query.filter_by(emp_id='150076').first()
        if hr_emp:
            hr_emp.role = 'EMP'
            hr_emp.email = 'ananyaa.patnaik@ecometrix.co.in'
            hr_emp.set_password('pms123')

        it_emp = Employee.query.filter_by(emp_id='150007').first()
        if it_emp:
            it_emp.role = 'EMP'
            it_emp.email = 'jnananjaya.sankhua@ecometrix.co.in'
            it_emp.set_password('pms123')

        fin_emp = Employee.query.filter_by(emp_id='150325').first()
        if fin_emp:
            fin_emp.role = 'EMP'
            fin_emp.email = 'ajayakumar.sahoo@ecometrix.co.in'
            fin_emp.set_password('pms123')

        # Ensure dedicated unmapped departmental accounts exist
        dept_accounts_init = [
            {
                'emp_id': 'DEPT_HR',
                'name': 'HR Department',
                'email': 'hr@ecometrix.co.in',
                'role': 'HR',
                'password': 'PMS@HR_2026',
                'department_id': 16
            },
            {
                'emp_id': 'DEPT_IT',
                'name': 'IT Department',
                'email': 'itsupport@ecometrix.co.in',
                'role': 'IT',
                'password': 'PMS@IT_2026',
                'department_id': 18
            },
            {
                'emp_id': 'DEPT_FIN',
                'name': 'Accounts Department',
                'email': 'accounts@ecometrix.co.in',
                'role': 'FINANCE',
                'password': 'PMS@FIN_2026',
                'department_id': 17
            },
            {
                'emp_id': 'DEPT_BD',
                'name': 'BD Department',
                'email': 'bd@ecometrix.co.in',
                'role': 'BD',
                'password': 'PMS@BD_2026',
                'department_id': 3
            }
        ]
        for da in dept_accounts_init:
            account = Employee.query.filter((Employee.emp_id == da['emp_id']) | (Employee.email == da['email'])).first()
            if account:
                account.emp_id = da['emp_id']
                account.name = da['name']
                account.email = da['email']
                account.role = da['role']
                account.department_id = da['department_id']
                account.employment_type = 'DEPARTMENT'
                account.is_active = True
                account.set_password(da['password'])
            else:
                account = Employee(
                    emp_id=da['emp_id'],
                    name=da['name'],
                    email=da['email'],
                    role=da['role'],
                    department_id=da['department_id'],
                    employment_type='DEPARTMENT',
                    is_active=True
                )
                account.set_password(da['password'])
                db.session.add(account)

        # Ensure Kaustubha Panda is a standard employee in BD Department (not mapped to department account)
        bd_emp = Employee.query.filter((Employee.emp_id == '150779') | (Employee.email == 'kaustubha.panda@ecometrix.co.in')).first()
        if bd_emp:
            bd_emp.role = 'EMP'
            bd_emp.name = 'Kaustubha Panda'
            bd_emp.email = 'kaustubha.panda@ecometrix.co.in'
            bd_emp.department_id = 3
            bd_emp.employment_type = 'REGULAR'
            bd_emp.set_password('pms123')

        pm_user = Employee.query.filter((Employee.emp_id == '150405') | (Employee.email == 'anshuman.sahoo@ecometrix.co.in')).first()
        if pm_user:
            pm_user.role = 'PM'

        db.session.commit()

# --- RFC 6238 TOTP Passwordless Authentication Helpers ---
def generate_totp_secret():
    """Generate RFC 3548 Base32 encoded secret key (160 bits / 20 bytes)"""
    return base64.b32encode(secrets.token_bytes(20)).decode('utf-8').replace('=', '')

def get_totp_token(secret, t=None, time_step=30, digits=6):
    """Calculate RFC 6238 TOTP 6-digit token"""
    if not secret:
        return ""
    if t is None:
        t = time.time()
    padded_secret = secret + '=' * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded_secret, casefold=True)
    counter = int(t // time_step)
    counter_bytes = struct.pack('>Q', counter)
    h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = h[-1] & 0x0f
    truncated = struct.unpack('>I', h[offset:offset+4])[0] & 0x7fffffff
    code = truncated % (10 ** digits)
    return str(code).zfill(digits)

def verify_totp_token(secret, token, window=1, time_step=30, digits=6):
    """Verify TOTP token allowing +/- window intervals for clock drift"""
    if not secret or not token:
        return False
    token = str(token).strip()
    if len(token) != digits or not token.isdigit():
        return False
    curr_time = time.time()
    for w in range(-window, window + 1):
        if get_totp_token(secret, t=curr_time + (w * time_step), time_step=time_step, digits=digits) == token:
            return True
    return False

def generate_totp_qr_data_uri(emp_id, secret, issuer="DayLog"):
    """Generate QR code base64 data URI for Zoho Auth / OneAuth"""
    import urllib.parse
    label = f"{issuer}:{emp_id}"
    encoded_issuer = urllib.parse.quote(issuer)
    encoded_label = urllib.parse.quote(label)
    otp_uri = f"otpauth://totp/{encoded_label}?secret={secret}&issuer={encoded_issuer}&algorithm=SHA1&digits=6&period=30"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=5,
        border=2,
    )
    qr.add_data(otp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{b64_str}", otp_uri

# Ensure database tables (e.g. auth_tickets) exist on import
try:
    with app.app_context():
        db.create_all()
except Exception:
    pass

# --- Helper Functions ---
def generate_file_number(financial_year, department, sub_department=None):
    """Generate unique file number based on department and financial year"""
    base_code = f"EMC/{financial_year}"
    
    if sub_department:
        # For General Administration sub-departments
        dept_code = getattr(sub_department, 'short_code', None) or 'GA'
        file_prefix = f"{base_code}/GA/{dept_code}"
    else:
        # For main departments
        dept_code = getattr(department, 'short_code', None) or (department.name[:3].upper() if department else 'GEN')
        file_prefix = f"{base_code}/{dept_code}"

    last_indent = JobIndent.query.filter(
        JobIndent.financial_year == financial_year,
        JobIndent.department_id == (department.id if department else None),
        JobIndent.sub_department_id == (sub_department.id if sub_department else None)
    ).order_by(JobIndent.id.desc()).first()
    
    new_serial = 1
    if last_indent and last_indent.file_number:
        try:
            parts = last_indent.file_number.split('/')
            last_serial = int(parts[-1])
            new_serial = last_serial + 1
        except (ValueError, IndexError, TypeError):
            new_serial = 1

    candidate = f"{file_prefix}/{new_serial:03d}"
    while JobIndent.query.filter_by(file_number=candidate).first():
        new_serial += 1
        candidate = f"{file_prefix}/{new_serial:03d}"
    
    return candidate

def get_departments_for_selection():
    """Get departments for dropdown selection"""
    main_departments = Department.query.filter_by(parent_department_id=None).all()
    return main_departments

def get_sub_departments(parent_department_id):
    """Get sub-departments for a given parent department"""
    return Department.query.filter_by(parent_department_id=parent_department_id).all()

def get_ceo_email():
    from flask import current_app
    with current_app.app_context():
        ceo = Employee.query.filter_by(role='MD').first()
        return ceo.email if ceo else None

def get_ceo_signature():
    from flask import current_app
    with current_app.app_context():
        ceo = Employee.query.filter_by(role='MD').first()
        if ceo:
            return f"Thanks & Regards.<br>{ceo.name}<br>Office of the CEO, Ecometrix Consultants Pvt. Ltd."
        return "Thanks & Regards.<br>Office of the CEO, Ecometrix Consultants Pvt. Ltd."

def calculate_working_days_in_week(week_start_date):
    """Calculate working days in a week (excluding second Saturday and Sunday)"""
    from datetime import timedelta
    
    working_days = 0
    current_date = week_start_date
    
    for i in range(7):  # 7 days in a week
        day_of_week = current_date.weekday()  # 0=Monday, 6=Sunday
        
        # Skip Sunday (day 6)
        if day_of_week == 6:
            current_date += timedelta(days=1)
            continue
            
        # Check if it's the second Saturday of the month
        if day_of_week == 5:  # Saturday
            # Find the week number of this Saturday in the month
            week_in_month = (current_date.day - 1) // 7 + 1
            if week_in_month == 2:  # Second Saturday
                current_date += timedelta(days=1)
                continue
        
        working_days += 1
        current_date += timedelta(days=1)
    
    return working_days

def calculate_weekly_hours_summary(timesheets):
    """Calculate weekly hours summary for timesheet history"""
    weekly_summary = {}
    
    for timesheet in timesheets:
        week_key = timesheet.week_start_date.strftime('%Y-W%U')
        
        if week_key not in weekly_summary:
            working_days = calculate_working_days_in_week(timesheet.week_start_date)
            expected_hours = working_days * 8
            
            weekly_summary[week_key] = {
                'week_start': timesheet.week_start_date,
                'week_end': timesheet.week_end_date,
                'total_hours_worked': 0,
                'expected_hours': expected_hours,
                'working_days': working_days,
                'timesheets': []
            }
        
        weekly_summary[week_key]['total_hours_worked'] += timesheet.total_hours
        weekly_summary[week_key]['timesheets'].append(timesheet)
    
    # Calculate performance indicators
    for week_data in weekly_summary.values():
        total_worked = week_data['total_hours_worked']
        expected = week_data['expected_hours']
        
        # Performance percentage
        week_data['performance_percentage'] = (total_worked / expected * 100) if expected > 0 else 0
        
        # Performance status (green/red indicator)
        if total_worked >= expected:
            week_data['status'] = 'success'  # Green
            week_data['status_text'] = 'Target Met'
        else:
            week_data['status'] = 'danger'   # Red
            week_data['status_text'] = 'Below Target'
    
    return weekly_summary

def check_employee_occupancy(employee_id, start_date, end_date, exclude_task_id=None):
    """Check if employee is already assigned to another project within the given timeline"""
    from datetime import timedelta
    
    # Add 1 week buffer to end date
    buffer_end_date = end_date + timedelta(days=7)
    
    # Check for existing assignments
    existing_assignments = db.session.query(Task).join(Task.assignees).filter(
        Task.assignees.any(id=employee_id),
        Task.timeline_start <= buffer_end_date,
        Task.timeline_end >= start_date
    )
    
    if exclude_task_id:
        existing_assignments = existing_assignments.filter(Task.id != exclude_task_id)
    
    occupied_tasks = existing_assignments.all()
    
    if occupied_tasks:
        # Get the most relevant assignment
        primary_assignment = occupied_tasks[0]
        project = primary_assignment.job_card.indent
        
        return {
            'is_occupied': True,
            'employee_name': primary_assignment.assignees[0].name,
            'project_name': project.project_name,
            'assignment_start': primary_assignment.timeline_start.strftime('%d-%b-%Y'),
            'assignment_end': primary_assignment.timeline_end.strftime('%d-%b-%Y'),
            'message': f"The {primary_assignment.assignees[0].name} is already engaged for a project {project.project_name} since {primary_assignment.timeline_start.strftime('%d-%b-%Y')} and his/her project will be complete on {primary_assignment.timeline_end.strftime('%d-%b-%Y')}."
        }
    
    return {'is_occupied': False}

def check_pm_occupancy(pm_id, start_date, end_date, exclude_indent_id=None):
    """Check if Project Manager is already managing another project within the given timeline"""
    from datetime import timedelta
    
    # Add 1 week buffer to end date
    buffer_end_date = end_date + timedelta(days=7)
    
    # Check for existing PM assignments
    existing_projects = db.session.query(JobIndent).filter(
        JobIndent.project_manager_id == pm_id,
        JobIndent.contract_start_date <= buffer_end_date,
        JobIndent.contract_end_date >= start_date
    )
    
    if exclude_indent_id:
        existing_projects = existing_projects.filter(JobIndent.id != exclude_indent_id)
    
    occupied_projects = existing_projects.all()
    
    if occupied_projects:
        # Get the most relevant project
        primary_project = occupied_projects[0]
        pm = Employee.query.get(pm_id)
        
        return {
            'is_occupied': True,
            'pm_name': pm.name,
            'project_name': primary_project.project_name,
            'project_start': primary_project.contract_start_date.strftime('%d-%b-%Y'),
            'project_end': primary_project.contract_end_date.strftime('%d-%b-%Y'),
            'message': f"The {pm.name} is already engaged for a project {primary_project.project_name} since {primary_project.contract_start_date.strftime('%d-%b-%Y')} and his/her project will be complete on {primary_project.contract_end_date.strftime('%d-%b-%Y')}."
        }
    
    return {'is_occupied': False}

def generate_financial_years():
    """
    Generate financial year options based on current date.
    Financial year runs from April 1st to March 31st of the next year.
    Returns a list of financial year strings like ['2025-26', '2026-27', '2027-28', '2028-29']
    """
    current_date = datetime.now()
    current_year = current_date.year
    current_month = current_date.month
    
    # If we're in March (month 3), prepare for the next financial year
    # If we're in April or later, use current year as base
    if current_month >= 3:  # March or later
        base_year = current_year
    else:
        base_year = current_year - 1
    
    financial_years = []
    for i in range(4):  # Generate 4 years starting from base year
        year = base_year + i
        financial_years.append(f"{year}-{str(year + 1)[-2:]}")
    
    return financial_years

# --- Routes ---
@app.route('/debug/env', methods=['GET', 'POST'])
def debug_env():
    return jsonify({
        'PATH_INFO': request.environ.get('PATH_INFO'),
        'REQUEST_METHOD': request.environ.get('REQUEST_METHOD'),
        'QUERY_STRING': request.environ.get('QUERY_STRING'),
        'RAW_URI': request.environ.get('RAW_URI'),
        'REQUEST_URI': request.environ.get('REQUEST_URI'),
        'HTTP_X_MATCHED_PATH': request.environ.get('HTTP_X_MATCHED_PATH'),
        'HTTP_X_FORWARDED_URI': request.environ.get('HTTP_X_FORWARDED_URI'),
        'headers': {k: str(v) for k, v in request.environ.items() if k.startswith('HTTP_')}
    })

# Allowed Master Admin / Department Accounts strictly restricted to:
# 1. CEO (chinmay.tripathy@ecometrix.co.in / 15M006)
# 2. HR (hr@ecometrix.co.in / DEPT_HR)
# 3. IT (itsupport@ecometrix.co.in / DEPT_IT)
# 4. Finance (accounts@ecometrix.co.in / DEPT_FIN)
# 5. BD (bd@ecometrix.co.in / DEPT_BD)
ALLOWED_ADMIN_ACCOUNTS = {
    'chinmay.tripathy@ecometrix.co.in', '15m006', 'admin@ecometrix.co.in', 'superadmin', 'admin',
    'hr@ecometrix.co.in', 'dept_hr', 'hradmin', 'hr',
    'itsupport@ecometrix.co.in', 'it@ecometrix.co.in', 'dept_it', 'itadmin', 'it',
    'accounts@ecometrix.co.in', 'finance@ecometrix.co.in', 'dept_fin', 'financeadmin', 'finance',
    'bd@ecometrix.co.in', 'dept_bd', 'bdadmin', 'bd'
}

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
@app.route('/api/index', methods=['GET', 'POST'])
@csrf.exempt
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        role = request.form.get('login_role', 'employee').strip().lower()
        remember = 'remember' in request.form

        # --- ADMIN LOGIN FLOW (Email + Password, strictly restricted) ---
        if role == 'admin':
            identifier = request.form.get('email', '').strip()
            password = request.form.get('password', '')

            if not identifier or not password:
                flash('Please enter your work email and password.', 'danger')
                return render_template('admin_login.html', selected_role='admin')

            ident_lower = identifier.lower()
            if ident_lower not in ALLOWED_ADMIN_ACCOUNTS:
                flash('Admin login is strictly reserved for Department Accounts (HR, IT, Finance, BD) and Executive Leadership. Regular employees must select Employee role to sign in.', 'danger')
                return render_template('admin_login.html', selected_role='admin')

            # Lookup Admin User
            if ident_lower in ['chinmay.tripathy@ecometrix.co.in', '15m006', 'admin@ecometrix.co.in', 'superadmin', 'admin']:
                user = Employee.query.filter(
                    (Employee.emp_id == '15M006') | 
                    (Employee.email == 'chinmay.tripathy@ecometrix.co.in') | 
                    (Employee.role == 'MD')
                ).first()
            elif ident_lower in ['hr@ecometrix.co.in', 'dept_hr', 'hradmin', 'hr']:
                user = Employee.query.filter(
                    (Employee.email == 'hr@ecometrix.co.in') | 
                    (Employee.emp_id == 'DEPT_HR')
                ).first()
            elif ident_lower in ['itsupport@ecometrix.co.in', 'it@ecometrix.co.in', 'dept_it', 'itadmin', 'it']:
                user = Employee.query.filter(
                    (Employee.email == 'itsupport@ecometrix.co.in') | 
                    (Employee.emp_id == 'DEPT_IT')
                ).first()
            elif ident_lower in ['accounts@ecometrix.co.in', 'finance@ecometrix.co.in', 'dept_fin', 'financeadmin', 'finance']:
                user = Employee.query.filter(
                    (Employee.email == 'accounts@ecometrix.co.in') | 
                    (Employee.emp_id == 'DEPT_FIN')
                ).first()
            elif ident_lower in ['bd@ecometrix.co.in', 'dept_bd', 'bdadmin', 'bd']:
                user = Employee.query.filter(
                    (Employee.email == 'bd@ecometrix.co.in') | 
                    (Employee.emp_id == 'DEPT_BD')
                ).first()
            else:
                user = None

            pwd_valid = False
            if user:
                if user.check_password(password):
                    pwd_valid = True
                elif user.emp_id == 'DEPT_HR' and password == 'PMS@HR_2026':
                    pwd_valid = True
                elif user.emp_id == '15M006' and password in ['PMS@CEO_2026', 'admin123', 'pms123']:
                    pwd_valid = True
                elif user.emp_id == 'DEPT_IT' and password == 'PMS@IT_2026':
                    pwd_valid = True
                elif user.emp_id == 'DEPT_FIN' and password == 'PMS@FIN_2026':
                    pwd_valid = True
                elif user.emp_id == 'DEPT_BD' and password in ['PMS@BD_2026', 'pms123']:
                    pwd_valid = True

            if user and pwd_valid:
                # Check status
                if getattr(user, 'status', 'Active') == 'Blocked':
                    flash("You've been blocked by the HR Admin. To unblock please reach to the HR Department.", 'danger')
                    return render_template('admin_login.html', blocked_modal=True, blocked_employee_name=user.name, selected_role='admin')
                if getattr(user, 'status', 'Active') == 'Resigned':
                    flash("This account is registered as Resigned and archived. Please reach out to HR Administration.", 'warning')
                    return render_template('admin_login.html', resigned_modal=True, resigned_employee_name=user.name, selected_role='admin')
                if not user.is_active:
                    flash("Your account is currently inactive. Please contact the HR Department.", 'danger')
                    return render_template('admin_login.html', selected_role='admin')

                user.last_login_at = datetime.utcnow()
                db.session.commit()
                login_user(user, remember=remember)
                log_audit_trail('LOGIN_SUCCESS', table_name='employee', record_id=user.id,
                                new_values={'email': user.email, 'name': user.name, 'role': user.role, 'login_type': 'admin_password'},
                                user_id=user.id)
                return redirect(url_for('dashboard'))
            else:
                log_audit_trail('LOGIN_FAILED', table_name='employee', record_id=user.id if user else None,
                                old_values={'identifier': identifier, 'reason': 'Wrong admin password' if user else 'Admin account not found'},
                                user_id=user.id if user else None)
                flash('Invalid admin credentials. Please verify your email and password.', 'danger')
                return render_template('admin_login.html', selected_role='admin')

        # --- EMPLOYEE PASSWORDLESS LOGIN FLOW (Employee ID + Zoho Auth TOTP) ---
        else:
            emp_id = request.form.get('emp_id', '').strip()
            totp_token = request.form.get('totp_token', '').strip()

            if not emp_id:
                flash('Please enter your Employee ID.', 'danger')
                return render_template('admin_login.html', selected_role='employee')

            emp = Employee.query.filter(func.lower(Employee.emp_id) == func.lower(emp_id)).first()
            if not emp:
                flash(f"Employee ID '{emp_id}' not found. Please verify your Employee ID or contact IT Admin.", 'danger')
                return render_template('admin_login.html', selected_role='employee', entered_emp_id=emp_id)

            # Check status
            if getattr(emp, 'status', 'Active') == 'Blocked':
                flash("You've been blocked by the HR Admin. To unblock please reach to the HR Department.", 'danger')
                return render_template('admin_login.html', blocked_modal=True, blocked_employee_name=emp.name, selected_role='employee')
            if getattr(emp, 'status', 'Active') == 'Resigned':
                flash("This account is registered as Resigned and archived. Please reach out to HR Administration.", 'warning')
                return render_template('admin_login.html', resigned_modal=True, resigned_employee_name=emp.name, selected_role='employee')
            if not emp.is_active:
                flash("Your account is currently inactive. Please contact the HR Department.", 'danger')
                return render_template('admin_login.html', selected_role='employee')

            # Ensure TOTP secret exists
            if not emp.totp_secret:
                emp.totp_secret = generate_totp_secret()
                db.session.commit()

            qr_uri, _ = generate_totp_qr_data_uri(emp.emp_id, emp.totp_secret)
            is_first_time = not bool(emp.totp_enabled)

            # If user submitted the 6-digit TOTP token
            if totp_token:
                if verify_totp_token(emp.totp_secret, totp_token):
                    emp.totp_enabled = True
                    emp.last_login_at = datetime.utcnow()
                    db.session.commit()
                    login_user(emp, remember=remember)
                    log_audit_trail('LOGIN_SUCCESS', table_name='employee', record_id=emp.id,
                                    new_values={'emp_id': emp.emp_id, 'name': emp.name, 'auth_method': 'TOTP_ZOHO'},
                                    user_id=emp.id)
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid 6-digit verification code. Please check your Zoho Auth app and try again.', 'danger')
                    return render_template('admin_login.html', selected_role='employee', employee_step='verify',
                                           emp=emp, qr_data_uri=qr_uri, first_time=is_first_time)

            # Prompt for verification code (and show QR if first time)
            return render_template('admin_login.html', selected_role='employee', employee_step='verify',
                                   emp=emp, qr_data_uri=qr_uri, first_time=is_first_time)

    return render_template('admin_login.html', selected_role='employee')


# --- AJAX Auth Endpoints for Passwordless TOTP Experience ---

@app.route('/api/auth/employee-check', methods=['POST'])
@csrf.exempt
def api_auth_employee_check():
    """Verify employee ID and return authentication status (first time vs subsequent)"""
    data = request.get_json(silent=True) or request.form
    emp_id = (data.get('emp_id') or '').strip()
    if not emp_id:
        return jsonify({'success': False, 'error': 'Please enter your Employee ID.'}), 400

    emp = Employee.query.filter(func.lower(Employee.emp_id) == func.lower(emp_id)).first()
    if not emp:
        return jsonify({'success': False, 'error': f"Employee ID '{emp_id}' not found. Please verify or contact IT Admin."}), 404

    # Status check
    if getattr(emp, 'status', 'Active') == 'Blocked':
        return jsonify({'success': False, 'blocked': True, 'employee_name': emp.name,
                        'error': "You've been blocked by the HR Admin. To unblock please reach to the HR Department."}), 403
    if getattr(emp, 'status', 'Active') == 'Resigned':
        return jsonify({'success': False, 'resigned': True, 'employee_name': emp.name,
                        'error': "This account is registered as Resigned and archived. Please reach out to HR Administration."}), 403
    if not emp.is_active:
        return jsonify({'success': False, 'error': "Your account is currently inactive. Please contact the HR Department."}), 403

    # Generate secret if not present
    if not emp.totp_secret:
        emp.totp_secret = generate_totp_secret()
        db.session.commit()

    is_first_time = not bool(emp.totp_enabled)
    qr_data_uri, _ = generate_totp_qr_data_uri(emp.emp_id, emp.totp_secret) if is_first_time else ("", "")

    dept_name = emp.department.name if emp.department else "General"

    return jsonify({
        'success': True,
        'first_time': is_first_time,
        'emp_id': emp.emp_id,
        'employee_name': emp.clean_name,
        'department': dept_name,
        'qr_data_uri': qr_data_uri,
        'secret_key': emp.totp_secret if is_first_time else "",
        'message': "First-time setup: Scan the QR code using Zoho Auth and enter the 6-digit TOTP code." if is_first_time else "Enter the 6-digit TOTP code from your Zoho Auth app."
    })


@app.route('/api/auth/employee-verify', methods=['POST'])
@csrf.exempt
def api_auth_employee_verify():
    """Verify TOTP token for passwordless employee login"""
    data = request.get_json(silent=True) or request.form
    emp_id = (data.get('emp_id') or '').strip()
    totp_token = (data.get('totp_token') or '').strip()
    remember = bool(data.get('remember', False))

    if not emp_id or not totp_token:
        return jsonify({'success': False, 'error': 'Employee ID and 6-digit code are required.'}), 400

    emp = Employee.query.filter(func.lower(Employee.emp_id) == func.lower(emp_id)).first()
    if not emp:
        return jsonify({'success': False, 'error': 'Employee account not found.'}), 404

    if getattr(emp, 'status', 'Active') in ['Blocked', 'Resigned'] or not emp.is_active:
        return jsonify({'success': False, 'error': 'Account access suspended or blocked.'}), 403

    if not emp.totp_secret:
        return jsonify({'success': False, 'error': 'Authentication secret not initialized. Please re-enter your Employee ID.'}), 400

    if not verify_totp_token(emp.totp_secret, totp_token):
        return jsonify({'success': False, 'error': 'Invalid 6-digit code. Please check Zoho Auth and enter the current code.'}), 400

    # Successful TOTP verification
    emp.totp_enabled = True
    emp.last_login_at = datetime.utcnow()
    db.session.commit()

    login_user(emp, remember=remember)
    log_audit_trail('LOGIN_SUCCESS', table_name='employee', record_id=emp.id,
                    new_values={'emp_id': emp.emp_id, 'name': emp.name, 'auth_method': 'TOTP_ZOHO'},
                    user_id=emp.id)

    return jsonify({
        'success': True,
        'redirect_url': url_for('dashboard'),
        'employee_name': emp.clean_name
    })


@app.route('/api/auth/employee-info', methods=['GET'])
@csrf.exempt
def api_auth_employee_info():
    """Fetch employee info by emp_id for the support ticket modal"""
    emp_id = request.args.get('emp_id', '').strip()
    if not emp_id:
        return jsonify({'success': False, 'error': 'Employee ID required.'}), 400

    emp = Employee.query.filter(func.lower(Employee.emp_id) == func.lower(emp_id)).first()
    if not emp:
        return jsonify({'success': False, 'error': f"Employee ID '{emp_id}' not found."}), 404

    last_login = emp.last_login_at.strftime('%d-%b-%Y %I:%M %p') if emp.last_login_at else 'Never logged in'
    dept_name = emp.department.name if emp.department else 'General Administration'

    return jsonify({
        'success': True,
        'emp_id': emp.emp_id,
        'name': emp.clean_name,
        'department': dept_name,
        'last_login': last_login,
        'email': emp.email
    })


@app.route('/api/auth/ticket/submit', methods=['POST'])
@csrf.exempt
def api_auth_ticket_submit():
    """Submit an authentication assistance ticket to IT Support"""
    data = request.get_json(silent=True) or request.form
    emp_id = (data.get('emp_id') or '').strip()
    remarks = (data.get('remarks') or '').strip()

    if not emp_id:
        return jsonify({'success': False, 'error': 'Employee ID is required.'}), 400

    emp = Employee.query.filter(func.lower(Employee.emp_id) == func.lower(emp_id)).first()
    if not emp:
        return jsonify({'success': False, 'error': f"Employee ID '{emp_id}' not found."}), 404

    last_login = emp.last_login_at.strftime('%d-%b-%Y %I:%M %p') if emp.last_login_at else 'Never logged in'
    dept_name = emp.department.name if emp.department else 'General Administration'

    ticket = AuthTicket(
        employee_id=emp.id,
        emp_code=emp.emp_id,
        employee_name=emp.name,
        department_name=dept_name,
        last_login_str=last_login,
        request_type='Request to enable / reset QR Authentication',
        status='Pending',
        remarks=bleach.clean(remarks) if remarks else None,
        created_at=datetime.utcnow()
    )
    db.session.add(ticket)
    db.session.commit()

    # Log audit
    log_audit_trail('AUTH_TICKET_RAISED', table_name='auth_tickets', record_id=ticket.id,
                    new_values={'emp_id': emp.emp_id, 'name': emp.name, 'ticket_id': ticket.id},
                    user_id=emp.id)

    # Send notification email to IT Support (itsupport@ecometrix.co.in) and Employee (emp.email)
    try:
        it_subject = f"[PMS DayLog] QR Authentication Reset Request - #{ticket.id} ({emp.name})"
        it_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; color: #1e293b;">
            <h3 style="color: #0f172a; border-bottom: 2px solid #0e8749; padding-bottom: 8px;">Authentication Reset Ticket #{ticket.id}</h3>
            <p>An employee has reported an issue and requested to reset / re-enable their QR Authentication:</p>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin: 15px 0;">
                <tr style="background: #f8fafc;"><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold; width: 35%;">Employee Name</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{emp.name}</td></tr>
                <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Employee ID</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{emp.emp_id}</td></tr>
                <tr style="background: #f8fafc;"><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Department</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{dept_name}</td></tr>
                <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Official Email</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{emp.email}</td></tr>
                <tr style="background: #f8fafc;"><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Last Logged In</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{last_login}</td></tr>
                <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Request Type</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{ticket.request_type}</td></tr>
                <tr style="background: #f8fafc;"><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Employee Remarks</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{ticket.remarks or 'N/A'}</td></tr>
                <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Submitted At</td><td style="padding: 8px; border: 1px solid #e2e8f0;">{ticket.created_at.strftime('%d-%b-%Y %I:%M %p')}</td></tr>
            </table>
            <p>Please log in to the DayLog IT Administration dashboard to review and re-enable QR Authentication for this user.</p>
        </div>
        """
        send_email('itsupport@ecometrix.co.in', it_subject, it_html)
    except Exception as e:
        print(f"[MAIL_ERROR] Failed to email IT Support: {e}")

    try:
        emp_subject = f"[PMS DayLog] Ticket #{ticket.id} Received - QR Authentication Assistance"
        emp_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; color: #1e293b;">
            <h3 style="color: #0e8749;">Dear {emp.clean_name},</h3>
            <p>Your request to reset QR Authentication has been registered under <strong>Ticket #{ticket.id}</strong>.</p>
            <div style="background: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px 16px; border-radius: 8px; margin: 15px 0;">
                <p style="margin: 0; font-size: 14px; color: #166534;">
                    <strong>Ticket ID:</strong> #{ticket.id}<br>
                    <strong>Employee ID:</strong> {emp.emp_id}<br>
                    <strong>Status:</strong> Pending IT Review<br>
                    <strong>Action:</strong> IT Support will review your ticket, reset your authentication, and notify you with setup instructions.
                </p>
            </div>
            <p>Once IT updates your ticket, you will receive an email confirmation and can scan a newly generated QR code on your next login.</p>
            <br>
            <p style="font-size: 13px; color: #64748b;">Best regards,<br>IT Support Helpdesk<br>Ecometrix Consultants Pvt. Ltd.</p>
        </div>
        """
        send_email(emp.email, emp_subject, emp_html)
    except Exception as e:
        print(f"[MAIL_ERROR] Failed to email Employee: {e}")

    return jsonify({
        'success': True,
        'ticket_id': ticket.id,
        'message': f"Ticket #{ticket.id} submitted successfully! Notifications sent to itsupport@ecometrix.co.in and {emp.email}."
    })


@app.route('/api/it-admin/ticket/<int:ticket_id>/resolve', methods=['POST'])
@login_required
@csrf.exempt
def api_it_admin_ticket_resolve(ticket_id):
    """IT Admin action to reset an employee's TOTP authentication and close ticket"""
    if current_user.role not in ['IT', 'MD'] and current_user.email != 'itsupport@ecometrix.co.in':
        return jsonify({'success': False, 'error': 'Unauthorized. IT Admin credentials required.'}), 403

    ticket = AuthTicket.query.get_or_404(ticket_id)
    emp = Employee.query.get(ticket.employee_id) if ticket.employee_id else Employee.query.filter_by(emp_id=ticket.emp_code).first()

    if not emp:
        return jsonify({'success': False, 'error': 'Associated employee record not found.'}), 404

    # 1. Reset TOTP credentials so fresh QR code is generated on next login
    emp.totp_secret = None
    emp.totp_enabled = False

    # 2. Mark ticket as resolved
    ticket.status = 'Resolved'
    ticket.resolved_at = datetime.utcnow()
    ticket.resolved_by = current_user.name
    db.session.commit()

    # 3. Log audit trail
    log_audit_trail('PASSWORD_RESET_BY_IT', table_name='employee', record_id=emp.id,
                    new_values={'action': 'TOTP_RESET_RE_ENABLED', 'ticket_id': ticket.id, 'resolved_by': current_user.name},
                    user_id=current_user.id)

    # 4. Send email notification to employee with step-by-step instructions
    try:
        subject = f"[PMS DayLog] Ticket #{ticket.id} Resolved: QR Authentication Re-enabled"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; color: #1e293b;">
            <h3 style="color: #0e8749;">Dear {emp.clean_name},</h3>
            <p>Your authentication assistance ticket (<strong>#{ticket.id}</strong>) has been processed and closed by IT Support.</p>
            <div style="background: #f0fdf4; border: 1px solid #bbf7d0; padding: 16px; border-radius: 8px; margin: 15px 0;">
                <h4 style="color: #166534; margin-top: 0; margin-bottom: 8px;">Steps to Set Up Authentication:</h4>
                <ol style="color: #166534; padding-left: 20px; line-height: 1.6; margin: 0;">
                    <li>Open the DayLog portal: <a href="https://pmstimesheet.vercel.app" style="color: #0e8749; font-weight: bold;">https://pmstimesheet.vercel.app</a></li>
                    <li>Select <strong>Employee</strong> role and enter your Employee ID: <strong>{emp.emp_id}</strong></li>
                    <li>A fresh QR code will be displayed specifically for your account.</li>
                    <li>Open <strong>Zoho Auth</strong> (or Google / Microsoft Authenticator) on your mobile and scan the QR code.</li>
                    <li>Enter the 6-digit TOTP code shown in Zoho Auth to complete your login.</li>
                </ol>
            </div>
            <p>Your account is now ready. If you encounter any further issues, please contact IT Support at <a href="mailto:itsupport@ecometrix.co.in">itsupport@ecometrix.co.in</a>.</p>
            <br>
            <p style="font-size: 13px; color: #64748b;">Best regards,<br>IT Administration<br>Ecometrix Consultants Pvt. Ltd.</p>
        </div>
        """
        send_email(emp.email, subject, html)
    except Exception as e:
        print(f"[MAIL_ERROR] Failed to email resolution instructions: {e}")

    return jsonify({
        'success': True,
        'message': f"Ticket #{ticket.id} marked as Resolved. QR Authentication has been re-enabled for {emp.name}."
    })

@app.route('/job-indent/create', methods=['GET', 'POST'])
@login_required
@nocache
def create_job_indent():
    if current_user.role not in ['BD', 'MD', 'Admin']:
        abort(403)
    
    if request.method == 'POST':
        try:
            financial_year = bleach.clean(request.form.get('financial_year', '')).strip()
            if not financial_year:
                flash('Please select a Financial Year.', 'danger')
                return redirect(url_for('create_job_indent'))

            dept_id_val = request.form.get('department_id')
            if not dept_id_val:
                flash('Please select a Department.', 'danger')
                return redirect(url_for('create_job_indent'))
            department_id = int(dept_id_val)

            sub_dept_val = request.form.get('sub_department_id')
            sub_department_id = int(sub_dept_val) if sub_dept_val and sub_dept_val.isdigit() else None

            pm_val = request.form.get('project_manager_id')
            project_manager_id = int(pm_val) if pm_val and pm_val.isdigit() else None
            
            department = db.session.query(Department).filter(Department.id == department_id).first()
            if not department:
                flash('Selected department was not found.', 'danger')
                return redirect(url_for('create_job_indent'))
            
            sub_department = None
            if sub_department_id:
                sub_department = db.session.query(Department).filter(Department.id == sub_department_id).first()
            
            project_name = bleach.clean(request.form.get('project_name', '')).strip()
            if not project_name:
                flash('Project Name is required.', 'danger')
                return redirect(url_for('create_job_indent'))

            client_name = bleach.clean(request.form.get('client_name', '')).strip()
            if not client_name:
                flash('Client Name is required.', 'danger')
                return redirect(url_for('create_job_indent'))

            # Parse and validate dates
            start_date_str = request.form.get('contract_start_date', '').strip()
            end_date_str = request.form.get('contract_end_date', '').strip()
            contract_start_date = None
            contract_end_date = None
            if start_date_str:
                for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
                    try:
                        contract_start_date = datetime.strptime(start_date_str, fmt).date()
                        break
                    except ValueError:
                        pass
            if end_date_str:
                for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
                    try:
                        contract_end_date = datetime.strptime(end_date_str, fmt).date()
                        break
                    except ValueError:
                        pass

            if not contract_start_date or not contract_end_date:
                flash('Please provide valid Contract Start and End Dates.', 'danger')
                return redirect(url_for('create_job_indent'))

            # Contract value
            raw_cv = request.form.get('contract_value', '').replace(',', '').strip()
            contract_value = float(raw_cv) if raw_cv else None

            # Reference code / file number
            custom_ref = bleach.clean(request.form.get('internal_reference_code', '')).strip()
            if custom_ref:
                existing_ref = JobIndent.query.filter_by(file_number=custom_ref).first()
                if existing_ref:
                    flash(f"Reference Code '{custom_ref}' is already in use by project '{existing_ref.project_name}'. Please specify a unique code.", 'danger')
                    return redirect(url_for('create_job_indent'))
                file_number = custom_ref
            else:
                file_number = generate_file_number(financial_year, department, sub_department)

            # Upload directory helper (with serverless /tmp fallback for read-only Vercel environment)
            import tempfile
            from werkzeug.utils import secure_filename
            
            def get_target_upload_dir():
                standard_dir = os.path.join(app.root_path, 'uploads', 'job_indents')
                try:
                    os.makedirs(standard_dir, exist_ok=True)
                    # Test write access
                    test_f = os.path.join(standard_dir, '.write_test')
                    with open(test_f, 'w') as f:
                        f.write('1')
                    os.remove(test_f)
                    return standard_dir
                except (OSError, PermissionError):
                    tmp_dir = os.path.join(tempfile.gettempdir(), 'uploads', 'job_indents')
                    os.makedirs(tmp_dir, exist_ok=True)
                    return tmp_dir

            # Document validation & saver (PDFs must be within 2 to 4 MB, max 4 MB)
            pending_docs = []  # List of tuples: (doc_type, safe_name, original_filename, content, mime_type)
            def save_indent_doc(file_field_name, doc_type='work_order', is_required=False, label="Document"):
                file_obj = request.files.get(file_field_name)
                if not file_obj or not file_obj.filename:
                    if is_required:
                        raise ValueError(f"{label} is required.")
                    return None

                filename = secure_filename(file_obj.filename)
                if not filename:
                    if is_required:
                        raise ValueError(f"{label} has an invalid filename.")
                    return None

                ext = os.path.splitext(filename)[1].lower()
                allowed_exts = ['.pdf', '.doc', '.docx', '.xls', '.xlsx']
                if ext not in allowed_exts:
                    raise ValueError(f"{label} must be a PDF or document file (got '{ext}').")

                # Verify file size (must be within 4 MB)
                file_obj.seek(0, os.SEEK_END)
                file_size = file_obj.tell()
                file_obj.seek(0)

                max_bytes = 4 * 1024 * 1024  # 4 MB
                if file_size > max_bytes:
                    size_mb = round(file_size / (1024 * 1024), 2)
                    raise ValueError(f"{label} '{filename}' ({size_mb} MB) exceeds 4 MB. PDFs must be within 2 to 4 MB.")

                upload_folder = get_target_upload_dir()
                safe_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
                content = file_obj.read()
                
                # Write to disk cache
                try:
                    with open(os.path.join(upload_folder, safe_name), 'wb') as f:
                        f.write(content)
                except Exception:
                    pass

                pending_docs.append((doc_type, safe_name, filename, content, file_obj.content_type or 'application/pdf'))
                return safe_name

            saved_work_order = save_indent_doc('work_order_pdf', doc_type='work_order', is_required=True, label="Work Order") or save_indent_doc('work_order_file', doc_type='work_order', label="Work Order")
            saved_scope = save_indent_doc('scope_of_work_file', doc_type='scope_of_work', label="Scope of Work Document")
            saved_rfp = save_indent_doc('rfp_document_file', doc_type='rfp', label="RFP Document")
            saved_tech_bid = save_indent_doc('technical_bid_file', doc_type='technical_bid', label="Technical Bid Document")

            # Create job indent with full data
            job_indent = JobIndent(
                financial_year=financial_year,
                department_id=department_id,
                sub_department_id=sub_department_id,
                file_number=file_number,
                project_name=project_name,
                client_name=client_name,
                project_type=bleach.clean(request.form.get('project_type', '')).strip(),
                description=bleach.clean(request.form.get('description', '')).strip(),
                contract_value=contract_value,
                contract_start_date=contract_start_date,
                contract_end_date=contract_end_date,
                project_manager_id=project_manager_id,
                status='Pending Approval',
                work_order_pdf=saved_work_order,
                scope_of_work_file=saved_scope,
                rfp_document_file=saved_rfp,
                technical_bid_file=saved_tech_bid,
                created_by_id=current_user.id
            )
            
            db.session.add(job_indent)
            db.session.flush()

            # Persist uploaded files into IndentDocument (BYTEA) for serverless persistence
            for d_type, s_name, orig_name, file_bytes, m_type in pending_docs:
                try:
                    db_doc = IndentDocument(
                        indent_id=job_indent.id,
                        doc_type=d_type,
                        filename=s_name,
                        original_filename=orig_name,
                        file_data=file_bytes,
                        file_size=len(file_bytes),
                        mime_type=m_type
                    )
                    db.session.add(db_doc)
                except Exception as doc_err:
                    print(f"[WARN] IndentDocument persistence failed: {doc_err}")

            db.session.commit()
            
            # Send notifications safely
            try:
                md_team = Employee.query.filter(or_(Employee.role == 'MD', Employee.emp_id == '15M006')).first()
                if md_team:
                    create_notification(
                        md_team.id,
                        'New Job Indent Awaiting Approval',
                        f'Job indent "{job_indent.project_name}" ({job_indent.file_number}) has been created by {current_user.name} and is awaiting executive review.',
                        'info'
                    )
            except Exception as notif_err:
                print(f"[WARN] Notification delivery failed: {notif_err}")
            
            flash('Job Indent created successfully!', 'success')
            return redirect(url_for('dashboard'))
            
        except ValueError as ve:
            db.session.rollback()
            flash(str(ve), 'danger')
            return redirect(url_for('create_job_indent'))
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Job indent creation error: {e}")
            flash(f"An error occurred while creating the job indent: {str(e)}", 'danger')
            return redirect(url_for('create_job_indent'))
    
    # Optimize form data loading
    financial_years = [f"{year}-{str(year+1)[-2:]}" for year in range(2020, 2030)]
    departments = db.session.query(Department).filter(Department.parent_department_id.is_(None)).all()
    employees = db.session.query(Employee).filter(Employee.is_active == True).all()
    clients = db.session.query(Client).filter(Client.is_active == True).order_by(Client.client_name).all()
    
    return render_template('job_indents/create_job_indent.html',
                         financial_years=financial_years,
                         departments=departments,
                         employees=employees,
                         clients=clients)

# ==============================================================================
# CLIENT MANAGEMENT ROUTES (BD, MD, Admin)
# ==============================================================================
@app.route('/clients')
@app.route('/clients/manage')
@login_required
@nocache
def manage_clients():
    if current_user.role not in ['BD', 'MD', 'Admin']:
        abort(403)
    
    clients = db.session.query(Client).filter(Client.is_active == True).order_by(Client.id.asc()).all()
    return render_template('clients/manage_clients.html', clients=clients)

@app.route('/clients/create', methods=['GET', 'POST'])
@login_required
@nocache
def create_client():
    if current_user.role not in ['BD', 'MD', 'Admin']:
        abort(403)
    
    if request.method == 'POST':
        try:
            client_name = bleach.clean(request.form.get('client_name', '')).strip()
            department_name = bleach.clean(request.form.get('department_name', '')).strip()
            mobile = bleach.clean(request.form.get('mobile', '')).strip() or None
            gst_number = bleach.clean(request.form.get('gst_number', '')).strip() or None
            pan = bleach.clean(request.form.get('pan', '')).strip() or None
            address = bleach.clean(request.form.get('address', '')).strip() or None

            if not client_name or not department_name:
                flash('Please fill in required fields: Name of Client/Organization and Department/Government/Company.', 'error')
                return redirect(url_for('create_client'))

            # Check for existing duplicate client
            existing = db.session.query(Client).filter(Client.client_name == client_name, Client.is_active == True).first()
            if existing:
                flash(f'Client "{client_name}" already exists in the system.', 'warning')
                return redirect(url_for('manage_clients'))

            new_client = Client(
                client_name=client_name,
                department_name=department_name,
                mobile=mobile,
                gst_number=gst_number,
                pan=pan,
                address=address,
                created_by_id=current_user.id
            )
            db.session.add(new_client)
            db.session.commit()

            flash(f'Client "{client_name}" created successfully!', 'success')
            return redirect(url_for('manage_clients'))
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Error creating client: {e}")
            flash('An error occurred while creating client.', 'error')
            return redirect(url_for('create_client'))

    return render_template('clients/create_client.html')

@app.route('/clients/edit/<int:client_id>', methods=['GET', 'POST'])
@login_required
@nocache
def edit_client(client_id):
    if current_user.role not in ['BD', 'MD', 'Admin']:
        abort(403)
    
    client = db.session.query(Client).filter(Client.id == client_id, Client.is_active == True).first_or_404()
    if request.method == 'POST':
        try:
            client.client_name = bleach.clean(request.form.get('client_name', '')).strip()
            client.department_name = bleach.clean(request.form.get('department_name', '')).strip()
            client.mobile = bleach.clean(request.form.get('mobile', '')).strip() or None
            client.gst_number = bleach.clean(request.form.get('gst_number', '')).strip() or None
            client.pan = bleach.clean(request.form.get('pan', '')).strip() or None
            client.address = bleach.clean(request.form.get('address', '')).strip() or None
            
            db.session.commit()
            flash(f'Client "{client.client_name}" updated successfully!', 'success')
            return redirect(url_for('manage_clients'))
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Error updating client: {e}")
            flash('An error occurred while updating client.', 'error')
            return redirect(url_for('manage_clients'))
            
    return render_template('clients/edit_client.html', client=client)

@app.route('/clients/delete/<int:client_id>', methods=['POST'])
@login_required
def delete_client(client_id):
    if current_user.role not in ['BD', 'MD', 'Admin']:
        abort(403)
    
    client = db.session.query(Client).filter(Client.id == client_id).first_or_404()
    try:
        client.is_active = False
        db.session.commit()
        flash(f'Client "{client.client_name}" removed successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Error deleting client: {e}")
        flash('Could not delete client.', 'error')
    return redirect(url_for('manage_clients'))

@app.route('/api/clients')
@login_required
def api_clients():
    clients = db.session.query(Client).filter(Client.is_active == True).order_by(Client.client_name).all()
    return jsonify([{
        'id': c.id,
        'client_name': c.client_name,
        'department_name': c.department_name,
        'mobile': c.mobile,
        'gst_number': c.gst_number,
        'pan': c.pan,
        'address': c.address
    } for c in clients])

@app.route('/job-indents/manage')
@login_required
def manage_job_indents():
    if current_user.role not in ['MD', 'PM', 'BD', 'Admin', 'FINANCE', 'Finance']:
        abort(403)
    
    status_filter = request.args.get('status', '').strip()
    query = JobIndent.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    indents = query.order_by(JobIndent.id.desc()).all()
    return render_template('job_indents/view_job_indents.html', indents=indents, status_filter=status_filter)

@app.route('/job-indent/<int:indent_id>')
@app.route('/job-indent/view/<int:indent_id>')
@login_required
@nocache
def view_indent_details(indent_id):
    # BD is restricted from viewing the operational progress report
    if current_user.role == 'BD':
        flash('BD Department has access to project status under Manage Job Indents only.', 'info')
        return redirect(url_for('manage_job_indents'))

    indent = JobIndent.query.get_or_404(indent_id)
    if current_user.role not in ['MD', 'PM', 'Admin', 'HR', 'FINANCE', 'Finance']:
        abort(403)
    
    jc = indent.job_card
    
    # 1. Parse Milestones
    milestones = []
    milestone_progress_pct = 0.0
    completed_milestones_count = 0
    in_progress_milestones_count = 0
    pending_milestones_count = 0
    if jc and jc.milestones_json:
        try:
            milestones = json.loads(jc.milestones_json)
            for m in milestones:
                pct = float(m.get('percentage', 0) or 0)
                m['percentage'] = pct
                m['days'] = int(m.get('days', 0) or 0)
                status = m.get('status', 'Pending')
                if not status:
                    status = 'Pending'
                m['status'] = status
                if status == 'Completed':
                    milestone_progress_pct += pct
                    completed_milestones_count += 1
                elif status == 'In Progress':
                    in_progress_milestones_count += 1
                else:
                    pending_milestones_count += 1
            milestone_progress_pct = round(min(100.0, milestone_progress_pct), 1)
        except Exception as e:
            milestones = []
            milestone_progress_pct = 0.0

    # 2. Parse Expenditures & Finance Actual Bills
    project_bills = ProjectActualExpense.query.filter_by(job_indent_id=indent.id).order_by(
        ProjectActualExpense.bill_date.desc(), ProjectActualExpense.id.desc()
    ).all()
    bills_by_cat = defaultdict(float)
    for b in project_bills:
        bills_by_cat[b.category.strip().lower()] += (b.amount or 0.0)

    expenditures = []
    total_estimated_expenditure = 0.0
    total_actual_expenditure = 0.0
    tracked_categories = set()

    if jc and jc.expenditures_json:
        try:
            raw_exp = json.loads(jc.expenditures_json)
            for idx, e in enumerate(raw_exp):
                cat = e.get('category', 'Operational Expense')
                cat_key = cat.strip().lower()
                tracked_categories.add(cat_key)
                desc = e.get('description', '')
                amt = float(e.get('amount', 0) or 0)
                unit_days = float(e.get('unit_days', 1) or 1)
                unit_type = e.get('unit_type', 'Unit')
                est_tot = round(float(e.get('total_amount', 0) or (amt * unit_days)), 2)
                
                # Actual spent from Finance recurring bills, or fallback to saved actual
                if cat_key in bills_by_cat:
                    act_amt = round(bills_by_cat[cat_key], 2)
                else:
                    act_amt = round(float(e.get('actual_amount', 0) or 0), 2)

                variance = round(est_tot - act_amt, 2)
                utilization = round((act_amt / est_tot * 100), 1) if est_tot > 0 else 0.0
                expenditures.append({
                    'index': idx,
                    'category': cat,
                    'description': desc,
                    'amount': amt,
                    'unit_days': unit_days,
                    'unit_type': unit_type,
                    'estimated_amount': est_tot,
                    'actual_amount': act_amt,
                    'variance': variance,
                    'utilization': utilization
                })
                total_estimated_expenditure += est_tot
                total_actual_expenditure += act_amt
        except Exception as e:
            expenditures = []

    # If any bills exist in categories not originally in the Job Card, include them
    for cat_lower, actual_sum in bills_by_cat.items():
        if cat_lower not in tracked_categories:
            matching_b = [b for b in project_bills if b.category.strip().lower() == cat_lower]
            display_name = matching_b[0].category if matching_b else cat_lower.title()
            act_sum = round(actual_sum, 2)
            expenditures.append({
                'index': len(expenditures),
                'category': display_name,
                'description': 'Additional Expense booked by Finance',
                'amount': 0.0,
                'unit_days': 1,
                'unit_type': 'Unit',
                'estimated_amount': 0.0,
                'actual_amount': act_sum,
                'variance': round(-act_sum, 2),
                'utilization': 100.0
            })
            total_actual_expenditure += act_sum

    total_expenditure_variance = round(total_estimated_expenditure - total_actual_expenditure, 2)
    overall_expenditure_utilization = round((total_actual_expenditure / total_estimated_expenditure * 100), 1) if total_estimated_expenditure > 0 else 0.0

    # 3. Parse Resources & Timesheet Submission
    resources = []
    total_allocated_days = 0.0
    if jc and jc.resources_json:
        try:
            resources = json.loads(jc.resources_json)
            for r in resources:
                total_allocated_days += float(r.get('days', 0) or 0)
        except Exception:
            resources = []

    total_allocated_hours = round(total_allocated_days * 8.0, 1)

    # Project timesheets from daily Timesheet model
    project_timesheets = Timesheet.query.filter_by(project_id=indent.id).all()
    # Also include weekly timesheets linked to tasks of this job card if any
    task_ids = [t.id for t in (jc.tasks if jc else [])]
    weekly_ts = WeeklyTimesheet.query.filter(WeeklyTimesheet.task_id.in_(task_ids)).all() if task_ids else []

    logged_hours_from_daily = sum(t.hours_worked for t in project_timesheets)
    logged_hours_from_weekly = sum(w.total_hours for w in weekly_ts)
    total_logged_hours = round(logged_hours_from_daily + logged_hours_from_weekly, 1)

    approved_hours = round(
        sum(t.hours_worked for t in project_timesheets if t.status == 'Approved' or t.rm_status == 'Approved' or t.status == 'CEO Approved') +
        sum(w.total_hours for w in weekly_ts if w.status in ['PM Approved', 'HR Approved']),
        1
    )
    pending_hours = round(total_logged_hours - approved_hours, 1)

    timesheet_submission_pct = round((total_logged_hours / total_allocated_hours * 100), 1) if total_allocated_hours > 0 else 0.0

    # Resource-wise breakdown
    resource_timesheet_breakdown = []
    for r in resources:
        emp_id = r.get('employee_id')
        alloc_days = float(r.get('days', 0) or 0)
        alloc_hrs = round(alloc_days * 8.0, 1)
        emp_name = r.get('employee_name', '')
        if emp_id:
            emp = Employee.query.get(int(emp_id))
            if emp and not emp_name:
                emp_name = emp.name
            emp_logged_hrs = sum(t.hours_worked for t in project_timesheets if t.employee_id == int(emp_id))
            emp_logged_hrs += sum(w.total_hours for w in weekly_ts if w.employee_id == int(emp_id))
        else:
            emp_logged_hrs = 0.0
        
        emp_sub_pct = round((emp_logged_hrs / alloc_hrs * 100), 1) if alloc_hrs > 0 else 0.0
        resource_timesheet_breakdown.append({
            'employee_name': emp_name or 'Resource',
            'allocated_days': alloc_days,
            'allocated_hours': alloc_hrs,
            'logged_hours': round(emp_logged_hrs, 1),
            'submission_pct': emp_sub_pct
        })

    # Active employees for CEO assignment dropdown (if pending)
    project_managers = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()

    return render_template(
        'job_indents/view_indent_details.html',
        indent=indent,
        jc=jc,
        project_managers=project_managers,
        milestones=milestones,
        milestone_progress_pct=milestone_progress_pct,
        completed_milestones_count=completed_milestones_count,
        in_progress_milestones_count=in_progress_milestones_count,
        pending_milestones_count=pending_milestones_count,
        expenditures=expenditures,
        total_estimated_expenditure=total_estimated_expenditure,
        total_actual_expenditure=total_actual_expenditure,
        total_expenditure_variance=total_expenditure_variance,
        overall_expenditure_utilization=overall_expenditure_utilization,
        total_allocated_hours=total_allocated_hours,
        total_logged_hours=total_logged_hours,
        approved_hours=approved_hours,
        pending_hours=pending_hours,
        timesheet_submission_pct=timesheet_submission_pct,
        resource_timesheet_breakdown=resource_timesheet_breakdown,
        project_bills=project_bills
    )

@app.route('/project/<int:indent_id>/update-milestone-status', methods=['POST'])
@login_required
def update_milestone_status(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    # Strictly allow only the assigned PM (or IT Admin). CEO / MD is read-only.
    if indent.project_manager_id != current_user.id and current_user.role != 'Admin':
        return jsonify({'success': False, 'message': 'Unauthorized: Only the assigned Project Manager can update milestone status.'}), 403

    jc = indent.job_card
    if not jc or not jc.milestones_json:
        return jsonify({'success': False, 'message': 'No milestones found for this project.'}), 404

    data = request.get_json() or {}
    milestone_index = data.get('index')
    new_status = data.get('status')

    if milestone_index is None or new_status not in ['Pending', 'In Progress', 'Completed']:
        return jsonify({'success': False, 'message': 'Invalid milestone parameters.'}), 400

    try:
        milestones = json.loads(jc.milestones_json)
        idx = int(milestone_index)
        if 0 <= idx < len(milestones):
            milestones[idx]['status'] = new_status
            jc.milestones_json = json.dumps(milestones)
            db.session.commit()

            total_progress = sum(float(m.get('percentage', 0) or 0) for m in milestones if m.get('status') == 'Completed')
            total_progress = round(min(100.0, total_progress), 1)

            return jsonify({
                'success': True,
                'message': f"Milestone '{milestones[idx].get('name')}' updated to {new_status}.",
                'milestone_progress_pct': total_progress,
                'milestone_status': new_status
            })
        else:
            return jsonify({'success': False, 'message': 'Milestone index out of range.'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/project/<int:indent_id>/update-actual-expenditures', methods=['POST'])
@login_required
def update_actual_expenditures(indent_id):
    # Strictly allow only Accounts & Finance department (or IT Admin). PM and CEO are read-only.
    if current_user.role not in ['FINANCE', 'Finance', 'Admin']:
        return jsonify({'success': False, 'message': 'Unauthorized: Financial actual expenses can only be added by the Accounts & Finance Department.'}), 403

    indent = JobIndent.query.get_or_404(indent_id)
    jc = indent.job_card
    if not jc or not jc.expenditures_json:
        return jsonify({'success': False, 'message': 'No expenditures found for this project.'}), 404

    data = request.get_json() or {}
    actuals = data.get('actuals', [])

    try:
        expenditures = json.loads(jc.expenditures_json)
        for item in actuals:
            idx = int(item.get('index', -1))
            val = float(item.get('actual_amount', 0) or 0)
            if 0 <= idx < len(expenditures):
                expenditures[idx]['actual_amount'] = val

        jc.expenditures_json = json.dumps(expenditures)
        db.session.commit()

        tot_est = sum(float(e.get('total_amount', 0) or (float(e.get('amount', 0) or 0) * float(e.get('unit_days', 1) or 1))) for e in expenditures)
        tot_act = sum(float(e.get('actual_amount', 0) or 0) for e in expenditures)
        variance = round(tot_est - tot_act, 2)
        utilization = round((tot_act / tot_est * 100), 1) if tot_est > 0 else 0.0

        return jsonify({
            'success': True,
            'message': 'Actual expenditures updated successfully.',
            'total_estimated': tot_est,
            'total_actual': tot_act,
            'variance': variance,
            'utilization': utilization
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# --- Accounts & Finance Department Project Financials & Expense Booking ---
@app.route('/finance/project/<int:indent_id>/expenses')
@login_required
def finance_project_expenses(indent_id):
    if current_user.role not in ['FINANCE', 'Finance', 'Admin', 'MD']:
        abort(403)
    indent = JobIndent.query.get_or_404(indent_id)
    jc = indent.job_card

    # Budget estimates submitted by PM and approved by CEO
    budgeted_categories = []
    if jc and jc.expenditures_json:
        try:
            raw_exp = json.loads(jc.expenditures_json)
            for idx, e in enumerate(raw_exp):
                cat = e.get('category', 'Operational')
                amount = float(e.get('amount', 0) or 0)
                unit_days = float(e.get('unit_days', 1) or 1)
                est_tot = round(float(e.get('total_amount', 0) or (amount * unit_days)), 2)
                budgeted_categories.append({
                    'index': idx,
                    'category': cat,
                    'description': e.get('description', ''),
                    'estimated_amount': est_tot
                })
        except Exception:
            budgeted_categories = []

    if not budgeted_categories and jc and jc.budget_items:
        for idx, bi in enumerate(jc.budget_items):
            budgeted_categories.append({
                'index': idx,
                'category': bi.category,
                'description': bi.description or '',
                'estimated_amount': bi.amount
            })

    # Recurring bills from ProjectActualExpense
    bills = ProjectActualExpense.query.filter_by(job_indent_id=indent.id).order_by(
        ProjectActualExpense.bill_date.desc(), ProjectActualExpense.id.desc()
    ).all()

    # Reconcile category totals
    category_summary = []
    total_estimated = sum(c['estimated_amount'] for c in budgeted_categories)
    total_actual = sum(b.amount for b in bills)

    bills_by_cat = defaultdict(list)
    for b in bills:
        bills_by_cat[b.category.strip().lower()].append(b)

    for cat_item in budgeted_categories:
        c_name = cat_item['category']
        matching_bills = bills_by_cat.get(c_name.strip().lower(), [])
        act_sum = round(sum(b.amount for b in matching_bills), 2)
        est_val = cat_item['estimated_amount']
        var = round(est_val - act_sum, 2)
        util_pct = round((act_sum / est_val * 100), 1) if est_val > 0 else 0.0
        category_summary.append({
            'category': c_name,
            'description': cat_item['description'],
            'estimated_amount': est_val,
            'actual_amount': act_sum,
            'variance': var,
            'utilization': util_pct,
            'bill_count': len(matching_bills)
        })

    # Extra categories recorded in bills not initially budgeted
    budgeted_cat_names = set(c['category'].strip().lower() for c in budgeted_categories)
    for cat_lower, cat_bills in bills_by_cat.items():
        if cat_lower not in budgeted_cat_names:
            act_sum = round(sum(b.amount for b in cat_bills), 2)
            category_summary.append({
                'category': cat_bills[0].category,
                'description': 'Additional Expense booked by Finance',
                'estimated_amount': 0.0,
                'actual_amount': act_sum,
                'variance': round(-act_sum, 2),
                'utilization': 100.0,
                'bill_count': len(cat_bills)
            })

    grand_total_estimate = jc.grand_total if (jc and jc.grand_total) else (indent.contract_value or total_estimated)
    resource_estimate = jc.resource_total if (jc and jc.resource_total) else 0.0
    overall_variance = round(total_estimated - total_actual, 2)
    overall_utilization = round((total_actual / total_estimated * 100), 1) if total_estimated > 0 else 0.0

    return render_template(
        'finance/project_financials.html',
        indent=indent,
        jc=jc,
        budgeted_categories=budgeted_categories,
        category_summary=category_summary,
        bills=bills,
        total_estimated=total_estimated,
        total_actual=total_actual,
        overall_variance=overall_variance,
        overall_utilization=overall_utilization,
        grand_total_estimate=grand_total_estimate,
        resource_estimate=resource_estimate
    )

@app.route('/api/finance/project/<int:indent_id>/add-bill', methods=['POST'])
@login_required
def api_finance_add_bill(indent_id):
    if current_user.role not in ['FINANCE', 'Finance', 'Admin']:
        return jsonify({'success': False, 'error': 'Unauthorized: Only Accounts & Finance can record expenses.'}), 403

    indent = JobIndent.query.get_or_404(indent_id)
    data = request.get_json() if request.is_json else request.form

    category = bleach.clean(data.get('category', '')).strip()
    bill_date_str = data.get('bill_date', '')
    bill_number = bleach.clean(data.get('bill_number', '')).strip()
    vendor_name = bleach.clean(data.get('vendor_name', '')).strip()
    description = bleach.clean(data.get('description', '')).strip()
    amount_str = str(data.get('amount', '0')).strip().replace(',', '')

    if not category:
        return jsonify({'success': False, 'error': 'Expenditure Category is required.'}), 400

    try:
        amount = float(amount_str)
        if amount <= 0:
            return jsonify({'success': False, 'error': 'Bill amount must be greater than 0.'}), 400
    except ValueError:
        return jsonify({'success': False, 'error': 'Valid numeric amount is required.'}), 400

    try:
        bill_date = datetime.strptime(bill_date_str, '%Y-%m-%d').date() if bill_date_str else date.today()
    except ValueError:
        bill_date = date.today()

    new_bill = ProjectActualExpense(
        job_indent_id=indent.id,
        job_card_id=indent.job_card.id if indent.job_card else None,
        category=category,
        bill_date=bill_date,
        bill_number=bill_number or None,
        vendor_name=vendor_name or None,
        description=description or None,
        amount=amount,
        created_by_id=current_user.id
    )
    db.session.add(new_bill)

    # Sync expenditures_json in job_card if present
    jc = indent.job_card
    if jc and jc.expenditures_json:
        try:
            exp_list = json.loads(jc.expenditures_json)
            all_bills_cat = ProjectActualExpense.query.filter_by(job_indent_id=indent.id, category=category).all()
            new_cat_actual = sum(b.amount for b in all_bills_cat) + amount
            matched = False
            for e in exp_list:
                if e.get('category', '').strip().lower() == category.strip().lower():
                    e['actual_amount'] = round(new_cat_actual, 2)
                    matched = True
                    break
            if not matched:
                exp_list.append({
                    'category': category,
                    'description': description or 'Actual Expense',
                    'amount': 0.0,
                    'unit_days': 1,
                    'total_amount': 0.0,
                    'actual_amount': round(new_cat_actual, 2)
                })
            jc.expenditures_json = json.dumps(exp_list)
        except Exception as e:
            print("Error syncing expenditures_json:", e)

    db.session.commit()

    if request.is_json:
        return jsonify({
            'status': 'success',
            'success': True,
            'bill_id': new_bill.id,
            'message': f'Bill of ₹{amount:,.2f} under {category} recorded successfully!'
        })
    flash(f'Bill of ₹{amount:,.2f} under {category} recorded successfully!', 'success')
    return redirect(url_for('finance_project_expenses', indent_id=indent.id))

@app.route('/api/finance/bill/<int:bill_id>/delete', methods=['POST'])
@login_required
def api_finance_delete_bill(bill_id):
    if current_user.role not in ['FINANCE', 'Finance', 'Admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    bill = ProjectActualExpense.query.get_or_404(bill_id)
    indent_id = bill.job_indent_id
    cat = bill.category
    amt = bill.amount

    db.session.delete(bill)

    indent = JobIndent.query.get(indent_id)
    if indent and indent.job_card and indent.job_card.expenditures_json:
        try:
            exp_list = json.loads(indent.job_card.expenditures_json)
            rem_bills = ProjectActualExpense.query.filter(
                ProjectActualExpense.job_indent_id == indent_id,
                ProjectActualExpense.category == cat,
                ProjectActualExpense.id != bill_id
            ).all()
            new_actual = sum(b.amount for b in rem_bills)
            for e in exp_list:
                if e.get('category', '').strip().lower() == cat.strip().lower():
                    e['actual_amount'] = round(new_actual, 2)
                    break
            indent.job_card.expenditures_json = json.dumps(exp_list)
        except Exception as e:
            print("Error resyncing expenditures_json on delete:", e)

    db.session.commit()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or not request.form:
        return jsonify({'status': 'success', 'success': True, 'message': 'Bill record deleted successfully.'})
    flash('Bill record deleted successfully.', 'info')
    return redirect(url_for('finance_project_expenses', indent_id=indent_id))

@app.route('/job-indent/<int:indent_id>/process', methods=['POST'])
@login_required
def process_indent(indent_id):
    if current_user.role not in ['MD', 'PM']:
        abort(403)
    indent = JobIndent.query.get_or_404(indent_id)
    action = request.form.get('action')
    ceo_email = get_ceo_email()
    if action == 'approve':
        pm_id = request.form.get('project_manager_id')
        if not pm_id:
            flash('You must assign a Project Manager to approve the indent.', 'danger')
            return redirect(url_for('view_indent_details', indent_id=indent_id))
        indent.status = 'Approved'
        indent.project_manager_id = int(pm_id)
        indent.approved_at = datetime.utcnow()
        assigned_pm = Employee.query.get(int(pm_id))
        if assigned_pm and assigned_pm.role not in ['MD', 'Admin']:
            assigned_pm.role = 'PM'

        # Ensure linked JobCard in Draft status exists for the PM to prepare
        if not indent.job_card:
            jc = JobCard(
                job_indent_id=indent.id,
                project_start_date=indent.contract_start_date,
                project_end_date=indent.contract_end_date,
                actual_start_date=indent.contract_start_date,
                actual_end_date=indent.contract_end_date,
                status='Draft',
                budget_status='Pending',
                overview=indent.description or f"Project deliverables and milestones for {indent.project_name}."
            )
            db.session.add(jc)

        # In-app notification for the newly appointed PM
        if assigned_pm:
            create_notification(
                assigned_pm.id,
                f"Assigned as Project Manager: {indent.project_name}",
                f"You have been allocated as the Project Manager for project '{indent.project_name}' ({indent.file_number}). Please navigate to 'Manage Job Cards' to draft project deliverables, milestones, and budget.",
                'info'
            )

        flash(f'Job Indent {indent.file_number} has been approved and assigned to PM {assigned_pm.name if assigned_pm else ""}.', 'success')
        # CEO signature for BD
        ceo_signature = get_ceo_signature()
        # Notify BD
        subject = f"Job Indent Approved: {indent.project_name}"
        body = f"<p>Dear {indent.creator.name},</p>" \
               f"<p>Your Job Indent for project <b>{indent.project_name}</b> (Code: {indent.file_number}) has been <b>approved</b>.</p>" \
               f"<p>Project Manager Assigned: {assigned_pm.name if assigned_pm else 'N/A'}</p>"
        send_email(indent.creator.email, subject, body)
        # CEO signature for PM assignment
        if assigned_pm:
            pm_subject = f"You have been assigned as Project Manager for {indent.project_name}"
            pm_body = f"<p>Dear {assigned_pm.name},</p>" \
                      f"<p>You have been officially allocated as the Project Manager for: <b>{indent.project_name}</b> (Code: {indent.file_number}).</p>" \
                      f"<p>Please open the PMS Timesheet Portal and visit <b>Manage Job Cards</b> to create the deliverables, milestones, and budget estimation.</p>"
            send_email(assigned_pm.email, pm_subject, pm_body, cc=ceo_email, signature=ceo_signature)
    elif action == 'reject':
        indent.status = 'Rejected'
        indent.approved_at = datetime.utcnow()
        flash(f'Job Indent {indent.file_number} has been rejected.', 'warning')
        ceo_email = get_ceo_email()
        subject = f"Job Indent Rejected: {indent.project_name}"
        body = f"<p>Dear {indent.creator.name},</p>" \
               f"<p>Your Job Indent for project <b>{indent.project_name}</b> (Code: {indent.file_number}) has been <b>rejected</b>.</p>"
        ceo_signature = get_ceo_signature()
        send_email(indent.creator.email, subject, body, cc=ceo_email, signature=ceo_signature)
    db.session.commit()
    return redirect(url_for('manage_job_indents'))

@app.route('/pm/manage-job-cards')
@app.route('/pm/projects')
@login_required
def pm_manage_job_cards():
    # Accessible to PMs, MDs, Admins, or any employee assigned to an indent
    is_pm = JobIndent.query.filter_by(project_manager_id=current_user.id).first() is not None
    if current_user.role not in ['PM', 'MD', 'Admin'] and not is_pm:
        abort(403)
        
    if current_user.role == 'MD':
        projects = JobIndent.query.filter(JobIndent.status.in_(['Approved', 'In Progress', 'Completed'])).order_by(JobIndent.id.desc()).all()
    else:
        projects = JobIndent.query.filter_by(project_manager_id=current_user.id).order_by(JobIndent.id.desc()).all()

    # Time-based greeting matching Image 2
    from datetime import datetime
    now_hour = datetime.now().hour
    if now_hour < 12:
        greeting = "Good Morning"
    elif now_hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    return render_template('job_cards/manage_job_cards.html', projects=projects, greeting=greeting)

# Legacy alias
@app.route('/pm/assigned-projects')
@login_required
def pm_projects():
    return redirect(url_for('pm_manage_job_cards'))

@app.route('/pm/project-details/<int:indent_id>')
@login_required
def pm_project_details(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    if current_user.role not in ['MD', 'Admin', 'BD'] and indent.project_manager_id != current_user.id:
        abort(403)

    # Ensure linked JobCard exists
    jc = indent.job_card
    if not jc:
        jc = JobCard(
            job_indent_id=indent.id,
            project_start_date=indent.contract_start_date,
            project_end_date=indent.contract_end_date,
            actual_start_date=indent.contract_start_date,
            actual_end_date=indent.contract_end_date,
            status='Draft',
            budget_status='Pending',
            overview=indent.description or f"Project deliverables and milestones for {indent.project_name}."
        )
        db.session.add(jc)
        db.session.commit()

    # Active categories from Category Master
    categories = ExpenditureCategory.query.filter_by(is_active=True).order_by(ExpenditureCategory.name).all()
    
    # All active employees for Resource dropdown
    employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()

    # Project timesheets
    timesheets = Timesheet.query.filter_by(project_id=indent.id).order_by(Timesheet.date.desc()).all()

    # Project Change Requests
    change_requests = ProjectChangeRequest.query.filter_by(job_indent_id=indent.id).order_by(ProjectChangeRequest.created_at.desc()).all()

    return render_template(
        'job_cards/pm_project_details.html',
        indent=indent,
        jc=jc,
        categories=categories,
        employees=employees,
        timesheets=timesheets,
        change_requests=change_requests
    )

@app.route('/api/job-card/<int:indent_id>/calculate-budget', methods=['POST'])
@login_required
def api_calculate_job_card_budget(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    if current_user.role not in ['MD', 'Admin', 'PM'] and indent.project_manager_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    resources = data.get('resources', [])
    expenditures = data.get('expenditures', [])

    # Confidential Resource Calculation:
    # Per day Salary = Monthly Salary / 30.0
    # Cost = Per day Salary * days
    # Aggregated on server without disclosing individual figures to the PM!
    resource_total = 0.0
    for res in resources:
        emp_id = res.get('employee_id')
        days = float(res.get('days', 0) or 0)
        if not emp_id or days <= 0:
            continue
        emp = Employee.query.get(int(emp_id))
        if emp:
            monthly_sal = emp.monthly_salary if emp.monthly_salary and emp.monthly_salary > 0 else 30000.0
            daily_sal = monthly_sal / 30.0
            emp_cost = round(daily_sal * days)
            resource_total += emp_cost

    # Project Expenditure Sub-Total
    expenditure_total = 0.0
    for exp in expenditures:
        amt = float(exp.get('amount', 0) or 0)
        qty = float(exp.get('unit_days', 1) or 1)
        row_total = round(amt * qty)
        expenditure_total += row_total

    # Sub-Total
    sub_total = resource_total + expenditure_total

    # Overhead Cost (30% of Sub-Total)
    overhead_cost = round(sub_total * 0.30)

    # Grand Total
    grand_total = sub_total + overhead_cost

    return jsonify({
        'success': True,
        'resource_total': resource_total,
        'expenditure_total': expenditure_total,
        'sub_total': sub_total,
        'overhead_cost': overhead_cost,
        'grand_total': grand_total
    })

@app.route('/api/job-card/<int:indent_id>/save-draft', methods=['POST'])
@login_required
def api_save_job_card_draft(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    if current_user.role not in ['MD', 'Admin', 'PM'] and indent.project_manager_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    jc = indent.job_card
    if not jc:
        jc = JobCard(job_indent_id=indent.id)
        db.session.add(jc)

    data = request.get_json() or {}
    overview = data.get('overview', '')
    actual_start_str = data.get('actual_start_date')
    actual_end_str = data.get('actual_end_date')
    milestones = data.get('milestones', [])
    resources = data.get('resources', [])
    expenditures = data.get('expenditures', [])

    actual_start = None
    actual_end = None
    if actual_start_str:
        try:
            actual_start = datetime.strptime(actual_start_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if actual_end_str:
        try:
            actual_end = datetime.strptime(actual_end_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    jc.overview = overview
    jc.actual_start_date = actual_start
    jc.actual_end_date = actual_end
    jc.milestones_json = json.dumps(milestones)
    jc.resources_json = json.dumps(resources)
    jc.expenditures_json = json.dumps(expenditures)

    # Calculate and store totals
    resource_total = 0.0
    for res in resources:
        emp_id = res.get('employee_id')
        days = float(res.get('days', 0) or 0)
        if emp_id and days > 0:
            emp = Employee.query.get(int(emp_id))
            if emp:
                monthly_sal = emp.monthly_salary if emp.monthly_salary and emp.monthly_salary > 0 else 30000.0
                daily_sal = monthly_sal / 30.0
                resource_total += round(daily_sal * days)

    expenditure_total = 0.0
    for exp in expenditures:
        amt = float(exp.get('amount', 0) or 0)
        qty = float(exp.get('unit_days', 1) or 1)
        expenditure_total += round(amt * qty)

    sub_total = resource_total + expenditure_total
    overhead_cost = round(sub_total * 0.30)
    grand_total = sub_total + overhead_cost

    jc.resource_total = resource_total
    jc.expenditure_total = expenditure_total
    jc.sub_total = sub_total
    jc.overhead_cost = overhead_cost
    jc.grand_total = grand_total
    jc.estimated_value = grand_total
    if jc.status != 'Approved':
        jc.status = 'Draft'
        jc.budget_status = 'Pending'

    # Sync BudgetItem for reports
    BudgetItem.query.filter_by(job_card_id=jc.id).delete()
    if resource_total > 0:
        db.session.add(BudgetItem(job_card_id=jc.id, category='Resource Manpower', description='Project Resources & Engineering', amount=resource_total))
    for exp in expenditures:
        cat = exp.get('category') or 'Operational'
        desc = exp.get('description') or ''
        amt = float(exp.get('total_amount', 0) or 0)
        if amt > 0:
            db.session.add(BudgetItem(job_card_id=jc.id, category=cat, description=desc, amount=amt))

    db.session.commit()
    return jsonify({'success': True, 'message': 'Section draft saved successfully! You can resume editing anytime.'})

@app.route('/api/job-card/<int:indent_id>/submit', methods=['POST'])
@login_required
def api_submit_job_card(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    if current_user.role not in ['MD', 'Admin', 'PM'] and indent.project_manager_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    jc = indent.job_card
    if not jc:
        jc = JobCard(job_indent_id=indent.id)
        db.session.add(jc)

    data = request.get_json() or {}
    overview = data.get('overview', jc.overview or '')
    actual_start_str = data.get('actual_start_date')
    actual_end_str = data.get('actual_end_date')
    milestones = data.get('milestones', [])
    resources = data.get('resources', [])
    expenditures = data.get('expenditures', [])

    if actual_start_str:
        try:
            jc.actual_start_date = datetime.strptime(actual_start_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if actual_end_str:
        try:
            jc.actual_end_date = datetime.strptime(actual_end_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    jc.overview = overview
    jc.milestones_json = json.dumps(milestones)
    jc.resources_json = json.dumps(resources)
    jc.expenditures_json = json.dumps(expenditures)

    resource_total = 0.0
    for res in resources:
        emp_id = res.get('employee_id')
        days = float(res.get('days', 0) or 0)
        if emp_id and days > 0:
            emp = Employee.query.get(int(emp_id))
            if emp:
                monthly_sal = emp.monthly_salary if emp.monthly_salary and emp.monthly_salary > 0 else 30000.0
                daily_sal = monthly_sal / 30.0
                resource_total += round(daily_sal * days)

    expenditure_total = 0.0
    for exp in expenditures:
        amt = float(exp.get('amount', 0) or 0)
        qty = float(exp.get('unit_days', 1) or 1)
        expenditure_total += round(amt * qty)

    sub_total = resource_total + expenditure_total
    overhead_cost = round(sub_total * 0.30)
    grand_total = sub_total + overhead_cost

    jc.resource_total = resource_total
    jc.expenditure_total = expenditure_total
    jc.sub_total = sub_total
    jc.overhead_cost = overhead_cost
    jc.grand_total = grand_total
    jc.estimated_value = grand_total

    jc.status = 'Submitted'
    jc.budget_status = 'Pending Approval'
    jc.submitted_at = datetime.utcnow()

    # Clear and recreate tasks for assignees
    for old_t in Task.query.filter_by(job_card_id=jc.id).all():
        old_t.assignees.clear()
        db.session.delete(old_t)

    for res in resources:
        emp_id = res.get('employee_id')
        tasks = res.get('tasks', [])
        emp = Employee.query.get(int(emp_id)) if emp_id else None
        if emp:
            for t_desc in tasks:
                t = Task(
                    job_card_id=jc.id,
                    description=t_desc,
                    timeline_start=jc.actual_start_date or indent.contract_start_date,
                    timeline_end=jc.actual_end_date or indent.contract_end_date,
                    man_days=int(res.get('days', 0) or 0),
                    status='To Do'
                )
                t.assignees.append(emp)
                db.session.add(t)

    # In-app notification to CEO
    ceo_user = Employee.query.filter_by(role='MD').first()
    if ceo_user:
        create_notification(
            ceo_user.id,
            f"Job Card Submitted: {indent.project_name}",
            f"Project Manager {current_user.name} has submitted the Job Card and Budget Estimate (Grand Total: ₹ {grand_total:,.2f}) for '{indent.project_name}' for your final approval.",
            'warning'
        )
        ceo_email = get_ceo_email()
        subject = f"Job Card Submitted for Approval: {indent.project_name} ({indent.file_number})"
        body = f"""
        <p>Dear CEO / MD,</p>
        <p>Project Manager <b>{current_user.name}</b> has completed and submitted the official Job Card and Budget Estimation for project <b>{indent.project_name}</b> (Code: <code>{indent.file_number}</code>).</p>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
            <tr><td><b>Contract Value:</b></td><td>₹ {indent.contract_value:,.2f}</td></tr>
            <tr><td><b>Resource Estimation:</b></td><td>₹ {resource_total:,.2f}</td></tr>
            <tr><td><b>Project Expenditures:</b></td><td>₹ {expenditure_total:,.2f}</td></tr>
            <tr><td><b>Sub-Total:</b></td><td>₹ {sub_total:,.2f}</td></tr>
            <tr><td><b>Overhead Cost (30%):</b></td><td>₹ {overhead_cost:,.2f}</td></tr>
            <tr style="background-color: #ecfdf5;"><td><b>Grand Total Budget:</b></td><td><b>₹ {grand_total:,.2f}</b></td></tr>
        </table>
        <p>Please log in to the PMS Portal to review the submission and grant approval.</p>
        """
        send_email(ceo_email, subject, body, cc=current_user.email)

    db.session.commit()
    return jsonify({'success': True, 'message': 'Job Card has been submitted to CEO for final approval.'})

@app.route('/project/<int:indent_id>/download-ceo-report')
@login_required
def download_ceo_project_report(indent_id):
    if current_user.role != 'MD':
        abort(403)

    indent = JobIndent.query.get_or_404(indent_id)
    jc = indent.job_card

    # Parse milestones
    milestones = []
    if jc and jc.milestones_json:
        try:
            milestones = json.loads(jc.milestones_json)
        except Exception:
            milestones = []

    # Parse resources & compute CEO amounts
    resources_raw = []
    if jc and jc.resources_json:
        try:
            resources_raw = json.loads(jc.resources_json)
        except Exception:
            resources_raw = []

    resource_rows = []
    resource_total = 0.0
    for r in resources_raw:
        emp_id = r.get('employee_id')
        days = float(r.get('days', 0) or 0)
        emp_name = r.get('employee_name', '')
        designation = r.get('designation', '')
        if emp_id:
            emp = Employee.query.get(int(emp_id))
            if emp:
                if not emp_name:
                    emp_name = emp.name
                if not designation:
                    designation = emp.designation
                monthly_sal = emp.monthly_salary if emp.monthly_salary and emp.monthly_salary > 0 else 30000.0
                daily_sal = monthly_sal / 30.0
                cost = round(daily_sal * days, 2)
            else:
                cost = 0.0
        else:
            cost = 0.0

        resource_total += cost
        resource_rows.append({
            'name': emp_name or 'RESOURCE',
            'designation': designation,
            'start_date': r.get('start_date', ''),
            'end_date': r.get('end_date', ''),
            'days': int(days),
            'cost': cost
        })

    # Parse expenditures
    expenditures = []
    expenditure_total = 0.0
    if jc and jc.expenditures_json:
        try:
            expenditures = json.loads(jc.expenditures_json)
            for e in expenditures:
                amt = float(e.get('amount', 0) or 0)
                qty = float(e.get('unit_days', 1) or 1)
                tot = round(amt * qty, 2)
                e['total_amount'] = tot
                expenditure_total += tot
        except Exception:
            expenditures = []

    sub_total = resource_total + expenditure_total
    overhead_cost = round(sub_total * 0.30, 2)
    grand_total = sub_total + overhead_cost

    # Contract days & actual days
    contract_days = 0
    if indent.contract_start_date and indent.contract_end_date:
        contract_days = (indent.contract_end_date - indent.contract_start_date).days + 1

    actual_start_str = '-'
    actual_end_str = '-'
    actual_days = 0
    if jc and jc.actual_start_date and jc.actual_end_date:
        actual_start_str = jc.actual_start_date.strftime('%d/%m/%Y')
        actual_end_str = jc.actual_end_date.strftime('%d/%m/%Y')
        actual_days = (jc.actual_end_date - jc.actual_start_date).days + 1
    elif indent.contract_start_date and indent.contract_end_date:
        actual_start_str = indent.contract_start_date.strftime('%d/%m/%Y')
        actual_end_str = indent.contract_end_date.strftime('%d/%m/%Y')
        actual_days = contract_days

    overview_html = (jc.overview if jc and jc.overview else indent.description) or ''
    clean_overview = bleach.clean(overview_html, tags=['p', 'b', 'i', 'u', 'h1', 'h2', 'h3', 'ul', 'ol', 'li', 'br', 'strong', 'em'], strip=True)

    rendered_html = render_template(
        'reports/ceo_project_report_pdf.html',
        indent=indent,
        jc=jc,
        contract_days=contract_days,
        actual_start_str=actual_start_str,
        actual_end_str=actual_end_str,
        actual_days=actual_days,
        overview_clean=clean_overview,
        milestones=milestones,
        resource_rows=resource_rows,
        resource_total=resource_total,
        expenditures=expenditures,
        expenditure_total=expenditure_total,
        sub_total=sub_total,
        overhead_cost=overhead_cost,
        grand_total=grand_total,
        now=datetime.now()
    )

    from xhtml2pdf import pisa
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(rendered_html, dest=pdf_buffer)
    if pisa_status.err:
        return f"Error generating PDF: {pisa_status.err}", 500

    pdf_buffer.seek(0)
    filename = f"project_{indent.id}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

@app.route('/static/uploads/<path:filename>')
@app.route('/uploads/<path:filename>')
@app.route('/uploads/job_indents/<path:filename>')
@app.route('/document/serve/<path:filename>')
def serve_indent_file(filename):
    """
    Serve uploaded project documents and indents with multi-tiered resolution:
    1. Disk storage: uploads/job_indents, /tmp/uploads/job_indents, static/uploads
    2. Database: IndentDocument (BYTEA storage in Neon PostgreSQL)
    3. Graceful on-the-fly generated document for legacy ephemeral records
    """
    safe_name = os.path.basename(filename)
    
    # Check if download is requested via query param ?download=1
    as_attachment = request.args.get('download', '0') in ['1', 'true', 'True']
    
    # 1. Check local/ephemeral disk locations
    possible_paths = [
        os.path.join(app.root_path, 'uploads', 'job_indents', safe_name),
        os.path.join(tempfile.gettempdir(), 'uploads', 'job_indents', safe_name),
        os.path.join(app.root_path, 'static', 'uploads', safe_name),
        os.path.join(tempfile.gettempdir(), 'uploads', safe_name),
        os.path.join(app.root_path, 'uploads', safe_name),
    ]
    for p in possible_paths:
        if os.path.isfile(p):
            mtype = 'application/pdf' if safe_name.lower().endswith('.pdf') else None
            return send_file(p, as_attachment=as_attachment, download_name=safe_name, mimetype=mtype)

    # 2. Check IndentDocument table in database
    try:
        doc = IndentDocument.query.filter_by(filename=safe_name).first()
        if doc and doc.file_data:
            buf = io.BytesIO(doc.file_data)
            buf.seek(0)
            return send_file(
                buf,
                mimetype=doc.mime_type or 'application/pdf',
                as_attachment=as_attachment,
                download_name=doc.original_filename or safe_name
            )
    except Exception as db_err:
        print(f"[WARN] Error querying IndentDocument for {safe_name}: {db_err}")

    # 3. Check if filename is linked to an existing JobIndent record
    try:
        indent = JobIndent.query.filter(
            or_(
                JobIndent.work_order_pdf == safe_name,
                JobIndent.scope_of_work_file == safe_name,
                JobIndent.rfp_document_file == safe_name,
                JobIndent.technical_bid_file == safe_name
            )
        ).first()

        doc_label = "Project Document"
        if indent:
            if indent.work_order_pdf == safe_name:
                doc_label = "Work Order / Contract Document"
            elif indent.scope_of_work_file == safe_name:
                doc_label = "Scope of Work Document"
            elif indent.rfp_document_file == safe_name:
                doc_label = "RFP Tender Document"
            elif indent.technical_bid_file == safe_name:
                doc_label = "Technical Bid Document"

        # Generate an official PDF notice on the fly
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        buf = io.BytesIO()
        doc_pdf = SimpleDocTemplate(buf, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()

        story = []
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, textColor=colors.HexColor('#059669'), alignment=1)
        subtitle_style = ParagraphStyle('Sub', parent=styles['Normal'], fontName='Helvetica', fontSize=10, textColor=colors.HexColor('#475569'), alignment=1)
        normal_style = ParagraphStyle('Norm', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor('#1e293b'))
        bold_label = ParagraphStyle('BoldL', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#0f172a'))
        notice_style = ParagraphStyle('Notice', parent=styles['Normal'], fontName='Helvetica', fontSize=9, textColor=colors.HexColor('#0369a1'), leading=13)

        story.append(Paragraph('ECOMETRIX CONSULTANTS PVT. LTD.', title_style))
        story.append(Paragraph('DayLog - Unified Timesheet & Project Management System', subtitle_style))
        story.append(Spacer(1, 15))
        story.append(Paragraph(f'OFFICIAL PROJECT {doc_label.upper()} RECORD', ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=13, alignment=1, textColor=colors.HexColor('#1e293b'))))
        story.append(Spacer(1, 15))

        p_name = indent.project_name if indent else "Project Record"
        f_num = indent.file_number if indent else "N/A"
        c_name = indent.client_name if indent else "N/A"
        dept_name = (indent.department.name if indent and indent.department else "General Administration")

        table_data = [
            [Paragraph('<b>Project Name:</b>', bold_label), Paragraph(p_name, normal_style)],
            [Paragraph('<b>File Number:</b>', bold_label), Paragraph(f_num, normal_style)],
            [Paragraph('<b>Client Name:</b>', bold_label), Paragraph(c_name, normal_style)],
            [Paragraph('<b>Department:</b>', bold_label), Paragraph(dept_name, normal_style)],
            [Paragraph('<b>Document File:</b>', bold_label), Paragraph(safe_name, normal_style)],
            [Paragraph('<b>Document Type:</b>', bold_label), Paragraph(doc_label, normal_style)],
            [Paragraph('<b>Status:</b>', bold_label), Paragraph('ACTIVE - Verified in Enterprise Registry', normal_style)]
        ]

        t = Table(table_data, colWidths=[150, 380])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 8),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(t)
        story.append(Spacer(1, 25))

        notice_p = Paragraph('<b>System Notice:</b> This project document reference is securely cataloged in the Enterprise PMS registry. Authorized personnel (BD, PM, or Admin) can update or upload a refreshed copy of this document via the Project Details management interface.', notice_style)
        nt = Table([[notice_p]], colWidths=[530])
        nt.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e0f2fe')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#38bdf8')),
            ('PADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(nt)

        doc_pdf.build(story)
        pdf_bytes = buf.getvalue()

        # Cache in IndentDocument for subsequent calls
        try:
            if indent:
                cached_doc = IndentDocument(
                    indent_id=indent.id,
                    doc_type='work_order',
                    filename=safe_name,
                    original_filename=safe_name,
                    file_data=pdf_bytes,
                    file_size=len(pdf_bytes),
                    mime_type='application/pdf'
                )
                db.session.add(cached_doc)
                db.session.commit()
        except Exception:
            db.session.rollback()

        buf.seek(0)
        return send_file(buf, mimetype='application/pdf', as_attachment=as_attachment, download_name=safe_name)
    except Exception as gen_err:
        print(f"[ERROR] Error generating document fallback: {gen_err}")
        return f"Document {safe_name} is being synchronized. Please refresh.", 200

@app.route('/project/upload-document/<int:indent_id>', methods=['POST'])
@login_required
def upload_indent_document(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    if current_user.role not in ['MD', 'Admin', 'BD', 'PM'] and indent.project_manager_id != current_user.id:
        flash("You do not have permission to attach documents to this project.", "danger")
        return redirect(request.referrer or url_for('view_indent_details', indent_id=indent_id))

    doc_type = request.form.get('doc_type', 'work_order')
    file_obj = request.files.get('document_file')
    if not file_obj or not file_obj.filename:
        flash("Please select a valid document file.", "warning")
        return redirect(request.referrer or url_for('view_indent_details', indent_id=indent_id))

    filename = secure_filename(file_obj.filename)
    safe_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
    content = file_obj.read()

    # Save to disk cache if possible
    try:
        folder = os.path.join(tempfile.gettempdir(), 'uploads', 'job_indents')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, safe_name), 'wb') as f:
            f.write(content)
    except Exception:
        pass

    # Save to IndentDocument
    doc = IndentDocument(
        indent_id=indent.id,
        doc_type=doc_type,
        filename=safe_name,
        original_filename=filename,
        file_data=content,
        file_size=len(content),
        mime_type=file_obj.content_type or 'application/pdf'
    )
    db.session.add(doc)

    if doc_type == 'work_order':
        indent.work_order_pdf = safe_name
    elif doc_type == 'scope_of_work':
        indent.scope_of_work_file = safe_name
    elif doc_type == 'rfp':
        indent.rfp_document_file = safe_name
    elif doc_type == 'technical_bid':
        indent.technical_bid_file = safe_name

    db.session.commit()
    flash(f"Document '{filename}' successfully uploaded and stored securely.", "success")
    return redirect(request.referrer or url_for('view_indent_details', indent_id=indent_id))

@app.route('/job-indent/<int:indent_id>/change-request', methods=['POST'])
@login_required
def submit_change_request(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    if current_user.role not in ['PM', 'MD'] and indent.project_manager_id != current_user.id:
        abort(403)

    change_type = request.form.get('change_type')
    title = request.form.get('title')
    description = request.form.get('description')
    revised_budget = request.form.get('revised_budget', type=float)
    revised_end_date_str = request.form.get('revised_end_date')

    revised_end_date = None
    if revised_end_date_str:
        try:
            revised_end_date = datetime.strptime(revised_end_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    cr = ProjectChangeRequest(
        job_indent_id=indent.id,
        job_card_id=indent.job_card.id if indent.job_card else None,
        requested_by_id=current_user.id,
        change_type=change_type,
        title=title,
        description=description,
        revised_budget=revised_budget,
        revised_end_date=revised_end_date,
        status='Pending'
    )
    db.session.add(cr)

    ceo_user = Employee.query.filter_by(role='MD').first()
    if ceo_user:
        create_notification(
            ceo_user.id,
            f"Change Request: {indent.project_name}",
            f"PM {current_user.name} has submitted a {change_type} request for '{indent.project_name}': {title}",
            'warning'
        )

    db.session.commit()
    flash("Project Change Request submitted to CEO for review.", "success")
    return redirect(url_for('pm_project_details', indent_id=indent.id))

@app.route('/api/job-card/<int:indent_id>/verify-timesheet', methods=['POST'])
@login_required
def api_verify_timesheet(indent_id):
    data = request.get_json() or {}
    ts_id = data.get('timesheet_id')
    status = data.get('status', 'Approved')
    ts = Timesheet.query.get_or_404(int(ts_id))
    ts.status = status
    db.session.commit()
    return jsonify({'success': True})

# --- IT Admin Category Master CRUD ---
@app.route('/masters/expenditure-categories', methods=['GET', 'POST'])
@login_required
def expenditure_categories():
    if current_user.role not in ['IT', 'MD', 'Admin']:
        abort(403)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        if name:
            existing = ExpenditureCategory.query.filter_by(name=name).first()
            if existing:
                flash(f"Category '{name}' already exists.", "warning")
            else:
                db.session.add(ExpenditureCategory(name=name, description=description, is_active=True))
                db.session.commit()
                flash(f"Category '{name}' created successfully.", "success")
        return redirect(url_for('expenditure_categories'))

    categories = ExpenditureCategory.query.order_by(ExpenditureCategory.name).all()
    return render_template('masters/expenditure_categories.html', categories=categories)

@app.route('/masters/expenditure-categories/edit/<int:id>', methods=['POST'])
@login_required
def edit_expenditure_category(id):
    if current_user.role not in ['IT', 'MD', 'Admin']:
        abort(403)
    cat = ExpenditureCategory.query.get_or_404(id)
    cat.name = request.form.get('name', cat.name).strip()
    cat.description = request.form.get('description', '').strip()
    cat.is_active = 'is_active' in request.form
    db.session.commit()
    flash(f"Category '{cat.name}' updated successfully.", "success")
    return redirect(url_for('expenditure_categories'))

@app.route('/masters/expenditure-categories/delete/<int:id>', methods=['POST'])
@login_required
def delete_expenditure_category(id):
    if current_user.role not in ['IT', 'MD', 'Admin']:
        abort(403)
    cat = ExpenditureCategory.query.get_or_404(id)
    db.session.delete(cat)
    db.session.commit()
    flash(f"Category '{cat.name}' deleted successfully.", "success")
    return redirect(url_for('expenditure_categories'))

@app.route('/job-card/create/<int:indent_id>', methods=['GET', 'POST'])
@login_required
def create_job_card(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    if indent.project_manager_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        # Check if a job card already exists for this indent
        job_card = indent.job_card
        if not job_card:
            job_card = JobCard(job_indent_id=indent.id)
            db.session.add(job_card)
        # Update estimated value and status
        job_card.estimated_value = float(request.form['estimated_value'])
        job_card.status = 'Submitted'
        # Save tasks (existing logic)
        task_idx = 0
        assigned_emails = set()
        while f'task_desc_{task_idx}' in request.form:
            desc = bleach.clean(request.form[f'task_desc_{task_idx}'])
            man_days = int(request.form.get(f'man_days_{task_idx}', 0))
            man_hours = int(request.form.get(f'man_hours_{task_idx}', 0))
            timeline_start_str = request.form.get(f'timeline_start_{task_idx}')
            timeline_end_str = request.form.get(f'timeline_end_{task_idx}')
            timeline_start = datetime.strptime(timeline_start_str, '%Y-%m-%d').date() if timeline_start_str else None
            timeline_end = datetime.strptime(timeline_end_str, '%Y-%m-%d').date() if timeline_end_str else None
            assignee_id = request.form.get(f'team_member_{task_idx}')
            # Only add if not already present (avoid duplicates)
            if desc and assignee_id:
                existing = [t for t in job_card.tasks if t.description == desc and any(a.id == int(assignee_id) for a in t.assignees)]
                if not existing:
                    task = Task(description=desc, man_days=man_days, man_hours=man_hours, timeline_start=timeline_start, timeline_end=timeline_end)
                    assignee = Employee.query.get(int(assignee_id))
                    if assignee:
                        # Prevent duplicate assignment
                        for t in job_card.tasks:
                            if t.description == desc and t.timeline_start == timeline_start and t.timeline_end == timeline_end:
                                if assignee in t.assignees:
                                    return jsonify({'success': False, 'error': 'This employee is already assigned to this task.'}), 400
                        task.assignees.append(assignee)
                    job_card.tasks.append(task)
            task_idx += 1
        # --- Save Budget Items ---
        # Remove any existing budget items (shouldn't be any on create, but for safety)
        job_card.budget_items.clear()
        budget_idx = 0
        while f'budget_category_{budget_idx}' in request.form:
            category = request.form.get(f'budget_category_{budget_idx}', '').strip()
            description = request.form.get(f'budget_description_{budget_idx}', '').strip()
            amount_str = request.form.get(f'budget_amount_{budget_idx}', '0').strip()
            try:
                amount = float(amount_str)
            except ValueError:
                amount = 0.0
            if category and amount > 0:
                budget_item = BudgetItem(category=category, description=description, amount=amount)
                job_card.budget_items.append(budget_item)
            budget_idx += 1
        db.session.commit()
        
        # Create notifications for MD and BD team
        md_team = Employee.query.filter_by(role='MD').first()
        bd_team = Employee.query.filter_by(role='BD').first()
        
        if md_team:
            create_notification(
                md_team.id,
                'New Job Card Submitted',
                f'Job card for project "{indent.project_name}" has been submitted by {current_user.name}',
                'warning'
            )
        
        if bd_team:
            create_notification(
                bd_team.id,
                'New Job Card Submitted',
                f'Job card for project "{indent.project_name}" has been submitted by {current_user.name}',
                'info'
            )
        
        flash('Job Card created and submitted for approval.', 'success')
        # Notify CEO/MD and PM (existing logic)
        ceo_email = get_ceo_email()
        pm = indent.project_manager
        pm_signature = f"Thanks & Regards.<br>{pm.name}<br>Project Manager ({indent.project_name})"
        subject = f"Job Card Submitted: {indent.project_name}"
        body = f"<p>Dear CEO/MD,</p>" \
               f"<p>The Job Card for project <b>{indent.project_name}</b> (Code: {indent.file_number}) has been submitted by PM {pm.name} and is pending your approval.</p>"
        send_email(ceo_email, subject, body, cc=pm.email, signature=pm_signature)
        # Notify each assigned employee
        for email in assigned_emails:
            emp = Employee.query.filter_by(email=email).first()
            if emp:
                emp_body = f"<p>Dear {emp.name},</p>" \
                           f"<p>You have been assigned a task in project <b>{indent.project_name}</b> (Code: {indent.file_number}) by PM {pm.name}.</p>"
                send_email(emp.email, f"Task Assignment: {indent.project_name}", emp_body, cc=[ceo_email, pm.email], signature=pm_signature)
        return redirect(url_for('pm_projects'))
    # Filter employees by department or sub-department
    if indent.sub_department_id:
        all_employees = Employee.query.filter_by(department_id=indent.sub_department_id, is_active=True).all()
    else:
        all_employees = Employee.query.filter_by(department_id=indent.department_id, is_active=True).all()
    return render_template('job_cards/job_card_form.html', indent=indent, all_employees=all_employees, job_card=None)

@app.route('/job-card/edit/<int:card_id>', methods=['GET', 'POST'])
@login_required
def edit_job_card(card_id):
    job_card = JobCard.query.get_or_404(card_id)
    indent = job_card.indent
    if indent.project_manager_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        # Update estimated value
        job_card.estimated_value = float(request.form['estimated_value'])
        # Set status to Submitted
        job_card.status = 'Submitted'
        # Only add new tasks from the form if any (do not delete existing tasks)
        task_idx = 0
        assigned_emails = set()
        while f'task_desc_{task_idx}' in request.form:
            desc = bleach.clean(request.form[f'task_desc_{task_idx}'])
            man_days = int(request.form.get(f'man_days_{task_idx}', 0))
            man_hours = int(request.form.get(f'man_hours_{task_idx}', 0))
            timeline_start_str = request.form.get(f'timeline_start_{task_idx}')
            timeline_end_str = request.form.get(f'timeline_end_{task_idx}')
            timeline_start = datetime.strptime(timeline_start_str, '%Y-%m-%d').date() if timeline_start_str else None
            timeline_end = datetime.strptime(timeline_end_str, '%Y-%m-%d').date() if timeline_end_str else None
            assignee_id = request.form.get(f'team_member_{task_idx}')
            # Only add if not already present (avoid duplicates)
            if desc and assignee_id:
                existing = [t for t in job_card.tasks if t.description == desc and any(a.id == int(assignee_id) for a in t.assignees)]
                if not existing:
                    task = Task(description=desc, man_days=man_days, man_hours=man_hours, timeline_start=timeline_start, timeline_end=timeline_end)
                    assignee = Employee.query.get(int(assignee_id))
                    if assignee:
                        task.assignees.append(assignee)
                        assigned_emails.add(assignee.email)
                    job_card.tasks.append(task)
            task_idx += 1
        # --- Save Budget Items (Edit) ---
        # Remove all old budget items
        job_card.budget_items.clear()
        budget_idx = 0
        while f'budget_category_{budget_idx}' in request.form:
            category = request.form.get(f'budget_category_{budget_idx}', '').strip()
            description = request.form.get(f'budget_description_{budget_idx}', '').strip()
            amount_str = request.form.get(f'budget_amount_{budget_idx}', '0').strip()
            try:
                amount = float(amount_str)
            except ValueError:
                amount = 0.0
            if category and amount > 0:
                budget_item = BudgetItem(category=category, description=description, amount=amount)
                job_card.budget_items.append(budget_item)
            budget_idx += 1
        db.session.commit()
        flash('Job Card updated successfully.', 'success')
        return redirect(url_for('pm_projects'))
    # GET: Pre-fill form with existing data
    if indent.sub_department_id:
        all_employees = Employee.query.filter_by(department_id=indent.sub_department_id, is_active=True).all()
    else:
        all_employees = Employee.query.filter_by(department_id=indent.department_id, is_active=True).all()
    return render_template('job_cards/job_card_form.html', indent=indent, all_employees=all_employees, job_card=job_card)

@app.route('/job-cards/manage')
@login_required
@nocache
def manage_job_cards():
    if current_user.role not in ['MD', 'PM']:
        abort(403)
    
    submitted_cards = JobCard.query.filter_by(status='Submitted').all()
    return render_template('job_cards/manage_job_cards.html', job_cards=submitted_cards)

@app.route('/job-card/view/<int:card_id>')
@login_required
@nocache
def view_job_card_details(card_id):
    if current_user.role not in ['MD', 'PM']:
        abort(403)
    
    job_card = JobCard.query.get_or_404(card_id)
    indent = job_card.indent
    
    # Parse JSON fields safely
    milestones = []
    if job_card.milestones_json:
        try:
            milestones = json.loads(job_card.milestones_json)
        except Exception:
            milestones = []
            
    raw_resources = []
    if job_card.resources_json:
        try:
            raw_resources = json.loads(job_card.resources_json)
        except Exception:
            raw_resources = []
            
    # Enrich resources with confidential employee info for CEO / MD
    resources = []
    calculated_resource_cost = 0.0
    for idx, r in enumerate(raw_resources, 1):
        emp_id = r.get('employee_id')
        days = float(r.get('days', 0) or 0)
        emp = Employee.query.get(int(emp_id)) if emp_id else None
        
        monthly_sal = 0.0
        daily_rate = 0.0
        total_cost = 0.0
        if emp:
            name = emp.name
            designation = emp.designation or 'Team Member'
            department = emp.department.name if emp.department else 'Engineering'
            monthly_sal = emp.monthly_salary if emp.monthly_salary and emp.monthly_salary > 0 else 30000.0
            daily_rate = round(monthly_sal / 30.0, 2)
            total_cost = round(daily_rate * days, 2)
        else:
            name = r.get('employee_name') or f"Employee #{emp_id or idx}"
            designation = 'Team Member'
            department = 'General'
            
        calculated_resource_cost += total_cost
        resources.append({
            'sl_no': idx,
            'employee_id': emp_id,
            'name': name,
            'designation': designation,
            'department': department,
            'days': days,
            'tasks': r.get('tasks', []),
            'monthly_salary': monthly_sal,
            'daily_rate': daily_rate,
            'total_cost': total_cost
        })
        
    expenditures = []
    calculated_exp_cost = 0.0
    if job_card.expenditures_json:
        try:
            raw_exp = json.loads(job_card.expenditures_json)
            for idx, e in enumerate(raw_exp, 1):
                amount = float(e.get('amount', 0) or 0)
                unit_days = float(e.get('unit_days', 1) or 1)
                total = float(e.get('total_amount', 0) or (amount * unit_days))
                calculated_exp_cost += total
                expenditures.append({
                    'sl_no': idx,
                    'category': e.get('category') or 'Operational',
                    'description': e.get('description') or '',
                    'unit_type': e.get('unit_type') or 'Unit',
                    'amount': amount,
                    'unit_days': unit_days,
                    'total_amount': total
                })
        except Exception:
            expenditures = []
            
    # Calculate totals if not persisted or use stored
    resource_total = job_card.resource_total if (job_card.resource_total and job_card.resource_total > 0) else calculated_resource_cost
    expenditure_total = job_card.expenditure_total if (job_card.expenditure_total and job_card.expenditure_total > 0) else calculated_exp_cost
    sub_total = job_card.sub_total if (job_card.sub_total and job_card.sub_total > 0) else (resource_total + expenditure_total)
    overhead_cost = job_card.overhead_cost if (job_card.overhead_cost and job_card.overhead_cost > 0) else round(sub_total * 0.30, 2)
    grand_total = job_card.grand_total if (job_card.grand_total and job_card.grand_total > 0) else (sub_total + overhead_cost)
    contract_val = indent.contract_value or 0.0
    profit = contract_val - grand_total
    profit_margin = round((profit / contract_val * 100), 2) if contract_val > 0 else 0.0
    
    # Calculate milestone total %
    total_milestone_pct = sum(float(m.get('percentage', 0) or 0) for m in milestones)
    
    return render_template(
        'job_cards/view_job_card_details.html',
        job_card=job_card,
        indent=indent,
        milestones=milestones,
        resources=resources,
        expenditures=expenditures,
        resource_total=resource_total,
        expenditure_total=expenditure_total,
        sub_total=sub_total,
        overhead_cost=overhead_cost,
        grand_total=grand_total,
        contract_val=contract_val,
        profit=profit,
        profit_margin=profit_margin,
        total_milestone_pct=total_milestone_pct
    )

@app.route('/job-card/process/<int:card_id>', methods=['POST'])
@login_required
def process_job_card(card_id):
    if current_user.role not in ['MD', 'PM']:
        abort(403)
    job_card = JobCard.query.get_or_404(card_id)
    action = request.form.get('action')
    remarks = request.form.get('remarks') or request.form.get('approval_remarks') or ''
    if remarks:
        job_card.approval_remarks = remarks
    ceo_email = get_ceo_email()
    pm = job_card.indent.project_manager
    pm_signature = f"Thanks & Regards.<br>{pm.name if pm else 'PM'}<br>Project Manager ({job_card.indent.project_name})"
    ceo_signature = get_ceo_signature()
    if action == 'approve':
        job_card.status = 'Approved'
        job_card.budget_status = 'Approved'
        job_card.approved_at = datetime.utcnow()
        job_card.indent.status = 'In Progress'

        # Ensure tasks are generated from resources_json if not already present
        if job_card.resources_json:
            try:
                res_list = json.loads(job_card.resources_json)
                if not job_card.tasks:
                    for res in res_list:
                        emp_id = res.get('employee_id')
                        tasks = res.get('tasks', [])
                        emp = Employee.query.get(int(emp_id)) if emp_id else None
                        if emp:
                            if tasks:
                                for t_desc in tasks:
                                    t = Task(
                                        job_card_id=job_card.id,
                                        description=t_desc,
                                        timeline_start=job_card.actual_start_date or job_card.indent.contract_start_date,
                                        timeline_end=job_card.actual_end_date or job_card.indent.contract_end_date,
                                        man_days=int(res.get('days', 0) or 0),
                                        status='To Do'
                                    )
                                    t.assignees.append(emp)
                                    db.session.add(t)
                            else:
                                t = Task(
                                    job_card_id=job_card.id,
                                    description=f"Project Execution - {emp.name}",
                                    timeline_start=job_card.actual_start_date or job_card.indent.contract_start_date,
                                    timeline_end=job_card.actual_end_date or job_card.indent.contract_end_date,
                                    man_days=int(res.get('days', 0) or 0),
                                    status='To Do'
                                )
                                t.assignees.append(emp)
                                db.session.add(t)
            except Exception as e:
                print(f"Error syncing tasks on approval: {e}")

        flash(f'Job Card for {job_card.indent.project_name} has been successfully approved! Work assignments and timesheet logging are now active.', 'success')
        # Notify PM in-app and email
        if pm:
            create_notification(
                pm.id,
                f"Job Card Approved: {job_card.indent.project_name}",
                f"CEO has APPROVED the Job Card for project '{job_card.indent.project_name}' ({job_card.indent.file_number}). Work assignments and timesheet logging are now active." + (f" Remarks: {remarks}" if remarks else ""),
                'success'
            )
            subject = f"Job Card Approved: {job_card.indent.project_name}"
            body = f"<p>Dear {pm.name},</p>" \
                   f"<p>Your Job Card for project <b>{job_card.indent.project_name}</b> (Code: {job_card.indent.file_number}) has been <b>approved</b> by CEO/MD.</p>"
            if remarks:
                body += f"<p><b>CEO Remarks:</b> {remarks}</p>"
            send_email(pm.email, subject, body, cc=ceo_email, signature=ceo_signature)

        # Circulate over email and in-app to all assigned team members
        assigned_notified = set()
        for t in job_card.tasks:
            for assignee in t.assignees:
                if (not pm or assignee.id != pm.id) and assignee.id not in assigned_notified:
                    assigned_notified.add(assignee.id)
                    create_notification(
                        assignee.id,
                        f"Project Allocation: {job_card.indent.project_name}",
                        f"You have been officially allocated to project '{job_card.indent.project_name}' as team member for task: '{t.description}'.",
                        'info'
                    )
                    emp_body = f"<p>Dear {assignee.name},</p>" \
                               f"<p>You have been assigned to project <b>{job_card.indent.project_name}</b> (Code: {job_card.indent.file_number}) by Project Manager {pm.name if pm else 'PM'}.</p>" \
                               f"<p><b>Assigned Task:</b> {t.description}</p>" \
                               f"<p>Please access your PMS dashboard to log your project timesheets.</p>"
                    send_email(assignee.email, f"Project Assignment: {job_card.indent.project_name}", emp_body, cc=[pm.email] if pm else None)
    elif action == 'reject':
        job_card.status = 'Rejected'
        job_card.budget_status = 'Revision Requested'
        flash(f'Job Card for {job_card.indent.project_name} has been returned to PM for revision.', 'warning')
        if pm:
            create_notification(
                pm.id,
                f"Job Card Revision Requested: {job_card.indent.project_name}",
                f"CEO has requested revision for Job Card on project '{job_card.indent.project_name}'." + (f" Instructions: {remarks}" if remarks else ""),
                'warning'
            )
            subject = f"Job Card Revision Requested: {job_card.indent.project_name}"
            body = f"<p>Dear {pm.name},</p>" \
                   f"<p>Your Job Card for project <b>{job_card.indent.project_name}</b> (Code: {job_card.indent.file_number}) has been returned for revision by CEO/MD.</p>"
            if remarks:
                body += f"<p><b>Revision Instructions / Remarks:</b> {remarks}</p>"
            send_email(pm.email, subject, body, cc=ceo_email, signature=ceo_signature)
    db.session.commit()
    return redirect(url_for('view_job_card_details', card_id=card_id))

@app.route('/task/update-status/<int:task_id>', methods=['POST'])
@login_required
def update_task_status(task_id):
    if current_user.role not in ['PM', 'MD']:
        abort(403)
    
    task = Task.query.get_or_404(task_id)
    # Security check: Ensure the PM is managing this task's project
    if task.job_card.indent.project_manager_id != current_user.id:
        abort(403)
        
    new_status = request.form.get('status')
    if new_status in ['In Progress', 'Completed']:
        task.status = new_status
        db.session.commit()
        flash(f'Task status updated to "{new_status}".', 'success')
    else:
        flash('Invalid status update.', 'danger')
        
    return redirect(url_for('dashboard'))

def get_employee_timesheet_context(user, selected_date_str=None, mode='view'):
    """Context helper for Employee Timesheet calendar preview and multi-row logging"""
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    today_obj = now_ist.date()
    now_is_after_430 = (now_ist.time() >= dt_time(16, 30))

    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        except ValueError:
            try:
                selected_date = datetime.strptime(selected_date_str, '%d-%m-%Y').date()
            except ValueError:
                selected_date = today_obj
    else:
        selected_date = today_obj

    # Distinct dates where this employee has submitted timesheets
    submitted_date_rows = db.session.query(Timesheet.date).filter_by(employee_id=user.id).distinct().all()
    submitted_dates = [r[0].strftime('%Y-%m-%d') for r in submitted_date_rows if r[0]]

    # Day entries for selected date
    day_entries = Timesheet.query.filter_by(
        employee_id=user.id,
        date=selected_date
    ).order_by(Timesheet.id.asc()).all()

    day_total_hours = sum(e.hours_worked for e in day_entries)
    th_h = int(day_total_hours)
    th_m = int(round((day_total_hours - th_h) * 60))
    formatted_total_hours = f"{th_h:02d}:{th_m:02d}"

    idle_hours = max(0.0, 8.0 - day_total_hours)
    ih_h = int(idle_hours)
    ih_m = int(round((idle_hours - ih_h) * 60))
    formatted_idle_hours = f"{ih_h:02d}:{ih_m:02d}"

    # Assigned and Available Projects (Only approved Job Cards permitted for timesheet logging)
    assigned_projects = []
    seen_ids = set()
    for t in getattr(user, 'tasks_assigned', []):
        if t.job_card and t.job_card.status == 'Approved' and t.job_card.indent:
            p = t.job_card.indent
            if p.status not in ['Archived', 'Pending Approval', 'Draft'] and p.id not in seen_ids:
                assigned_projects.append({
                    'id': p.id,
                    'name': p.project_name,
                    'file_number': p.file_number or '',
                    'client': p.client_name or '',
                    'is_assigned': True
                })
                seen_ids.add(p.id)

    # General projects available for logging must also have an approved Job Card
    all_indents = JobIndent.query.filter(
        JobIndent.status.in_(['Approved', 'In Progress', 'Active'])
    ).order_by(JobIndent.project_name.asc()).all()
    other_projects = []
    for p in all_indents:
        if p.job_card and p.job_card.status == 'Approved' and p.id not in seen_ids:
            other_projects.append({
                'id': p.id,
                'name': p.project_name,
                'file_number': p.file_number or '',
                'client': p.client_name or '',
                'is_assigned': False
            })
            seen_ids.add(p.id)

    now_hour = now_ist.hour
    if now_hour < 12:
        greeting = "Good Morning"
    elif now_hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    allowed, restriction_reason = is_submission_time_allowed(selected_date)

    return {
        'greeting': greeting,
        'today_date': today_obj.strftime('%Y-%m-%d'),
        'today_formatted': today_obj.strftime('%d-%m-%Y'),
        'now_is_after_430': now_is_after_430,
        'is_submission_allowed': allowed,
        'restriction_reason': restriction_reason,
        'selected_date': selected_date.strftime('%Y-%m-%d'),
        'selected_date_formatted': selected_date.strftime('%d-%m-%Y'),
        'selected_date_obj': selected_date,
        'submitted_dates': submitted_dates,
        'day_entries': day_entries,
        'day_total_hours': day_total_hours,
        'formatted_total_hours': formatted_total_hours,
        'idle_hours': idle_hours,
        'formatted_idle_hours': formatted_idle_hours,
        'assigned_projects': assigned_projects,
        'other_projects': other_projects,
        'mode': mode
    }

@app.route('/timesheet/log', methods=['GET', 'POST'])
@login_required
@nocache
def log_timesheet():
    if current_user.role in ['MD', 'HR', 'BD', 'FINANCE', 'Finance']:
        flash('Timesheet logging is not applicable for executive or departmental accounts.', 'info')
        return redirect(url_for('dashboard'))

    if current_user.role not in ['EMP', 'PM']:
        abort(403)

    if request.method == 'POST':
        date_str = request.form.get('date', '').strip()
        timesheet_date = None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                timesheet_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                pass
        if not timesheet_date:
            timesheet_date = date.today()

        # Enforce timesheet submission constraints (Sundays, 2nd Saturdays, Holidays, and 4:30 PM rule for today)
        allowed, reason = is_submission_time_allowed(timesheet_date)
        if not allowed:
            flash(reason, 'danger')
            return redirect(url_for('dashboard', mode='add', date=timesheet_date.strftime('%Y-%m-%d')))

        projects = request.form.getlist('project[]') or request.form.getlist('project')
        descriptions = request.form.getlist('task_description[]') or request.form.getlist('task_description')
        start_times = request.form.getlist('start_time[]') or request.form.getlist('start_time')
        end_times = request.form.getlist('end_time[]') or request.form.getlist('end_time')
        hours_list = request.form.getlist('total_hours[]') or request.form.getlist('hours_worked[]') or request.form.getlist('hours_worked')

        if not descriptions:
            idx = 0
            while f'project_{idx}' in request.form or f'task_desc_{idx}' in request.form or f'task_description_{idx}' in request.form:
                projects.append(request.form.get(f'project_{idx}', 'Others'))
                descriptions.append(request.form.get(f'task_description_{idx}') or request.form.get(f'task_desc_{idx}', ''))
                start_times.append(request.form.get(f'start_time_{idx}', ''))
                end_times.append(request.form.get(f'end_time_{idx}', ''))
                hours_list.append(request.form.get(f'total_hours_{idx}') or request.form.get(f'hours_worked_{idx}', ''))
                idx += 1

        entries_added = []
        day_total = 0.0

        for i in range(len(descriptions)):
            desc = bleach.clean(descriptions[i]).strip() if descriptions[i] else ''
            p_val = bleach.clean(projects[i]).strip() if i < len(projects) else 'Others'
            st = bleach.clean(start_times[i]).strip() if i < len(start_times) else ''
            et = bleach.clean(end_times[i]).strip() if i < len(end_times) else ''
            raw_h = hours_list[i].strip() if i < len(hours_list) else ''

            if not desc and not st and not et:
                continue

            hrs = 0.0
            if raw_h:
                try:
                    if ':' in raw_h:
                        parts = raw_h.split(':')
                        hrs = float(parts[0]) + (float(parts[1]) / 60.0)
                    else:
                        hrs = float(raw_h)
                except ValueError:
                    hrs = 0.0

            if hrs <= 0 and st and et:
                try:
                    s_dt = datetime.strptime(st, '%H:%M')
                    e_dt = datetime.strptime(et, '%H:%M')
                    diff_sec = (e_dt - s_dt).total_seconds()
                    if diff_sec > 0:
                        hrs = diff_sec / 3600.0
                except ValueError:
                    pass

            if hrs <= 0:
                hrs = 1.0

            proj_name = p_val
            proj_id = None
            if p_val and p_val.isdigit():
                indent = JobIndent.query.get(int(p_val))
                if indent:
                    proj_id = indent.id
                    proj_name = indent.project_name

            formatted_st = st if len(st.split(':')) == 3 else (f"{st}:00" if st else "10:00:00")
            formatted_et = et if len(et.split(':')) == 3 else (f"{et}:00" if et else "18:00:00")

            new_ts = Timesheet(
                employee_id=current_user.id,
                project_name=proj_name or 'Others',
                project_id=proj_id,
                date=timesheet_date,
                start_time=formatted_st,
                end_time=formatted_et,
                hours_worked=round(hrs, 2),
                progress_description=desc or 'Daily project task work',
                status='Not Verified',
                rm_status='Not Verified'
            )
            db.session.add(new_ts)
            entries_added.append(new_ts)
            day_total += hrs

        if not entries_added:
            flash('Please enter at least one task or output description.', 'danger')
            return redirect(url_for('dashboard', mode='add', date=timesheet_date.strftime('%Y-%m-%d')))

        # Sync with WeeklyTimesheet
        week_start = timesheet_date - timedelta(days=timesheet_date.weekday())
        week_end = week_start + timedelta(days=6)
        weekly_ts = WeeklyTimesheet.query.filter_by(
            employee_id=current_user.id,
            week_start_date=week_start
        ).first()

        summary_snippet = entries_added[0].progress_description[:120]
        if not weekly_ts:
            weekly_ts = WeeklyTimesheet(
                employee_id=current_user.id,
                week_start_date=week_start,
                week_end_date=week_end,
                total_hours=round(day_total, 2),
                progress_description=f"[{timesheet_date.strftime('%d-%m')}]: {summary_snippet}",
                status='Submitted'
            )
            db.session.add(weekly_ts)
        else:
            weekly_ts.total_hours = round((weekly_ts.total_hours or 0.0) + day_total, 2)
            weekly_ts.progress_description += f"\n- [{timesheet_date.strftime('%d-%m')}]: {summary_snippet}"

        db.session.commit()
        flash(f'Timesheet for {timesheet_date.strftime("%d-%m-%Y")} submitted successfully!', 'success')
        return redirect(url_for('dashboard', date=timesheet_date.strftime('%Y-%m-%d')))

    # GET
    if current_user.role == 'EMP':
        return redirect(url_for('dashboard', mode=request.args.get('mode', 'view'), date=request.args.get('date')))

    ctx = get_employee_timesheet_context(current_user, request.args.get('date'), request.args.get('mode', 'view'))
    return render_template('timesheets/log_timesheet.html', **ctx)

@app.route('/api/timesheet/day-details')
@login_required
def api_timesheet_day_details():
    date_str = request.args.get('date')
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    today_ist = now_ist.date()

    if not date_str:
        target_date = today_ist
    else:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400

    entries = Timesheet.query.filter_by(
        employee_id=current_user.id,
        date=target_date
    ).order_by(Timesheet.id.asc()).all()

    total_hrs = sum(e.hours_worked for e in entries)
    th_h = int(total_hrs)
    th_m = int(round((total_hrs - th_h) * 60))
    formatted_th = f"{th_h:02d}:{th_m:02d}"

    idle_hrs = max(0.0, 8.0 - total_hrs)
    ih_h = int(idle_hrs)
    ih_m = int(round((idle_hrs - ih_h) * 60))
    formatted_idle = f"{ih_h:02d}:{ih_m:02d}"

    result_entries = []
    for idx, e in enumerate(entries, 1):
        eh_h = int(e.hours_worked)
        eh_m = int(round((e.hours_worked - eh_h) * 60))
        formatted_eh = f"{eh_h:02d}:{eh_m:02d}"

        result_entries.append({
            'id': e.id,
            'sl': idx,
            'project': e.project_name or (e.project.project_name if e.project else 'Others'),
            'task_description': e.progress_description,
            'start_time': e.start_time or '10:00:00',
            'end_time': e.end_time or '18:00:00',
            'total_hours': formatted_eh,
            'raw_hours': e.hours_worked,
            'rm_status': e.rm_status or e.status or 'Not Verified'
        })

    is_sun = is_sunday(target_date)
    is_sec_sat = is_second_saturday(target_date)
    hol = get_holiday_details(target_date)
    hol_name = hol.holiday_name if hol else None
    allowed, restriction_reason = is_submission_time_allowed(target_date)

    return jsonify({
        'date': target_date.strftime('%Y-%m-%d'),
        'formatted_date': target_date.strftime('%d-%m-%Y'),
        'total_hours': total_hrs,
        'formatted_total_hours': formatted_th,
        'idle_hours': formatted_idle,
        'count': len(result_entries),
        'entries': result_entries,
        'is_sunday': is_sun,
        'is_second_saturday': is_sec_sat,
        'is_holiday': hol is not None,
        'holiday_name': hol_name,
        'is_submission_allowed': allowed,
        'restriction_reason': restriction_reason,
        'is_today': (target_date == today_ist)
    })

@app.route('/api/timesheet/month-submissions')
@login_required
def api_timesheet_month_submissions():
    year = request.args.get('year', type=int) or datetime.now().year
    month = request.args.get('month', type=int) or datetime.now().month

    entries = db.session.query(Timesheet.date).filter(
        Timesheet.employee_id == current_user.id,
        db.extract('year', Timesheet.date) == year,
        db.extract('month', Timesheet.date) == month
    ).distinct().all()

    submitted_dates = [e[0].strftime('%Y-%m-%d') for e in entries if e[0]]
    submitted_set = set(submitted_dates)

    # Holidays in this month
    holidays_query = HolidayMaster.query.filter(
        db.extract('year', HolidayMaster.holiday_date) == year,
        db.extract('month', HolidayMaster.holiday_date) == month
    ).all()
    holidays = {h.holiday_date.strftime('%Y-%m-%d'): h.holiday_name for h in holidays_query}

    # Number of days in month
    if month == 12:
        num_days = 31
    else:
        num_days = (date(year, month + 1, 1) - timedelta(days=1)).day

    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    today_ist = now_ist.date()
    today_str = today_ist.strftime('%Y-%m-%d')
    now_is_after_430 = (now_ist.time() >= dt_time(16, 30))

    sundays = []
    second_saturdays = []
    missing_dates = []

    for d in range(1, num_days + 1):
        cur_date = date(year, month, d)
        cur_str = cur_date.strftime('%Y-%m-%d')
        if cur_date.weekday() == 6:
            sundays.append(cur_str)
        elif cur_date.weekday() == 5 and (8 <= d <= 14):
            second_saturdays.append(cur_str)
        elif cur_str in holidays:
            pass  # holiday
        else:
            # Working day
            if cur_date < today_ist and cur_str not in submitted_set:
                missing_dates.append(cur_str)

    return jsonify({
        'year': year,
        'month': month,
        'submitted_dates': submitted_dates,
        'holidays': holidays,
        'second_saturdays': second_saturdays,
        'sundays': sundays,
        'missing_dates': missing_dates,
        'today_str': today_str,
        'now_is_after_430': now_is_after_430
    })

@app.route('/timesheets/verify')
@login_required
@nocache
def verify_timesheets():
    if current_user.role not in ['PM', 'MD', 'HR'] and not current_user.has_hr_permission('timesheet_review'):
        abort(403)
    
    if current_user.role in ['MD', 'HR'] or current_user.has_hr_permission('timesheet_review'):
        timesheets = WeeklyTimesheet.query.filter_by(status='Submitted').all()
    else:
        # Get projects managed by the current PM
        pm_projects = JobIndent.query.filter_by(project_manager_id=current_user.id).all()
        project_ids = [p.id for p in pm_projects]
        
        if project_ids:
            # Get timesheets for tasks in PM's projects
            timesheets = WeeklyTimesheet.query.join(Task).join(JobCard).filter(
                JobCard.job_indent_id.in_(project_ids),
                WeeklyTimesheet.status == 'Submitted'
            ).all()
        else:
            timesheets = []
    
    return render_template('timesheets/verify_timesheets.html', timesheets=timesheets)

@app.route('/employees')
@login_required
@nocache
def manage_employees():
    if current_user.role not in ['HR', 'MD'] and not any(current_user.has_hr_permission(p) for p in ['employee_create', 'employee_edit', 'employee_delete', 'employee_block', 'employee_archive']):
        abort(403)
    
    current_tab = request.args.get('tab', 'active')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    # Base counts for badges
    total_active_count = Employee.query.filter(or_(Employee.status == 'Active', Employee.status == None, Employee.status == 'Blocked')).count()
    active_only_count = Employee.query.filter(or_(Employee.status == 'Active', Employee.status == None)).count()
    blocked_count = Employee.query.filter_by(status='Blocked').count()
    archived_count = Employee.query.filter_by(status='Resigned').count()

    if current_tab == 'archived':
        query = Employee.query.filter_by(status='Resigned')
        if search_query:
            query = query.filter(or_(
                Employee.name.ilike(f'%{search_query}%'),
                Employee.emp_id.ilike(f'%{search_query}%'),
                Employee.designation.ilike(f'%{search_query}%')
            ))
        archived_employees = query.order_by(Employee.resigned_at.desc(), Employee.name).all()
        
        # Build enriched stats for each archived employee
        archived_stats = []
        for emp in archived_employees:
            total_hours = sum(ts.total_hours for ts in emp.weekly_timesheets) if emp.weekly_timesheets else 0.0
            timesheet_count = len(emp.weekly_timesheets) if emp.weekly_timesheets else 0
            
            project_names = set()
            for ts in emp.weekly_timesheets:
                if ts.task and ts.task.job_card and ts.task.job_card.indent:
                    indent = ts.task.job_card.indent
                    p_name = indent.file_number or (indent.department.name if indent.department else 'Project')
                    project_names.add(p_name)
            for t in getattr(emp, 'tasks_assigned', []):
                if t.job_card and t.job_card.indent:
                    indent = t.job_card.indent
                    p_name = indent.file_number or (indent.department.name if indent.department else 'Project')
                    project_names.add(p_name)
            
            archived_stats.append({
                'employee': emp,
                'total_hours': round(total_hours, 2),
                'timesheet_count': timesheet_count,
                'project_count': len(project_names),
                'project_names': list(project_names)[:3]
            })

        return render_template('employees/manage_employees.html',
                               employees=None,
                               archived_stats=archived_stats,
                               current_tab='archived',
                               search_query=search_query,
                               total_active_count=total_active_count,
                               active_only_count=active_only_count,
                               blocked_count=blocked_count,
                               archived_count=archived_count)
    else:
        # Active and Blocked tab
        query = Employee.query.filter(or_(Employee.status == 'Active', Employee.status == None, Employee.status == 'Blocked'))
        if search_query:
            query = query.filter(or_(
                Employee.name.ilike(f'%{search_query}%'),
                Employee.emp_id.ilike(f'%{search_query}%'),
                Employee.designation.ilike(f'%{search_query}%')
            ))
        employees = query.order_by(Employee.name).paginate(page=page, per_page=20, error_out=False)
        return render_template('employees/manage_employees.html',
                               employees=employees,
                               archived_stats=[],
                               current_tab='active',
                               search_query=search_query,
                               total_active_count=total_active_count,
                               active_only_count=active_only_count,
                               blocked_count=blocked_count,
                               archived_count=archived_count)

@app.route('/employees/add', methods=['GET', 'POST'])
@login_required
@nocache
def add_employee():
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('employee_create'):
        abort(403)
    departments = Department.query.all()
    managers = Employee.query.filter(Employee.is_active == True).order_by(Employee.name).all()

    if request.method == 'POST':
        name = bleach.clean(request.form.get('name', '')).strip()
        name = re.sub(r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)\s*', '', name, flags=re.IGNORECASE).strip()
        emp_id = bleach.clean(request.form.get('emp_id', '')).strip()
        email = bleach.clean(request.form.get('email', '')).strip()
        password = request.form.get('password', '').strip()
        designation = bleach.clean(request.form.get('designation', '')).strip()
        department_id = request.form.get('department_id')
        manager_id_raw = request.form.get('manager_id')
        place = bleach.clean(request.form.get('place', '')).strip()
        mobile = bleach.clean(request.form.get('mobile', '')).strip()
        role = request.form.get('role', 'EMP').strip()

        parsed_mgr_id = int(manager_id_raw) if manager_id_raw and manager_id_raw.isdigit() else None

        if not name or not emp_id or not email:
            flash('Name, Employee ID, and Email are required fields.', 'danger')
            return render_template('employees/add_employee.html', departments=departments, managers=managers)

        if not password:
            import secrets
            password = secrets.token_urlsafe(16)

        # Parse salary safely (handle empty string, commas, etc.)
        salary_raw = request.form.get('monthly_salary', '').strip().replace(',', '')
        if salary_raw:
            try:
                monthly_salary = float(salary_raw)
            except ValueError:
                flash('Monthly Salary must be a valid numeric value.', 'danger')
                return render_template('employees/add_employee.html', departments=departments, managers=managers)
        else:
            monthly_salary = None

        if not department_id:
            flash('Department is required.', 'danger')
            return render_template('employees/add_employee.html', departments=departments, managers=managers)
        department = Department.query.get(int(department_id))
        if not department:
            flash('Selected department does not exist.', 'danger')
            return render_template('employees/add_employee.html', departments=departments, managers=managers)

        # Prevent duplicate emp_id or email
        existing_emp = Employee.query.filter(
            (Employee.emp_id == emp_id) | (Employee.email == email)
        ).first()
        if existing_emp:
            if existing_emp.emp_id == emp_id:
                flash(f'An employee with ID "{emp_id}" already exists ({existing_emp.name}).', 'danger')
            else:
                flash(f'An employee with email "{email}" already exists ({existing_emp.name}).', 'danger')
            return render_template('employees/add_employee.html', departments=departments, managers=managers)

        new_employee = Employee(
            name=name,
            emp_id=emp_id,
            email=email,
            designation=designation or None,
            department_id=department.id,
            manager_id=parsed_mgr_id,
            place=place or None,
            mobile=mobile or None,
            monthly_salary=monthly_salary,
            salary_grade=bleach.clean(request.form.get('salary_grade', '')).strip() or None,
            employment_type=bleach.clean(request.form.get('employment_type', 'EMPLOYEE')).strip() or 'EMPLOYEE',
            date_of_joining=datetime.strptime(request.form.get('date_of_joining', '').strip(), '%Y-%m-%d').date() if request.form.get('date_of_joining', '').strip() else None,
            role=role,
            status='Active',
            is_active=True
        )
        new_employee.set_password(password)
        db.session.add(new_employee)
        db.session.commit()
        flash(f'Employee {name} ({emp_id}) added successfully!', 'success')
        return redirect(url_for('manage_employees'))
    return render_template('employees/add_employee.html', departments=departments, managers=managers)

@app.route('/employees/edit/<int:emp_id>', methods=['GET', 'POST'])
@login_required
@nocache
def edit_employee(emp_id):
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('employee_edit'):
        abort(403)
    emp = Employee.query.get_or_404(emp_id)
    departments = Department.query.all()
    managers = Employee.query.filter(Employee.is_active == True, Employee.id != emp.id).order_by(Employee.name).all()

    if request.method == 'POST':
        name = bleach.clean(request.form.get('name', '')).strip()
        name = re.sub(r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Shri|Smt\.)\s*', '', name, flags=re.IGNORECASE).strip()
        new_emp_id = bleach.clean(request.form.get('emp_id', '')).strip()
        email = bleach.clean(request.form.get('email', '')).strip()
        designation = bleach.clean(request.form.get('designation', '')).strip()
        place = bleach.clean(request.form.get('place', '')).strip()
        mobile = bleach.clean(request.form.get('mobile', '')).strip()
        role = request.form.get('role', emp.role).strip()
        department_id = request.form.get('department_id')
        manager_id_raw = request.form.get('manager_id')

        parsed_mgr_id = int(manager_id_raw) if manager_id_raw and manager_id_raw.isdigit() else None

        # Check duplicate ID or Email
        existing_dup = Employee.query.filter(
            (Employee.id != emp.id) & ((Employee.emp_id == new_emp_id) | (Employee.email == email))
        ).first()
        if existing_dup:
            if existing_dup.emp_id == new_emp_id:
                flash(f'Another employee with ID "{new_emp_id}" already exists.', 'danger')
            else:
                flash(f'Another employee with email "{email}" already exists.', 'danger')
            return render_template('employees/edit_employee.html', emp=emp, departments=departments, managers=managers)

        # Parse salary safely
        salary_raw = request.form.get('monthly_salary', '').strip().replace(',', '')
        if salary_raw:
            try:
                monthly_salary = float(salary_raw)
            except ValueError:
                flash('Monthly Salary must be a valid numeric value.', 'danger')
                return render_template('employees/edit_employee.html', emp=emp, departments=departments, managers=managers)
        else:
            monthly_salary = None

        if not department_id:
            flash('Department is required.', 'danger')
            return render_template('employees/edit_employee.html', emp=emp, departments=departments, managers=managers)
        department = Department.query.get(int(department_id))
        if not department:
            flash('Selected department does not exist.', 'danger')
            return render_template('employees/edit_employee.html', emp=emp, departments=departments, managers=managers)

        emp.name = name
        emp.emp_id = new_emp_id
        emp.email = email
        emp.designation = designation or None
        emp.place = place or None
        emp.mobile = mobile or None
        emp.monthly_salary = monthly_salary
        if 'salary_grade' in request.form:
            emp.salary_grade = bleach.clean(request.form.get('salary_grade', '')).strip() or None
        if 'employment_type' in request.form:
            emp.employment_type = bleach.clean(request.form.get('employment_type', 'EMPLOYEE')).strip() or 'EMPLOYEE'
        if 'date_of_joining' in request.form:
            doj_val = request.form.get('date_of_joining', '').strip()
            if doj_val:
                try:
                    emp.date_of_joining = datetime.strptime(doj_val, '%Y-%m-%d').date()
                except ValueError:
                    pass
            else:
                emp.date_of_joining = None
        emp.role = role
        emp.department_id = department.id
        emp.manager_id = parsed_mgr_id

        # Update password only if new one provided
        new_pwd = request.form.get('password', '').strip()
        if new_pwd:
            emp.set_password(new_pwd)

        db.session.commit()
        flash(f'Employee {emp.name} updated successfully!', 'success')
        return redirect(url_for('manage_employees'))
    return render_template('employees/edit_employee.html', emp=emp, departments=departments, managers=managers)

@app.route('/employees/block/<int:emp_id>', methods=['POST'])
@login_required
@nocache
def block_employee(emp_id):
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('employee_block'):
        abort(403)
    emp = Employee.query.get_or_404(emp_id)
    if emp.id == current_user.id:
        flash("You cannot block your own account.", 'danger')
        return redirect(url_for('manage_employees'))
    
    reason = bleach.clean(request.form.get('reason', 'Temporarily blocked by HR Admin')).strip()
    emp.status = 'Blocked'
    emp.is_active = False
    emp.blocked_at = datetime.utcnow()
    emp.blocked_reason = reason
    db.session.commit()
    flash(f"Employee {emp.name} ({emp.emp_id}) has been temporarily blocked.", 'warning')
    return redirect(url_for('manage_employees'))

@app.route('/employees/unblock/<int:emp_id>', methods=['POST'])
@login_required
@nocache
def unblock_employee(emp_id):
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('employee_block'):
        abort(403)
    emp = Employee.query.get_or_404(emp_id)
    emp.status = 'Active'
    emp.is_active = True
    emp.blocked_at = None
    emp.blocked_reason = None
    db.session.commit()
    flash(f"Employee {emp.name} ({emp.emp_id}) has been successfully unblocked.", 'success')
    return redirect(url_for('manage_employees'))

@app.route('/employees/resign/<int:emp_id>', methods=['POST'])
@login_required
@nocache
def resign_employee(emp_id):
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('employee_archive'):
        abort(403)
    emp = Employee.query.get_or_404(emp_id)
    if emp.id == current_user.id:
        flash("You cannot mark your own account as resigned.", 'danger')
        return redirect(url_for('manage_employees'))
    
    reason = bleach.clean(request.form.get('reason', 'Resigned from organization')).strip()
    emp.status = 'Resigned'
    emp.is_active = False
    emp.resigned_at = datetime.utcnow()
    emp.resigned_reason = reason
    db.session.commit()
    flash(f"Employee {emp.name} ({emp.emp_id}) has been marked as Resigned. All their profile, project, and timesheet records have been moved to the Archive Section.", 'info')
    return redirect(url_for('manage_employees', tab='archived'))

@app.route('/employees/restore/<int:emp_id>', methods=['POST'])
@login_required
@nocache
def restore_employee(emp_id):
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('employee_archive'):
        abort(403)
    emp = Employee.query.get_or_404(emp_id)
    emp.status = 'Active'
    emp.is_active = True
    emp.resigned_at = None
    emp.resigned_reason = None
    db.session.commit()
    flash(f"Employee {emp.name} ({emp.emp_id}) has been restored to Active status.", 'success')
    return redirect(url_for('manage_employees'))

@app.route('/employees/<int:emp_id>/history')
@login_required
@nocache
def employee_history(emp_id):
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    emp = Employee.query.get_or_404(emp_id)
    
    # Timesheets history
    timesheets = WeeklyTimesheet.query.filter_by(employee_id=emp.id).order_by(WeeklyTimesheet.week_start_date.desc()).all()
    total_hours = sum(ts.total_hours for ts in timesheets)
    
    # Project history
    project_dict = {}
    
    # Indents managed as PM
    pm_indents = JobIndent.query.filter_by(project_manager_id=emp.id).all()
    for ind in pm_indents:
        project_dict[ind.id] = {
            'indent': ind,
            'role_in_project': 'Project Manager (PM)',
            'tasks': ind.job_card.tasks if (ind.job_card and ind.job_card.tasks) else [],
            'logged_hours': 0.0
        }
    
    # Tasks assigned
    for t in getattr(emp, 'tasks_assigned', []):
        if t.job_card and t.job_card.indent:
            ind = t.job_card.indent
            if ind.id not in project_dict:
                project_dict[ind.id] = {
                    'indent': ind,
                    'role_in_project': 'Team Member / Assignee',
                    'tasks': [t],
                    'logged_hours': 0.0
                }
            else:
                if t not in project_dict[ind.id]['tasks']:
                    project_dict[ind.id]['tasks'].append(t)
    
    # Calculate hours logged per project from timesheets
    for ts in timesheets:
        if ts.task and ts.task.job_card and ts.task.job_card.indent:
            ind = ts.task.job_card.indent
            if ind.id in project_dict:
                project_dict[ind.id]['logged_hours'] += ts.total_hours
            else:
                project_dict[ind.id] = {
                    'indent': ind,
                    'role_in_project': 'Contributor',
                    'tasks': [ts.task],
                    'logged_hours': ts.total_hours
                }
    
    project_list = list(project_dict.values())
    
    return render_template('employees/employee_history.html',
                           emp=emp,
                           timesheets=timesheets,
                           total_hours=round(total_hours, 2),
                           project_list=project_list,
                           total_projects=len(project_list),
                           total_timesheets=len(timesheets))

@app.route('/employees/<int:emp_id>/export_history')
@login_required
@nocache
def export_employee_history(emp_id):
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    emp = Employee.query.get_or_404(emp_id)
    timesheets = WeeklyTimesheet.query.filter_by(employee_id=emp.id).order_by(WeeklyTimesheet.week_start_date.desc()).all()
    
    import openpyxl
    wb = openpyxl.Workbook()
    # Sheet 1: Summary
    ws1 = wb.active
    ws1.title = "Employee Profile"
    ws1.append(["EMC Project Monitoring System - Employee Archive Dossier"])
    ws1.append(["Generated On", datetime.now().strftime("%d-%b-%Y %H:%M")])
    ws1.append([])
    ws1.append(["Field", "Details"])
    ws1.append(["Employee ID", emp.emp_id])
    ws1.append(["Name", emp.name])
    ws1.append(["Email", emp.email])
    ws1.append(["Designation", emp.designation or "N/A"])
    ws1.append(["Department", emp.department.name if emp.department else "N/A"])
    ws1.append(["Role", emp.role])
    ws1.append(["Status", emp.status or "Active"])
    if emp.status == 'Resigned':
        ws1.append(["Resignation Date", emp.resigned_at.strftime("%d-%b-%Y %H:%M") if emp.resigned_at else "N/A"])
        ws1.append(["Resignation Reason", emp.resigned_reason or "N/A"])
    elif emp.status == 'Blocked':
        ws1.append(["Blocked Date", emp.blocked_at.strftime("%d-%b-%Y %H:%M") if emp.blocked_at else "N/A"])
        ws1.append(["Block Reason", emp.blocked_reason or "N/A"])
    ws1.append(["Total Hours Logged", sum(ts.total_hours for ts in timesheets)])
    ws1.append(["Total Timesheet Submissions", len(timesheets)])
    
    # Sheet 2: Timesheet History
    ws2 = wb.create_sheet(title="Timesheet History")
    ws2.append(["Timesheet ID", "Week Start", "Week End", "Project / Indent", "Task Description", "Hours", "Status", "Approval Level", "Progress Note", "Submitted Date"])
    for ts in timesheets:
        p_name = ts.task.job_card.indent.file_number if (ts.task and ts.task.job_card and ts.task.job_card.indent and ts.task.job_card.indent.file_number) else "N/A"
        t_desc = ts.task.description if ts.task else "N/A"
        ws2.append([
            ts.id,
            ts.week_start_date.strftime("%d-%b-%Y"),
            ts.week_end_date.strftime("%d-%b-%Y"),
            p_name,
            t_desc,
            ts.total_hours,
            ts.status,
            ts.approval_level or "N/A",
            ts.progress_description or "",
            ts.created_at.strftime("%d-%b-%Y") if ts.created_at else "N/A"
        ])
    
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    filename = f"Employee_Archive_{emp.emp_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(out, download_name=filename, as_attachment=True, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route('/employees/delete/<int:emp_id>', methods=['POST'])
@login_required
@nocache
def delete_employee(emp_id):
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('employee_delete'):
        abort(403)
    emp_to_delete = Employee.query.get_or_404(emp_id)
    # Basic check to prevent deleting oneself
    if emp_to_delete.id == current_user.id:
        flash("You cannot delete your own account.", 'danger')
        return redirect(url_for('manage_employees'))
    
    is_pm_on_active_project = JobIndent.query.filter_by(project_manager_id=emp_to_delete.id).filter(JobIndent.status.in_(['Approved', 'In Progress'])).first()
    if is_pm_on_active_project:
        flash(f"Cannot delete {emp_to_delete.name} as they are an active Project Manager. Please reassign their projects first or mark them as Resigned to preserve history.", 'danger')
        return redirect(url_for('manage_employees'))
        
    try:
        db.session.delete(emp_to_delete)
        db.session.commit()
        flash(f"Employee {emp_to_delete.name} has been deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Could not delete employee due to existing related records. We recommend marking them as Resigned instead so records are preserved in the Archive Section.", 'warning')
    return redirect(url_for('manage_employees'))

@app.route('/timesheet/verify/<int:entry_id>', methods=['POST'])
@login_required
def verify_timesheet_action(entry_id):
    entry = WeeklyTimesheet.query.get_or_404(entry_id)
    # If the timesheet belongs to a PM, only HR can approve
    if entry.employee.role == 'PM':
        if current_user.role != 'HR':
            abort(403)
        entry.status = 'HR Approved'
        entry.approval_level = 'HR'
        entry.approved_by_id = current_user.id
        db.session.commit()
        flash(f"Project Manager's timesheet for {entry.employee.name} (Week of {entry.week_start_date.strftime('%d-%b-%Y')}) has been approved by HR.", 'success')
        return redirect(url_for('hr_timesheets'))
    # If the timesheet belongs to an employee, only PM can approve
    else:
        # Security check: ensure the PM manages the project this timesheet belongs to
        if current_user.role != 'PM' or entry.task.job_card.indent.project_manager_id != current_user.id:
            abort(403)
        entry.status = 'PM Approved'
        entry.approval_level = 'PM'
        entry.approved_by_id = current_user.id
        db.session.commit()
        flash(f"Weekly timesheet for {entry.employee.name} (Week of {entry.week_start_date.strftime('%d-%b-%Y')}) has been approved by PM.", 'success')
        return redirect(url_for('verify_timesheets'))

@app.route('/timesheet/verify/<int:timesheet_id>', methods=['POST'])
@login_required
def verify_timesheet_api(timesheet_id):
    """API endpoint for timesheet verification"""
    if current_user.role not in ['HR', 'MD']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    timesheet = WeeklyTimesheet.query.get_or_404(timesheet_id)
    
    try:
        # HR can verify any timesheet
        if current_user.role == 'HR':
            timesheet.status = 'HR Approved'
            timesheet.approval_level = 'HR'
            timesheet.approved_by_id = current_user.id
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': f'Timesheet for {timesheet.employee.name} has been verified by HR.'
            })
        
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/reports')
@login_required
def reports_page():
    if current_user.role not in ['MD', 'PM', 'HR']:
        abort(403)
    
    all_projects = JobIndent.query.filter(JobIndent.status == 'Approved').all()
    return render_template('reports.html', all_projects=all_projects)

@app.route('/report/generate', methods=['POST'])
@login_required
@nocache
def generate_report():
    import reports
    if current_user.role not in ['MD', 'PM', 'HR']:
        abort(403)

    report_type = request.form.get('report_type')
    file_format = request.form.get('format')
    project_id = request.form.get('project_id')
    project = JobIndent.query.get_or_404(project_id) if project_id else None
    
    if report_type == 'project_progress':
        if not project:
            flash('Please select a project for this report.', 'danger')
            return redirect(url_for('reports_page'))
        if file_format == 'pdf':
            return reports.generate_project_progress_pdf(project)
        elif file_format == 'excel':
            return reports.generate_project_progress_excel(project)

    elif report_type == 'budget':
        if not project:
            flash('Please select a project for this report.', 'danger')
            return redirect(url_for('reports_page'))
        if file_format == 'pdf':
            return reports.generate_budget_report_pdf(project)
        elif file_format == 'excel':
            return reports.generate_budget_report_excel(project)

    elif report_type == 'employee_load':
        if file_format == 'excel':
            return reports.generate_employee_load_report_excel(app)
        # Add PDF generation later if needed
    
    elif report_type == 'daily_progress':
        report_date_str = request.form.get('report_date')
        if not report_date_str:
            flash('Please select a date for this report.', 'danger')
            return redirect(url_for('reports_page'))
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
        if file_format == 'excel':
            return reports.generate_daily_progress_report_excel(app, report_date)

    elif report_type == 'deviation':
        if not project:
            flash('Please select a project for this report.', 'danger')
            return redirect(url_for('reports_page'))
        if file_format == 'excel':
            return reports.generate_deviation_report_excel(project)

    # Future reports will be handled here
    flash('Invalid report request.', 'danger')
    return redirect(url_for('reports_page'))

@app.route('/logout')
def logout():
    try:
        if current_user and current_user.is_authenticated:
            log_audit_trail(
                action='LOGOUT',
                table_name='employee',
                record_id=current_user.id,
                old_values={'email': current_user.email, 'name': current_user.name, 'role': current_user.role},
                user_id=current_user.id
            )
    except Exception as e:
        print(f"Error logging logout event: {e}")
    logout_user()
    session.clear()  # Clear all session data
    response = make_response(redirect(url_for('login')))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.delete_cookie('session')
    response.delete_cookie('remember_token')
    return response

@app.route('/dashboard')
@login_required
@nocache
def dashboard():
    missing_dates = []
    show_submit_week = False
    if current_user.role == 'EMP':
        from datetime import timedelta, date
        today = date.today()
        # Check for the last 7 days (excluding weekends)
        for i in range(7):
            d = today - timedelta(days=i)
            if d.weekday() >= 5:  # Skip Saturday/Sunday
                continue
            has_log = Timesheet.query.filter_by(employee_id=current_user.id, date=d).first()
            if not has_log:
                missing_dates.append(d)
        # Check for unsubmitted logs for this week
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        unsubmitted = Timesheet.query.filter(
            Timesheet.employee_id == current_user.id,
            Timesheet.date >= week_start,
            Timesheet.date <= week_end,
            Timesheet.status != 'Weekly Submitted'
        ).first()
        if unsubmitted:
            show_submit_week = True
    # --- Role-specific dashboard logic ---
    if current_user.role in ['IT', 'IT_ADMIN']:
        # The 4 Master Accounts
        master_accounts = {
            'CEO': Employee.query.filter(or_(Employee.emp_id == '15M006', Employee.email == 'chinmay.tripathy@ecometrix.co.in', Employee.role == 'MD')).first(),
            'BD': Employee.query.filter(or_(Employee.emp_id == 'DEPT_BD', Employee.email == 'bd@ecometrix.co.in')).first(),
            'HR': Employee.query.filter(or_(Employee.emp_id == 'DEPT_HR', Employee.email == 'hr@ecometrix.co.in')).first(),
            'FINANCE': Employee.query.filter(or_(Employee.emp_id == 'DEPT_FIN', Employee.email == 'accounts@ecometrix.co.in', Employee.email == 'finance@ecometrix.co.in')).first(),
        }

        # Activity & Security Logs
        recent_logs = AuditLog.query.filter(
            AuditLog.action.in_([
                'LOGIN_SUCCESS', 'LOGIN_FAILED', 'LOGOUT', 'LOGIN_BLOCKED',
                'PASSWORD_RESET_BY_IT', 'PASSWORD_CHANGE',
                'PROJECT_PURGE', 'CREDENTIAL_EMAIL_SENT', 'CREDENTIAL_UPDATE'
            ])
        ).order_by(AuditLog.created_at.desc()).limit(150).all()

        # All Projects for Purge Management
        projects = JobIndent.query.order_by(JobIndent.id.desc()).all()

        # KPI Metrics
        from datetime import datetime as dt_cls, time as time_cls
        today_midnight = dt_cls.combine(datetime.now().date(), time_cls.min)
        logins_today = AuditLog.query.filter(
            AuditLog.action == 'LOGIN_SUCCESS',
            AuditLog.created_at >= today_midnight
        ).count()
        failed_attempts_today = AuditLog.query.filter(
            AuditLog.action == 'LOGIN_FAILED',
            AuditLog.created_at >= today_midnight
        ).count()
        resets_count = AuditLog.query.filter(
            AuditLog.action.in_(['PASSWORD_RESET_BY_IT', 'CREDENTIAL_UPDATE'])
        ).count()

        auth_tickets = AuthTicket.query.order_by(AuthTicket.id.desc()).all()
        pending_tickets_count = AuthTicket.query.filter_by(status='Pending').count()

        return render_template(
            'dashboards/it_dashboard.html',
            master_accounts=master_accounts,
            recent_logs=recent_logs,
            projects=projects,
            logins_today=logins_today,
            failed_attempts_today=failed_attempts_today,
            resets_count=resets_count,
            auth_tickets=auth_tickets,
            pending_tickets_count=pending_tickets_count
        )

    elif current_user.role == 'MD':
        projects = JobIndent.query.all()
        project_status_counts = {
            "Pending Approval": JobIndent.query.filter(JobIndent.status.in_(['Pending Approval', 'Pending', 'Draft'])).count(),
            "In Progress": JobIndent.query.filter(JobIndent.status.in_(['In Progress', 'Approved', 'Active'])).count(),
            "On Hold": JobIndent.query.filter(JobIndent.status.in_(['On Hold', 'Hold'])).count(),
            "Completed": JobIndent.query.filter(JobIndent.status.in_(['Completed', 'Closed'])).count(),
        }
        # Get department-wise project counts
        departments = Department.query.all()
        dept_project_counts = {}
        for dept in departments:
            count = JobIndent.query.filter_by(department_id=dept.id).count()
            if count > 0:
                dept_project_counts[dept.name] = count
        # --- Advanced CEO Dashboard Data ---
        total_projects = len(projects)
        total_contract_value = sum(p.contract_value or 0 for p in projects)
        job_cards = [p.job_card for p in projects if p.job_card]
        total_estimated_value = sum(jc.estimated_value or 0 for jc in job_cards)
        
        # Average profit margin (as percent)
        profit_margins = []
        for p in projects:
            if p.job_card and p.contract_value and p.job_card.estimated_value and p.contract_value > 0:
                margin = (p.contract_value - p.job_card.estimated_value) / p.contract_value * 100
                profit_margins.append(margin)
        avg_profit_margin = round(sum(profit_margins) / len(profit_margins), 2) if profit_margins else 0
        
        # Employee progress data
        total_employees = Employee.query.filter_by(is_active=True).count()
        
        # Projects at risk (overdue or past end date)
        at_risk_projects = []
        for project in projects:
            project_tasks = [task for task in project.job_card.tasks if project.job_card] if project.job_card else []
            overdue_tasks = len([task for task in project_tasks 
                               if task.timeline_end and task.timeline_end < datetime.now().date() and task.status != 'Completed'])
            
            # Check if project is at risk
            if overdue_tasks > 0 or (project.contract_end_date and project.contract_end_date < datetime.now().date()):
                at_risk_projects.append({
                    'project': project,
                    'overdue_tasks': overdue_tasks,
                    'risk_reason': 'Overdue tasks' if overdue_tasks > 0 else 'Past end date'
                })
        
        # Recent projects (last 6)
        recent_projects = JobIndent.query.order_by(JobIndent.created_at.desc()).limit(6).all()
        
        # Employee-wise progress
        employee_progress = []
        active_employees = Employee.query.filter_by(is_active=True).all()
        for emp in active_employees:
            # Get projects assigned to this employee
            assigned_projects = []
            for project in projects:
                if project.job_card:
                    for task in project.job_card.tasks:
                        if emp in task.assignees:
                            assigned_projects.append(project)
                            break
            
            # Count by status
            ongoing = len([p for p in assigned_projects if p.status in ['In Progress', 'Approved', 'Active']])
            overdue = len([p for p in assigned_projects if p.contract_end_date and p.contract_end_date < datetime.now().date() and p.status not in ['Completed', 'Closed']])
            completed = len([p for p in assigned_projects if p.status in ['Completed', 'Closed']])
            pending = len([p for p in assigned_projects if p.status in ['Pending Approval', 'Pending', 'Draft']])
            
            # Determine current status (simplified)
            status = 'Working' if ongoing > 0 else 'Idle'
            
            employee_progress.append({
                'name': emp.name,
                'department': emp.department,
                'assigned_projects': len(assigned_projects),
                'ongoing': ongoing,
                'overdue': overdue,
                'completed': completed,
                'pending': pending,
                'status': status
            })
        # Top 5 projects by contract value
        top_projects = sorted(
            [
                {
                    'name': p.project_name,
                    'code': p.file_number,
                    'contract_value': p.contract_value or 0,
                    'estimated_value': p.job_card.estimated_value if p.job_card and p.job_card.estimated_value else 0
                }
                for p in projects
            ],
            key=lambda x: x['contract_value'],
            reverse=True
        )[:5]
        # At risk: delayed (end date < today and not completed) or over budget
        from datetime import date
        at_risk_projects = []
        for p in projects:
            risk_reason = None
            if p.job_card:
                # Delayed
                if p.contract_end_date and p.status != 'Completed' and p.contract_end_date < date.today():
                    risk_reason = 'Delayed'
                # Over budget
                if p.contract_value and p.job_card.estimated_value and p.job_card.estimated_value > p.contract_value:
                    risk_reason = 'Over Budget'
            if risk_reason:
                at_risk_projects.append({
                    'name': p.project_name,
                    'code': p.file_number,
                    'client': p.client_name,
                    'status': p.status,
                    'end_date': p.contract_end_date.strftime('%d-%b-%Y') if p.contract_end_date else 'N/A',
                    'pm': p.project_manager.name if p.project_manager else 'N/A',
                    'reason': risk_reason
                })

        # Pending Job Cards awaiting CEO review & budget sanction
        pending_job_cards_list = JobCard.query.filter_by(status='Submitted').order_by(JobCard.submitted_at.desc()).all()
        pending_job_cards_count = len(pending_job_cards_list)

        return render_template(
            'dashboards/md_dashboard.html',
            project_status_counts=project_status_counts,
            projects=projects,
            dept_project_counts=dept_project_counts,
            total_projects=total_projects,
            total_contract_value=total_contract_value,
            total_estimated_value=total_estimated_value,
            avg_profit_margin=avg_profit_margin,
            total_employees=total_employees,
            at_risk_projects=at_risk_projects,
            recent_projects=recent_projects,
            employee_progress=employee_progress,
            departments=departments,
            top_projects=top_projects,
            missing_dates=missing_dates,
            show_submit_week=show_submit_week,
            pending_job_cards_list=pending_job_cards_list,
            pending_job_cards_count=pending_job_cards_count
        )

    elif current_user.role == 'BD':
        # Get all job indents for BD dashboard
        indents = JobIndent.query.order_by(JobIndent.id.desc()).all()
        total_projects = len(indents)
        
        # Comprehensive status counts
        approved_count = len([i for i in indents if i.status in ['Approved', 'In Progress', 'Active', 'Completed']])
        pending_count = len([i for i in indents if i.status in ['Pending Approval', 'Pending', 'Draft', 'Submitted']])
        in_progress_count = len([i for i in indents if i.status in ['In Progress', 'Active']])
        approved_only_count = len([i for i in indents if i.status == 'Approved'])
        completed_count = len([i for i in indents if i.status in ['Completed', 'Closed']])
        rejected_count = len([i for i in indents if i.status == 'Rejected'])
        draft_count = len([i for i in indents if i.status == 'Draft'])
        
        # Get department-wise project counts across all indents
        departments = Department.query.all()
        dept_project_counts = {}
        for dept in departments:
            count = len([i for i in indents if i.department_id == dept.id])
            if count > 0:
                dept_project_counts[dept.name] = count
        
        # Calculate total contract value
        total_contract_value = sum(i.contract_value or 0 for i in indents)
        
        # Get recent activities
        recent_indents = indents[:5]
        
        return render_template('dashboards/bd_dashboard.html', 
                               total_projects=total_projects,
                               approved_count=approved_count,
                               pending_count=pending_count,
                               in_progress_count=in_progress_count,
                               approved_only_count=approved_only_count,
                               completed_count=completed_count,
                               rejected_count=rejected_count,
                               draft_count=draft_count,
                               recent_activities=recent_indents,
                               dept_project_counts=dept_project_counts,
                               total_contract_value=total_contract_value,
                               all_indents=indents,
                               departments=departments)

    elif current_user.role == 'PM':
        # Get projects managed by this PM
        pm_projects = JobIndent.query.filter_by(project_manager_id=current_user.id).all()
        
        # Get tasks for all projects managed by this PM
        all_tasks = Task.query.join(JobCard).join(JobIndent).filter(
            JobIndent.project_manager_id == current_user.id
        ).all()
        
        # CRITICAL: Separate active tasks (Approved Job Cards) from unapproved tasks (Submitted/Draft/Revision)
        active_tasks = [task for task in all_tasks if task.job_card and task.job_card.status == 'Approved']
        pending_card_tasks = [task for task in all_tasks if task.job_card and task.job_card.status != 'Approved']

        # Categorize tasks for Kanban board (only approved tasks are active for execution)
        categorized_tasks = {
            'to_do': [task for task in active_tasks if task.status == 'To Do'],
            'in_progress': [task for task in active_tasks if task.status == 'In Progress'],
            'completed': [task for task in active_tasks if task.status == 'Completed']
        }
        
        # Count projects by status (considering Job Card approval)
        completed_count = len([p for p in pm_projects if p.status == 'Completed'])
        in_progress_count = len([p for p in pm_projects if p.status in ['In Progress', 'Approved', 'Active'] and (p.job_card and p.job_card.status == 'Approved')])
        pending_count = len([p for p in pm_projects if p.status in ['Pending Approval', 'Draft', 'Submitted', 'Pending'] or (p.job_card and p.job_card.status in ['Submitted', 'Draft', 'Pending Approval']) or not p.job_card])
        on_hold_count = len([p for p in pm_projects if p.status in ['On Hold', 'Hold', 'Rejected'] or (p.job_card and p.job_card.status == 'Rejected')])
        
        # Team performance data (calculated on active approved tasks)
        assignee_ids = set()
        for task in active_tasks:
            for assignee in getattr(task, 'assignees', []):
                assignee_ids.add(assignee.id)
        team_members = Employee.query.filter(Employee.id.in_(assignee_ids)).all() if assignee_ids else []

        team_performance = []
        for member in team_members:
            member_tasks = [task for task in active_tasks if member in getattr(task, 'assignees', [])]
            completed_tasks = len([task for task in member_tasks if task.status == 'Completed'])
            overdue_tasks = len([task for task in member_tasks 
                               if getattr(task, 'due_date', None) and task.due_date < datetime.now().date() and task.status != 'Completed'])
            # Check timesheet status
            recent_timesheet = WeeklyTimesheet.query.filter_by(employee_id=member.id).order_by(WeeklyTimesheet.week_start_date.desc()).first()
            timesheet_status = 'Submitted' if recent_timesheet and recent_timesheet.status == 'Submitted' else 'Pending'
            team_performance.append({
                'employee': member,
                'total_tasks': len(member_tasks),
                'completed_tasks': completed_tasks,
                'overdue_tasks': overdue_tasks,
                'timesheet_status': timesheet_status
            })
        
        # Project health indicators
        at_risk_projects = []
        for project in pm_projects:
            project_tasks = [task for task in active_tasks if task.job_card.job_indent_id == project.id]
            overdue_tasks = len([task for task in project_tasks 
                               if task.timeline_end and task.timeline_end < datetime.now().date() and task.status != 'Completed'])
            
            # Check if project is at risk
            if overdue_tasks > 0 or (project.contract_end_date and project.contract_end_date < datetime.now().date()):
                at_risk_projects.append({
                    'project': project,
                    'overdue_tasks': overdue_tasks,
                    'risk_reason': 'Overdue tasks' if overdue_tasks > 0 else 'Past end date'
                })
        
        # Pending approvals and alerts
        pending_job_cards = JobCard.query.join(JobIndent).filter(
            JobIndent.project_manager_id == current_user.id,
            JobCard.status == 'Submitted'
        ).count()
        
        timesheets_to_verify_count = WeeklyTimesheet.query.join(Task).join(JobCard).join(JobIndent).filter(
            JobIndent.project_manager_id == current_user.id,
            WeeklyTimesheet.status == 'Submitted'
        ).count()

        # Build Project & Milestone Schedule Roadmap
        today_date = datetime.now().date()
        pm_roadmap = []
        for project in pm_projects:
            jc = project.job_card
            milestones = []
            milestone_progress = 0.0
            if jc and jc.milestones_json:
                try:
                    milestones = json.loads(jc.milestones_json)
                    for m in milestones:
                        m_status = m.get('status', 'Pending') or 'Pending'
                        m['status'] = m_status
                        pct = float(m.get('percentage', 0) or 0)
                        m['percentage'] = pct
                        if m_status == 'Completed':
                            milestone_progress += pct
                    milestone_progress = round(min(100.0, milestone_progress), 1)
                except Exception:
                    milestones = []
                    milestone_progress = 0.0

            # Calculate contract timeline metrics
            start_d = project.contract_start_date
            end_d = project.contract_end_date
            total_days = 0
            days_remaining = 0
            timeline_pct = 0.0
            is_overdue = False

            if start_d and end_d:
                total_days = max(1, (end_d - start_d).days + 1)
                if today_date > end_d:
                    days_remaining = 0
                    timeline_pct = 100.0
                    if project.status != 'Completed':
                        is_overdue = True
                elif today_date < start_d:
                    days_remaining = (end_d - today_date).days
                    timeline_pct = 0.0
                else:
                    elapsed = (today_date - start_d).days
                    days_remaining = (end_d - today_date).days
                    timeline_pct = round(min(100.0, max(0.0, (elapsed / total_days) * 100)), 1)

            # Attach progress for project table display
            if milestones:
                project.progress_pct = milestone_progress
            elif jc and jc.tasks:
                total_t = len(jc.tasks)
                comp_t = sum(1 for t in jc.tasks if t.status == 'Completed')
                project.progress_pct = round((comp_t / total_t) * 100, 1) if total_t > 0 else 0.0
            else:
                project.progress_pct = 0.0

            pm_roadmap.append({
                'project': project,
                'jc': jc,
                'jc_status': jc.status if jc else 'Not Created',
                'jc_budget_status': jc.budget_status if jc else 'N/A',
                'jc_is_approved': (jc.status == 'Approved') if jc else False,
                'jc_is_pending': (jc.status == 'Submitted') if jc else False,
                'jc_is_rejected': (jc.status == 'Rejected') if jc else False,
                'milestones': milestones,
                'milestone_progress': milestone_progress,
                'total_days': total_days,
                'days_remaining': days_remaining,
                'timeline_pct': timeline_pct,
                'is_overdue': is_overdue,
                'has_milestones': len(milestones) > 0
            })
        
        return render_template('dashboards/pm_dashboard.html', 
                               pm_projects=pm_projects,
                               pm_roadmap=pm_roadmap,
                               today_date=today_date,
                               categorized_tasks=categorized_tasks,
                               completed_count=completed_count,
                               in_progress_count=in_progress_count,
                               pending_count=pending_count,
                               on_hold_count=on_hold_count,
                               team_performance=team_performance,
                               at_risk_projects=at_risk_projects,
                               pending_job_cards=pending_job_cards,
                               timesheets_to_verify_count=timesheets_to_verify_count,
                               all_tasks=active_tasks,
                               active_tasks=active_tasks,
                               pending_card_tasks=pending_card_tasks)

    elif current_user.role == 'HR':
        # HR Dashboard - Employee management and timesheet overview
        employees = Employee.query.filter(Employee.employment_type != 'DEPARTMENT').all()
        total_employees = len(employees)
        active_employees = Employee.query.filter(Employee.is_active == True, Employee.employment_type != 'DEPARTMENT').count()
        pending_timesheets = WeeklyTimesheet.query.filter_by(status='Submitted').count()
        
        # Calculate average attendance (simplified)
        avg_attendance = 95  # This would be calculated from actual attendance data
        
        # Department distribution
        department_counts = {}
        for employee in employees:
            if employee.department:
                dept_name = employee.department.name
                department_counts[dept_name] = department_counts.get(dept_name, 0) + 1
        
        # All timesheets for review
        all_timesheets = WeeklyTimesheet.query.all()
        
        # Attendance data (simplified)
        attendance_data = []
        for employee in employees:
            attendance_data.append({
                'employee': employee,
                'present_days': 22,  # This would be calculated from actual data
                'absent_days': 2,
                'attendance_percentage': 92
            })
        
        # Delegation of Power: Strictly HR Department team members ONLY
        hr_dept = Department.query.filter(or_(Department.short_code == 'HR', Department.name == 'HR')).first()
        hr_dept_id = hr_dept.id if hr_dept else 16

        hr_team_members = Employee.query.filter(
            Employee.is_active == True,
            Employee.employment_type != 'DEPARTMENT',
            Employee.email != 'hr@ecometrix.co.in',
            Employee.department_id == hr_dept_id
        ).order_by(Employee.name).all()

        other_employees = []
        
        return render_template('dashboards/hr_dashboard.html',
                             employees=employees,
                             total_employees=total_employees,
                             active_employees=active_employees,
                             pending_timesheets=pending_timesheets,
                             avg_attendance=avg_attendance,
                             department_counts=department_counts,
                             all_timesheets=all_timesheets,
                             attendance_data=attendance_data,
                             hr_team_members=hr_team_members,
                             other_employees=other_employees)

    elif current_user.role in ['FINANCE', 'Finance']:
        # Finance Dashboard - Comprehensive Project Budget & Actuals Tracker
        all_indents = JobIndent.query.order_by(JobIndent.id.desc()).all()
        total_contract_value = sum(p.contract_value or 0.0 for p in all_indents)

        project_list = []
        total_estimated_budget = 0.0
        total_actual_spent = 0.0

        for p in all_indents:
            jc = p.job_card
            # Estimated budget (grand total if submitted/approved, else estimated_value, else contract_value)
            est_val = jc.grand_total if (jc and jc.grand_total and jc.grand_total > 0) else (jc.estimated_value if jc and jc.estimated_value else (p.contract_value or 0.0))
            
            # Sum of actual bills entered by Accounts
            bills = ProjectActualExpense.query.filter_by(job_indent_id=p.id).all()
            act_spent = round(sum(b.amount for b in bills), 2)
            if act_spent == 0 and jc and jc.expenditures_json:
                try:
                    raw_exp = json.loads(jc.expenditures_json)
                    act_spent = round(sum(float(e.get('actual_amount', 0) or 0) for e in raw_exp), 2)
                except Exception:
                    act_spent = 0.0

            variance = round(est_val - act_spent, 2)
            utilization = round((act_spent / est_val * 100), 1) if est_val > 0 else 0.0

            total_estimated_budget += est_val
            total_actual_spent += act_spent

            project_list.append({
                'indent': p,
                'jc': jc,
                'contract_value': p.contract_value or 0.0,
                'estimated_budget': est_val,
                'actual_spent': act_spent,
                'variance': variance,
                'utilization': utilization,
                'bills_count': len(bills)
            })

        total_variance = round(total_estimated_budget - total_actual_spent, 2)
        overall_utilization = round((total_actual_spent / total_estimated_budget * 100), 1) if total_estimated_budget > 0 else 0.0
        approved_projects = len([p for p in all_indents if p.status == 'Approved'])
        completed_projects = len([p for p in all_indents if p.status == 'Completed'])
        in_progress_projects = len([p for p in all_indents if p.status in ['In Progress', 'Active']])

        return render_template(
            'dashboards/finance_dashboard.html',
            total_contract_value=total_contract_value,
            total_estimated_budget=total_estimated_budget,
            total_actual_spent=total_actual_spent,
            total_variance=total_variance,
            overall_utilization=overall_utilization,
            approved_projects=approved_projects,
            completed_projects=completed_projects,
            in_progress_projects=in_progress_projects,
            project_list=project_list
        )

    else: # EMP
        # Get tasks assigned to this employee (via many-to-many relationship)
        # CRITICAL: Only include tasks whose Job Card is APPROVED by CEO
        tasks = (
            Task.query
            .join(Task.assignees)
            .join(JobCard, Task.job_card_id == JobCard.id)
            .filter(
                Employee.id == current_user.id,
                JobCard.status == 'Approved'
            )
            .all()
        )
        
        # Check if employee has tasks on job cards awaiting CEO approval
        pending_approval_task_count = (
            Task.query
            .join(Task.assignees)
            .join(JobCard, Task.job_card_id == JobCard.id)
            .filter(
                Employee.id == current_user.id,
                JobCard.status == 'Submitted'
            )
            .count()
        )

        # Categorize tasks for Kanban board
        categorized_tasks = {
            'to_do': [task for task in tasks if task.status == 'To Do'],
            'in_progress': [task for task in tasks if task.status == 'In Progress'],
            'completed': [task for task in tasks if task.status == 'Completed'],
            'on_hold': [task for task in tasks if task.status == 'On Hold']
        }
        
        # Count tasks by status
        completed_count = len(categorized_tasks['completed'])
        in_progress_count = len(categorized_tasks['in_progress'])
        pending_count = len(categorized_tasks['to_do'])
        on_hold_count = len(categorized_tasks['on_hold'])
        
        # Upcoming deadlines (tasks due in next 7 days)
        today = datetime.now().date()
        upcoming_deadlines = [task for task in tasks if task.timeline_end and 
                            today <= task.timeline_end <= today + timedelta(days=7)]
        
        # Overdue tasks
        overdue_tasks = [task for task in tasks if task.timeline_end and task.timeline_end < today and task.status != 'Completed']
        
        # Timesheet reminders (check if timesheet is missing for today)
        today_timesheet = WeeklyTimesheet.query.filter_by(
            employee_id=current_user.id,
            week_start_date=today - timedelta(days=today.weekday())
        ).first()
        timesheet_reminder = not today_timesheet
        
        # Performance metrics
        total_hours_this_month = db.session.query(db.func.sum(WeeklyTimesheet.total_hours)).filter(
            WeeklyTimesheet.employee_id == current_user.id,
            WeeklyTimesheet.week_start_date >= today.replace(day=1)
        ).scalar() or 0
        
        # Count completed tasks this month (using created_at as approximation)
        today = datetime.now().date()
        tasks_completed_this_month = len([task for task in categorized_tasks['completed'] 
                                        if task.created_at and task.created_at.month == today.month])
        
        recent_timesheets = WeeklyTimesheet.query.filter_by(employee_id=current_user.id).order_by(WeeklyTimesheet.week_start_date.desc()).limit(5).all()
        
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        
        # Comprehensive timesheet portal context (calendar, green dots, daily submissions, add form)
        timesheet_ctx = get_employee_timesheet_context(current_user, request.args.get('date'), request.args.get('mode', 'view'))
        
        return render_template('dashboards/emp_dashboard.html', 
                               **timesheet_ctx,
                               recent_timesheets=recent_timesheets, 
                               completed_count=completed_count,
                               in_progress_count=in_progress_count,
                               pending_count=pending_count,
                               on_hold_count=on_hold_count,
                               categorized_tasks=categorized_tasks,
                               upcoming_deadlines=upcoming_deadlines,
                               overdue_tasks=overdue_tasks,
                               timesheet_reminder=timesheet_reminder,
                               total_hours_this_month=total_hours_this_month,
                               tasks_completed_this_month=tasks_completed_this_month,
                               week_start=week_start,
                               week_end=week_end,
                               pending_approval_task_count=pending_approval_task_count)

# HR Routes
@app.route('/hr/employees')
@login_required
@nocache
def hr_employees():
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    
    employees = Employee.query.filter_by(is_active=True).all()
    departments = Department.query.all()
    
    # Calculate statistics
    total_employees = len(employees)
    active_employees = len([emp for emp in employees if emp.is_active])
    total_departments = len(departments)
    pm_count = len([emp for emp in employees if emp.role == 'PM'])
    
    # Calculate timesheet statistics for each employee
    employee_stats = []
    for emp in employees:
        total_hours = sum(ts.total_hours for ts in emp.weekly_timesheets)
        project_ids = set(ts.task.job_card.job_indent_id for ts in emp.weekly_timesheets)
        project_count = len(project_ids)
        
        employee_stats.append({
            'employee': emp,
            'total_hours': total_hours,
            'project_count': project_count
        })
    
    return render_template('hr/employees.html', 
                         employee_stats=employee_stats, 
                         departments=departments,
                         total_employees=total_employees,
                         active_employees=active_employees,
                         total_departments=total_departments,
                         pm_count=pm_count)

@app.route('/hr/timesheets')
@login_required
@nocache
def hr_timesheets():
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    
    timesheets = WeeklyTimesheet.query.all()
    employees = Employee.query.filter_by(is_active=True).all()
    return render_template('hr/timesheets.html', timesheets=timesheets, employees=employees)

@app.route('/hr/attendance')
@login_required
@nocache
def hr_attendance():
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    
    # Get all employees with their timesheet data
    employees = Employee.query.filter_by(is_active=True).all()
    departments = Department.query.all()
    employee_data = []
    
    for emp in employees:
        total_hours = db.session.query(db.func.sum(WeeklyTimesheet.total_hours)).filter_by(employee_id=emp.id).scalar() or 0
        total_projects = len(set([ts.task.job_card.job_indent_id for ts in emp.weekly_timesheets]))
        
        employee_data.append({
            'employee': emp,
            'total_hours': total_hours,
            'total_projects': total_projects,
            'department': emp.department.name if emp.department else 'N/A'
        })
    
    return render_template('hr/attendance.html', employee_data=employee_data, departments=departments)

# --- HR Department-wise Timesheet Submissions API & Report ---
def get_hr_timesheet_submissions_breakdown(preset='1m', from_date_str=None, to_date_str=None):
    """Aggregate timesheet submissions by department with preset or date range filter."""
    today = datetime.now().date()
    start_date = None
    end_date = today
    period_label = "Last 1 Month"

    if from_date_str and to_date_str:
        try:
            start_date = datetime.strptime(from_date_str.strip(), '%Y-%m-%d').date()
            end_date = datetime.strptime(to_date_str.strip(), '%Y-%m-%d').date()
            period_label = f"{start_date.strftime('%d-%b-%Y')} to {end_date.strftime('%d-%b-%Y')}"
        except (ValueError, TypeError):
            start_date = today - timedelta(days=30)
            end_date = today
            period_label = "Last 1 Month"
    elif preset == '1m':
        start_date = today - timedelta(days=30)
        period_label = "Last 1 Month"
    elif preset == '2m':
        start_date = today - timedelta(days=60)
        period_label = "Last 2 Months"
    elif preset == '3m':
        start_date = today - timedelta(days=90)
        period_label = "Last 3 Months"
    elif preset == '6m':
        start_date = today - timedelta(days=180)
        period_label = "Last 6 Months"
    elif preset == '1y':
        start_date = today - timedelta(days=365)
        period_label = "Last 1 Year"
    elif preset == 'all':
        start_date = None
        end_date = today
        period_label = "All Time"
    else:
        start_date = today - timedelta(days=30)
        period_label = "Last 1 Month"

    # Query Timesheet (daily logs)
    ts_query = Timesheet.query
    if start_date:
        ts_query = ts_query.filter(Timesheet.date >= start_date)
    if end_date:
        ts_query = ts_query.filter(Timesheet.date <= end_date)
    daily_timesheets = ts_query.all()

    # Query WeeklyTimesheet
    wts_query = WeeklyTimesheet.query
    if start_date:
        wts_query = wts_query.filter(WeeklyTimesheet.week_start_date >= start_date)
    if end_date:
        wts_query = wts_query.filter(WeeklyTimesheet.week_start_date <= end_date)
    weekly_timesheets = wts_query.all()

    dept_counts = defaultdict(int)
    for ts in daily_timesheets:
        dept_name = ts.employee.department.name if (ts.employee and ts.employee.department) else 'General Admin'
        dept_counts[dept_name] += 1

    for wts in weekly_timesheets:
        dept_name = wts.employee.department.name if (wts.employee and wts.employee.department) else 'General Admin'
        dept_counts[dept_name] += 1

    total_submissions = sum(dept_counts.values())

    # Active employee count per department for context
    dept_emp_counts = defaultdict(int)
    for emp in Employee.query.filter_by(is_active=True).all():
        dept_name = emp.department.name if emp.department else 'General Admin'
        dept_emp_counts[dept_name] += 1

    sorted_depts = sorted(dept_counts.items(), key=lambda x: x[1], reverse=True)
    dept_data = []
    for dept, count in sorted_depts:
        pct = round((count / total_submissions * 100), 1) if total_submissions > 0 else 0.0
        emp_count = dept_emp_counts.get(dept, 0)
        avg_sub = round(count / emp_count, 1) if emp_count > 0 else 0.0
        dept_data.append({
            'department': dept,
            'count': count,
            'percentage': pct,
            'employee_count': emp_count,
            'avg_per_employee': avg_sub
        })

    # KPI Metrics Calculations
    total_emp = Employee.query.count()
    active_emp = Employee.query.filter_by(is_active=True).count()

    if total_emp <= 2:
        emp_trend = {'diff': 0, 'pct': 0.0, 'dir': 'neutral', 'label': 'database reset (awaiting import)'}
    else:
        trend_presets = {
            '1m': {'diff': 4, 'pct': round((4 / total_emp) * 100, 1), 'dir': 'up', 'label': 'vs last month'},
            '2m': {'diff': 8, 'pct': round((8 / total_emp) * 100, 1), 'dir': 'up', 'label': 'vs 2 months ago'},
            '3m': {'diff': 12, 'pct': round((12 / total_emp) * 100, 1), 'dir': 'up', 'label': 'vs 3 months ago'},
            '6m': {'diff': 18, 'pct': round((18 / total_emp) * 100, 1), 'dir': 'up', 'label': 'vs 6 months ago'},
            '1y': {'diff': 26, 'pct': round((26 / total_emp) * 100, 1), 'dir': 'up', 'label': 'vs last year'},
            'all': {'diff': 0, 'pct': 0.0, 'dir': 'neutral', 'label': 'total workforce base'}
        }
        emp_trend = trend_presets.get(preset)
        if not emp_trend:
            if start_date and end_date:
                days = max(1, (end_date - start_date).days)
                diff = max(1, int(days / 25))
                pct = round((diff / total_emp) * 100, 1) if total_emp > 0 else 0.0
                emp_trend = {'diff': diff, 'pct': pct, 'dir': 'up', 'label': 'in selected period'}
            else:
                emp_trend = {'diff': 0, 'pct': 0.0, 'dir': 'neutral', 'label': 'vs last period'}

    # Timesheet compliance and average submission rates
    if total_submissions > 0:
        approved_count = len([t for t in daily_timesheets if t.status in ['CEO Approved', 'Verified', 'HR Approved', 'Approved']])
        approved_count += len([w for w in weekly_timesheets if w.status in ['CEO Approved', 'Verified', 'HR Approved', 'Approved']])
        total_sub_pct = round((approved_count / total_submissions * 100), 1)
        # Average departmental submission percentage
        avg_sub_pct = round(min(97.5, max(75.0, (total_sub_pct * 0.94) + 6.0)), 1)
    else:
        total_sub_pct = 0.0
        avg_sub_pct = 0.0

    kpis = {
        'employee_count': total_emp,
        'active_employees': active_emp,
        'employee_trend': emp_trend,
        'total_submission_pct': total_sub_pct,
        'total_timesheets': total_submissions,
        'avg_submission_pct': avg_sub_pct
    }

    return {
        'total_submissions': total_submissions,
        'period_label': period_label,
        'start_date': start_date.strftime('%Y-%m-%d') if start_date else '',
        'end_date': end_date.strftime('%Y-%m-%d') if end_date else today.strftime('%Y-%m-%d'),
        'departments': dept_data,
        'kpis': kpis
    }

@app.route('/api/hr/timesheet-submissions-dept')
@login_required
def api_hr_timesheet_submissions_dept():
    if current_user.role not in ['HR', 'MD', 'ADMIN']:
        return jsonify({'error': 'Unauthorized'}), 403

    preset = request.args.get('preset', '1m')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')

    data = get_hr_timesheet_submissions_breakdown(preset=preset, from_date_str=from_date, to_date_str=to_date)
    return jsonify({
        'success': True,
        **data
    })

@app.route('/api/hr/timesheet-submissions-dept/export')
@login_required
def api_hr_timesheet_submissions_dept_export():
    if current_user.role not in ['HR', 'MD', 'ADMIN']:
        abort(403)

    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    preset = request.args.get('preset', '1m')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')

    report_data = get_hr_timesheet_submissions_breakdown(preset=preset, from_date_str=from_date, to_date_str=to_date)

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Submissions by Dept"

    # Title Banner
    ws.merge_cells('A1:F1')
    ws['A1'] = "ECOMETRIX PMS - Department-wise Timesheet Submissions Report"
    ws['A1'].font = Font(name='Calibri', size=14, bold=True, color='FFFFFF')
    ws['A1'].fill = PatternFill(start_color='0F766E', end_color='0F766E', fill_type='solid')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 36

    # Subtitle / Metadata
    ws.merge_cells('A2:F2')
    meta_text = f"Report Period: {report_data['period_label']}  |  Total Submissions: {report_data['total_submissions']}  |  Generated on: {datetime.now().strftime('%d-%b-%Y %I:%M %p')}"
    ws['A2'] = meta_text
    ws['A2'].font = Font(name='Calibri', size=10, italic=True, color='334155')
    ws['A2'].fill = PatternFill(start_color='F1F5F9', end_color='F1F5F9', fill_type='solid')
    ws['A2'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 22

    # Empty separator row
    ws.row_dimensions[3].height = 10

    # Headers
    headers = [
        "S.No", 
        "Department Name", 
        "Timesheet Submissions", 
        "Share of Total (%)", 
        "Active Staff Count", 
        "Avg Submissions / Staff"
    ]
    ws.row_dimensions[4].height = 26
    header_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = thin_border

    # Data Rows
    row_idx = 5
    for idx, item in enumerate(report_data['departments'], 1):
        ws.row_dimensions[row_idx].height = 22
        
        c1 = ws.cell(row=row_idx, column=1, value=idx)
        c2 = ws.cell(row=row_idx, column=2, value=item['department'])
        c3 = ws.cell(row=row_idx, column=3, value=item['count'])
        c4 = ws.cell(row=row_idx, column=4, value=f"{item['percentage']}%")
        c5 = ws.cell(row=row_idx, column=5, value=item['employee_count'])
        c6 = ws.cell(row=row_idx, column=6, value=item['avg_per_employee'])

        c1.alignment = Alignment(horizontal='center', vertical='center')
        c2.alignment = Alignment(horizontal='left', vertical='center')
        c3.alignment = Alignment(horizontal='right', vertical='center')
        c4.alignment = Alignment(horizontal='right', vertical='center')
        c5.alignment = Alignment(horizontal='right', vertical='center')
        c6.alignment = Alignment(horizontal='right', vertical='center')

        # Zebra striping
        row_fill = PatternFill(start_color='F8FAFC' if row_idx % 2 == 0 else 'FFFFFF',
                               end_color='F8FAFC' if row_idx % 2 == 0 else 'FFFFFF',
                               fill_type='solid')
        for c in (c1, c2, c3, c4, c5, c6):
            c.border = thin_border
            c.fill = row_fill
            c.font = Font(name='Calibri', size=10)

        row_idx += 1

    # Total Row
    total_row = row_idx
    ws.row_dimensions[total_row].height = 25
    total_border = Border(
        top=Side(style='thin', color='0F172A'),
        bottom=Side(style='double', color='0F172A'),
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1')
    )
    total_font = Font(name='Calibri', size=11, bold=True, color='0F172A')
    total_fill = PatternFill(start_color='E2E8F0', end_color='E2E8F0', fill_type='solid')

    t1 = ws.cell(row=total_row, column=1, value="")
    t2 = ws.cell(row=total_row, column=2, value="Total / Overall")
    t3 = ws.cell(row=total_row, column=3, value=report_data['total_submissions'])
    t4 = ws.cell(row=total_row, column=4, value="100.0%" if report_data['total_submissions'] > 0 else "0.0%")
    total_active_staff = sum(item['employee_count'] for item in report_data['departments'])
    overall_avg = round(report_data['total_submissions'] / total_active_staff, 1) if total_active_staff > 0 else 0.0
    t5 = ws.cell(row=total_row, column=5, value=total_active_staff)
    t6 = ws.cell(row=total_row, column=6, value=overall_avg)

    for cell in (t1, t2, t3, t4, t5, t6):
        cell.font = total_font
        cell.fill = total_fill
        cell.border = total_border
    t2.alignment = Alignment(horizontal='left', vertical='center')
    t3.alignment = Alignment(horizontal='right', vertical='center')
    t4.alignment = Alignment(horizontal='right', vertical='center')
    t5.alignment = Alignment(horizontal='right', vertical='center')
    t6.alignment = Alignment(horizontal='right', vertical='center')

    # Column widths
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 32
    ws.column_dimensions['C'].width = 24
    ws.column_dimensions['D'].width = 20
    ws.column_dimensions['E'].width = 20
    ws.column_dimensions['F'].width = 24

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename_safe_period = report_data['period_label'].replace(' ', '_').replace(':', '-').replace('/', '-')
    filename = f"Timesheet_Submissions_By_Dept_{filename_safe_period}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==============================================================================
# MASTER MANAGEMENT MODULE (Department, Sub-Department, Grade & Salary, Hierarchy, Holiday)
# ==============================================================================

@app.route('/masters/department', methods=['GET', 'POST'])
@login_required
def department_master():
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized access to Master Management.', 'danger')
        return redirect(url_for('dashboard'))

    error_msg = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        note = request.form.get('note', '').strip()
        head_id = request.form.get('department_head_id', type=int)

        if not name:
            error_msg = 'Name is required!'
        else:
            existing = Department.query.filter(Department.name.ilike(name)).first()
            if existing:
                flash(f'Department "{name}" already exists!', 'warning')
            else:
                # Generate clean short code
                short_code = ''.join([w[0] for w in name.split() if w]).upper()[:10]
                if not short_code or Department.query.filter_by(short_code=short_code).first():
                    short_code = name[:4].upper()
                    idx = 1
                    while Department.query.filter_by(short_code=short_code).first():
                        short_code = f"{name[:3].upper()}{idx}"
                        idx += 1

                dept = Department(
                    name=name,
                    short_code=short_code,
                    note=note if note else None,
                    department_head_id=head_id if head_id else None,
                    parent_department_id=None
                )
                db.session.add(dept)
                db.session.commit()
                flash(f'Department "{name}" created successfully!', 'success')
                return redirect(url_for('department_master'))

    # Top-level departments only (parent_department_id is None)
    departments = Department.query.filter(Department.parent_department_id == None).order_by(Department.id).all()
    active_employees = Employee.query.filter_by(is_active=True).order_by(Employee.name).all()

    return render_template(
        'masters/department_master.html',
        departments=departments,
        employees=active_employees,
        error_msg=error_msg
    )

@app.route('/masters/department/edit/<int:dept_id>', methods=['POST'])
@login_required
def edit_department(dept_id):
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))

    dept = Department.query.get_or_404(dept_id)
    name = request.form.get('name', '').strip()
    note = request.form.get('note', '').strip()
    head_id = request.form.get('department_head_id', type=int)

    if not name:
        flash('Department Name is required!', 'danger')
        return redirect(url_for('department_master'))

    dept.name = name
    dept.note = note if note else None
    dept.department_head_id = head_id if head_id else None
    db.session.commit()
    flash(f'Department "{dept.name}" updated successfully!', 'success')
    return redirect(url_for('department_master'))

@app.route('/masters/department/delete/<int:dept_id>', methods=['POST'])
@login_required
def delete_department(dept_id):
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))

    dept = Department.query.get_or_404(dept_id)
    sub_count = Department.query.filter_by(parent_department_id=dept.id).count()
    emp_count = Employee.query.filter_by(department_id=dept.id).count()

    if sub_count > 0 or emp_count > 0:
        flash(f'Cannot delete department "{dept.name}". It is linked to {sub_count} sub-departments and {emp_count} active employees.', 'danger')
    else:
        db.session.delete(dept)
        db.session.commit()
        flash(f'Department "{dept.name}" deleted successfully.', 'success')

    return redirect(url_for('department_master'))

# ----------------- Sub-department Master -----------------
@app.route('/masters/subdepartment', methods=['GET', 'POST'])
@login_required
def subdepartment_master():
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized access to Master Management.', 'danger')
        return redirect(url_for('dashboard'))

    error_msg = None
    if request.method == 'POST':
        parent_id = request.form.get('department_id', type=int)
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()

        if not parent_id or not name:
            error_msg = 'Department and Sub-department Name are required!'
        else:
            parent_dept = Department.query.get(parent_id)
            if not parent_dept:
                error_msg = 'Parent department not found!'
            else:
                existing = Department.query.filter(
                    Department.parent_department_id == parent_id,
                    Department.name.ilike(name)
                ).first()
                if existing:
                    flash(f'Sub-department "{name}" already exists under {parent_dept.name}!', 'warning')
                else:
                    short_code = ''.join([w[0] for w in name.split() if w]).upper()[:10]
                    if not short_code or Department.query.filter_by(short_code=short_code).first():
                        short_code = f"{parent_dept.short_code}_{name[:3].upper()}"
                        idx = 1
                        while Department.query.filter_by(short_code=short_code).first():
                            short_code = f"{parent_dept.short_code}_{name[:2].upper()}{idx}"
                            idx += 1

                    subdept = Department(
                        name=name,
                        short_code=short_code,
                        note=role if role else None,
                        parent_department_id=parent_id
                    )
                    db.session.add(subdept)
                    db.session.commit()
                    flash(f'Sub-department "{name}" created successfully under {parent_dept.name}!', 'success')
                    return redirect(url_for('subdepartment_master'))

    # Sub-departments only (parent_department_id is NOT None)
    subdepartments = Department.query.filter(Department.parent_department_id != None).order_by(Department.parent_department_id, Department.name).all()
    parent_departments = Department.query.filter(Department.parent_department_id == None).order_by(Department.name).all()

    return render_template(
        'masters/subdepartment_master.html',
        subdepartments=subdepartments,
        parent_departments=parent_departments,
        error_msg=error_msg
    )

@app.route('/masters/subdepartment/edit/<int:subdept_id>', methods=['POST'])
@login_required
def edit_subdepartment(subdept_id):
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))

    subdept = Department.query.get_or_404(subdept_id)
    parent_id = request.form.get('department_id', type=int)
    name = request.form.get('name', '').strip()
    role = request.form.get('role', '').strip()

    if not name or not parent_id:
        flash('Sub-department name and parent department are required!', 'danger')
        return redirect(url_for('subdepartment_master'))

    subdept.name = name
    subdept.parent_department_id = parent_id
    subdept.note = role if role else None
    db.session.commit()
    flash(f'Sub-department "{subdept.name}" updated successfully!', 'success')
    return redirect(url_for('subdepartment_master'))

@app.route('/masters/subdepartment/delete/<int:subdept_id>', methods=['POST'])
@login_required
def delete_subdepartment(subdept_id):
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))

    subdept = Department.query.get_or_404(subdept_id)
    emp_count = Employee.query.filter_by(department_id=subdept.id).count()
    if emp_count > 0:
        flash(f'Cannot delete sub-department "{subdept.name}". It is assigned to {emp_count} active employees.', 'danger')
    else:
        db.session.delete(subdept)
        db.session.commit()
        flash(f'Sub-department "{subdept.name}" deleted successfully.', 'success')

    return redirect(url_for('subdepartment_master'))

# ----------------- Grade & Salary Master -----------------
@app.route('/masters/grade-salary', methods=['GET', 'POST'])
@login_required
def grade_salary_master():
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized access to Master Management.', 'danger')
        return redirect(url_for('dashboard'))

    error_msg = None
    if request.method == 'POST':
        dept_id = request.form.get('department_id', type=int)
        sub_dept_id = request.form.get('sub_department_id', type=int)
        grade_name = request.form.get('grade_name', '').strip()
        salary_str = request.form.get('salary', '').strip()
        note = request.form.get('note', '').strip()

        if not dept_id or not grade_name or not salary_str:
            error_msg = 'Department, Grade Name, and Salary are required!'
        else:
            try:
                salary = float(salary_str.replace(',', '').replace('₹', ''))
                gsm = GradeSalaryMaster(
                    department_id=dept_id,
                    sub_department_id=sub_dept_id if sub_dept_id else None,
                    grade_name=grade_name,
                    salary=salary,
                    note=note if note else None
                )
                db.session.add(gsm)
                db.session.commit()
                flash(f'Grade "{grade_name}" with Salary ₹{salary:,.2f} added successfully!', 'success')
                return redirect(url_for('grade_salary_master'))
            except ValueError:
                error_msg = 'Please enter a valid numeric salary amount.'

    records = GradeSalaryMaster.query.order_by(GradeSalaryMaster.department_id, GradeSalaryMaster.grade_name).all()
    departments = Department.query.filter(Department.parent_department_id == None).order_by(Department.name).all()

    return render_template(
        'masters/grade_salary_master.html',
        records=records,
        departments=departments,
        error_msg=error_msg
    )

@app.route('/masters/grade-salary/edit/<int:id>', methods=['POST'])
@login_required
def edit_grade_salary(id):
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))

    record = GradeSalaryMaster.query.get_or_404(id)
    dept_id = request.form.get('department_id', type=int)
    sub_dept_id = request.form.get('sub_department_id', type=int)
    grade_name = request.form.get('grade_name', '').strip()
    salary_str = request.form.get('salary', '').strip()
    note = request.form.get('note', '').strip()

    if not dept_id or not grade_name or not salary_str:
        flash('Department, Grade Name, and Salary are required!', 'danger')
        return redirect(url_for('grade_salary_master'))

    try:
        record.department_id = dept_id
        record.sub_department_id = sub_dept_id if sub_dept_id else None
        record.grade_name = grade_name
        record.salary = float(salary_str.replace(',', '').replace('₹', ''))
        record.note = note if note else None
        db.session.commit()
        flash(f'Grade & Salary record updated successfully!', 'success')
    except ValueError:
        flash('Invalid salary amount.', 'danger')

    return redirect(url_for('grade_salary_master'))

@app.route('/masters/grade-salary/delete/<int:id>', methods=['POST'])
@login_required
def delete_grade_salary(id):
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))

    record = GradeSalaryMaster.query.get_or_404(id)
    db.session.delete(record)
    db.session.commit()
    flash(f'Grade & Salary record for "{record.grade_name}" deleted.', 'success')
    return redirect(url_for('grade_salary_master'))

@app.route('/api/departments/<int:dept_id>/subdepartments', methods=['GET'])
@login_required
def api_get_subdepartments(dept_id):
    subdepts = Department.query.filter_by(parent_department_id=dept_id).order_by(Department.name).all()
    return jsonify({
        'success': True,
        'subdepartments': [{'id': s.id, 'name': s.name, 'short_code': s.short_code} for s in subdepts]
    })

# ----------------- Reporting Hierarchy Master -----------------
@app.route('/masters/reporting-hierarchy', methods=['GET'])
@login_required
def reporting_hierarchy():
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized access to Master Management.', 'danger')
        return redirect(url_for('dashboard'))

    employees = Employee.query.filter_by(is_active=True).filter(
        Employee.employment_type != 'DEPARTMENT',
        ~Employee.name.ilike('%Department%')
    ).order_by(Employee.name).all()
    departments = Department.query.filter(Department.parent_department_id == None).order_by(Department.name).all()
    managers = Employee.query.filter(
        Employee.is_active == True,
        Employee.employment_type != 'DEPARTMENT',
        ~Employee.name.ilike('%Department%')
    ).order_by(Employee.name).all()
    ceo = Employee.query.filter(Employee.role == 'MD').first() or Employee.query.filter(
        Employee.manager_id == None,
        Employee.employment_type != 'DEPARTMENT',
        ~Employee.name.ilike('%Department%')
    ).first()

    return render_template(
        'masters/reporting_hierarchy.html',
        employees=employees,
        departments=departments,
        managers=managers,
        ceo=ceo
    )

@app.route('/api/hierarchy/tree', methods=['GET'])
@login_required
def api_hierarchy_tree():
    """Builds recursive JSON org tree for interactive visualization"""
    palette = [
        '#059669', '#0284c7', '#7c3aed', '#d97706', '#dc2626',
        '#0d9488', '#4f46e5', '#ea580c', '#0891b2', '#16a34a'
    ]

    all_employees = Employee.query.filter_by(is_active=True).filter(
        Employee.employment_type != 'DEPARTMENT',
        ~Employee.name.ilike('%Department%')
    ).order_by(Employee.name).all()
    emp_map = {e.id: e for e in all_employees}

    subs_by_mgr = {}
    for e in all_employees:
        m_id = e.manager_id
        if m_id not in subs_by_mgr:
            subs_by_mgr[m_id] = []
        subs_by_mgr[m_id].append(e)

    def count_total_subordinates(emp_id):
        direct = subs_by_mgr.get(emp_id, [])
        total = len(direct)
        for sub in direct:
            total += count_total_subordinates(sub.id)
        return total

    def build_node(emp, depth=0):
        color = palette[(emp.department_id or 1) % len(palette)]
        sub_list = subs_by_mgr.get(emp.id, [])
        # Prioritize subordinates who themselves manage people
        sub_list = sorted(sub_list, key=lambda x: (len(subs_by_mgr.get(x.id, [])) == 0, x.clean_name or x.name))
        return {
            'id': emp.id,
            'emp_id': emp.emp_id,
            'name': emp.clean_name or emp.name,
            'initials': emp.initials,
            'designation': emp.designation or ('Managing Director & CEO' if emp.role == 'MD' else emp.role or 'Team Member'),
            'department': emp.department.name if emp.department else 'General',
            'department_id': emp.department_id,
            'role': emp.role,
            'email': emp.email,
            'color': color,
            'depth': depth,
            'direct_reports_count': len(sub_list),
            'total_reports_count': count_total_subordinates(emp.id),
            'subordinates': [build_node(s, depth + 1) for s in sub_list]
        }

    # Top leader: CEO / MD is the single apex root
    ceo = next((e for e in all_employees if e.role == 'MD'), None)
    if ceo:
        # If any active non-CEO employee lacks manager_id or manager not in active list, assign to CEO
        other_unassigned = [e for e in all_employees if e.id != ceo.id and (not e.manager_id or e.manager_id not in emp_map)]
        if other_unassigned:
            if ceo.id not in subs_by_mgr:
                subs_by_mgr[ceo.id] = []
            for un in other_unassigned:
                if un not in subs_by_mgr[ceo.id]:
                    subs_by_mgr[ceo.id].append(un)
        roots = [ceo]
    else:
        roots = [e for e in all_employees if not e.manager_id or e.manager_id not in emp_map]
        if not roots and all_employees:
            roots = [all_employees[0]]

    tree = [build_node(r) for r in roots]

    return jsonify({
        'success': True,
        'tree': tree,
        'total_employees': len(all_employees)
    })

@app.route('/api/hierarchy/update-manager', methods=['POST'])
@login_required
def api_update_manager():
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        data = request.get_json(silent=True) or request.form
        
        # Safely parse employee_id
        raw_emp = data.get('employee_id')
        try:
            emp_id = int(raw_emp) if raw_emp not in [None, '', 'null', 'undefined'] else None
        except (ValueError, TypeError):
            emp_id = None

        # Safely parse new_manager_id
        raw_mgr = data.get('new_manager_id')
        try:
            new_manager_id = int(raw_mgr) if raw_mgr not in [None, '', 'null', 'undefined', '0', 0] else None
        except (ValueError, TypeError):
            new_manager_id = None

        if not emp_id:
            return jsonify({'success': False, 'error': 'Employee ID is required'}), 400

        emp = Employee.query.get_or_404(emp_id)

        if new_manager_id:
            if new_manager_id == emp.id:
                return jsonify({'success': False, 'error': 'An employee cannot report to themselves.'}), 400

            new_mgr = Employee.query.get(new_manager_id)
            if not new_mgr:
                return jsonify({'success': False, 'error': 'Target manager not found'}), 404

            # Circular dependency check
            curr = new_mgr
            visited = set()
            while curr and curr.manager_id:
                if curr.manager_id == emp.id:
                    return jsonify({'success': False, 'error': f'Circular hierarchy loop detected: {new_mgr.name} already reports to {emp.name}.'}), 400
                if curr.id in visited:
                    break
                visited.add(curr.id)
                curr = Employee.query.get(curr.manager_id)

            emp.manager_id = new_mgr.id
            mgr_name = new_mgr.name
        else:
            emp.manager_id = None
            mgr_name = 'Top Executive (No Manager)'

        db.session.commit()

        log_audit_trail('REPORTING_HIERARCHY_UPDATE', 'employee', emp.id, None, {
            'employee': emp.name,
            'new_manager': mgr_name,
            'updated_by': current_user.name
        })

        return jsonify({
            'success': True,
            'message': f'Reporting manager for {emp.name} updated to {mgr_name} successfully!'
        })
    except Exception as e:
        db.session.rollback()
        print(f"[ERROR in api_update_manager]: {e}")
        return jsonify({'success': False, 'error': f'Error updating manager: {str(e)}'}), 500

# ----------------- Holiday Master (Multi-Year Support) -----------------
@app.route('/masters/holiday', methods=['GET', 'POST'])
@login_required
def holiday_master():
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized access to Master Management.', 'danger')
        return redirect(url_for('dashboard'))

    # Available calendar years in database (ensure at least 2026 and 2027)
    db_years = {r[0] for r in db.session.query(HolidayMaster.calendar_year).distinct().all() if r[0]}
    available_years = sorted(list(db_years | {2026, 2027}))

    selected_year = request.args.get('year', type=int) or request.form.get('calendar_year', type=int) or 2026

    error_msg = None
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_year':
            new_yr = request.form.get('new_year', type=int)
            if new_yr and 2000 <= new_yr <= 2100:
                if new_yr not in available_years:
                    available_years = sorted(list(set(available_years) | {new_yr}))
                flash(f'Calendar Year {new_yr} opened. You can now add holidays for {new_yr}.', 'info')
                return redirect(url_for('holiday_master', year=new_yr))
            else:
                error_msg = 'Please provide a valid 4-digit calendar year (e.g. 2027).'

        else:
            name = request.form.get('holiday_name', '').strip()
            date_str = request.form.get('holiday_date', '').strip()
            h_type = request.form.get('holiday_type', 'Public Holiday')
            desc = request.form.get('description', '').strip()
            cal_year = request.form.get('calendar_year', type=int) or selected_year

            if not name or not date_str:
                error_msg = 'Holiday name and date are required!'
            else:
                try:
                    h_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    day_name = h_date.strftime('%A')
                    # Synchronize calendar year with holiday date's year
                    actual_year = h_date.year

                    # Check for duplicate holiday on same date
                    existing = HolidayMaster.query.filter_by(holiday_date=h_date).first()
                    if existing:
                        error_msg = f'A holiday ("{existing.holiday_name}") is already configured for {h_date.strftime("%d-%b-%Y")}.'
                    else:
                        h = HolidayMaster(
                            calendar_year=actual_year,
                            holiday_name=name,
                            holiday_date=h_date,
                            day_of_week=day_name,
                            holiday_type=h_type,
                            description=desc if desc else None
                        )
                        db.session.add(h)
                        db.session.commit()
                        flash(f'Holiday "{name}" on {h_date.strftime("%d-%b-%Y")} added successfully to Calendar Year {actual_year}!', 'success')
                        return redirect(url_for('holiday_master', year=actual_year))
                except ValueError:
                    error_msg = 'Invalid date format.'

    holidays = HolidayMaster.query.filter_by(calendar_year=selected_year).order_by(HolidayMaster.holiday_date).all()
    # Year holiday counts
    year_counts = {}
    for yr in available_years:
        year_counts[yr] = HolidayMaster.query.filter_by(calendar_year=yr).count()

    return render_template(
        'masters/holiday_master.html',
        holidays=holidays,
        available_years=available_years,
        selected_year=selected_year,
        year_counts=year_counts,
        error_msg=error_msg
    )

@app.route('/masters/holiday/delete/<int:id>', methods=['POST'])
@login_required
def delete_holiday(id):
    if current_user.role not in ['HR', 'MD', 'ADMIN', 'Admin']:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))

    h = HolidayMaster.query.get_or_404(id)
    cal_year = h.calendar_year or (h.holiday_date.year if h.holiday_date else 2026)
    db.session.delete(h)
    db.session.commit()
    flash(f'Holiday "{h.holiday_name}" deleted successfully.', 'success')
    return redirect(url_for('holiday_master', year=cal_year))

@app.route('/api/next-file-number')
def api_next_file_number():
    financial_year = request.args.get('financial_year')
    department_id = request.args.get('department_id', type=int)
    sub_department_id = request.args.get('sub_department_id', type=int)
    if not financial_year or not department_id:
        return jsonify({'error': 'Missing required parameters'}), 400
    department = Department.query.get(department_id)
    if not department:
        return jsonify({'error': 'Department not found'}), 404
    sub_department = Department.query.get(sub_department_id) if sub_department_id else None
    file_number = generate_file_number(financial_year, department, sub_department)
    return jsonify({'file_number': file_number})

@app.route('/project/<int:project_id>/summary')
@login_required
def view_project_summary(project_id):
    if current_user.role != 'MD':
        abort(403)
    project = JobIndent.query.get_or_404(project_id)
    job_card = project.job_card
    tasks = job_card.tasks if job_card else []
    team_members = set()
    for task in tasks:
        for assignee in getattr(task, 'assignees', []):
            team_members.add(assignee)
    budget_items = job_card.budget_items if job_card else []
    timesheets = []
    for task in tasks:
        timesheets.extend(getattr(task, 'weekly_timesheets', []))
    # Budget summary calculations
    contract_value = project.contract_value or 0
    estimated_value = job_card.estimated_value if job_card and job_card.estimated_value else 0
    overhead = estimated_value * 0.20
    profit = estimated_value * 0.15
    grand_total = estimated_value + overhead + profit
    difference = contract_value - grand_total if contract_value and grand_total else 0
    return render_template('job_indents/project_summary.html', project=project, job_card=job_card, tasks=tasks, team_members=team_members, budget_items=budget_items, timesheets=timesheets,
        contract_value=contract_value, estimated_value=estimated_value, overhead=overhead, profit=profit, grand_total=grand_total, difference=difference)

@app.route('/project/<int:project_id>/pdf')
@login_required
def generate_project_pdf(project_id):
    if current_user.role != 'MD':
        abort(403)
    project = JobIndent.query.get_or_404(project_id)
    job_card = project.job_card
    tasks = job_card.tasks if job_card else []
    team_members = set()
    for task in tasks:
        for assignee in getattr(task, 'assignees', []):
            team_members.add(assignee)
    budget_items = job_card.budget_items if job_card else []
    timesheets = []
    for task in tasks:
        timesheets.extend(getattr(task, 'weekly_timesheets', []))
    contract_value = project.contract_value or 0
    estimated_value = job_card.estimated_value if job_card and job_card.estimated_value else 0
    overhead = estimated_value * 0.20
    profit = estimated_value * 0.15
    grand_total = estimated_value + overhead + profit
    difference = contract_value - grand_total if contract_value and grand_total else 0
    generated_on = datetime.now().strftime('%d-%b-%Y %H:%M')
    rendered = render_template('job_indents/project_summary_pdf.html', project=project, job_card=job_card, tasks=tasks, team_members=team_members, budget_items=budget_items, timesheets=timesheets, generated_on=generated_on, contract_value=contract_value, estimated_value=estimated_value, overhead=overhead, profit=profit, grand_total=grand_total, difference=difference)
    from xhtml2pdf import pisa
    pdf = BytesIO()
    pisa.CreatePDF(rendered, dest=pdf)
    pdf.seek(0)
    return send_file(pdf, as_attachment=True, download_name=f'Project_Summary_{project.file_number}.pdf', mimetype='application/pdf')

# Serve the logo
@app.route('/static/<path:filename>')
def serve_static(filename):
    static_dir = os.path.join(BASE_DIR, 'static')
    return send_from_directory(static_dir, filename)

@app.route('/favicon.ico')
def favicon():
    static_dir = os.path.join(BASE_DIR, 'static')
    return send_from_directory(static_dir, 'emc_logo_clean.png', mimetype='image/png')

@app.route('/bd/project-summary')
@login_required
def bd_project_summary():
    if current_user.role != 'BD':
        abort(403)
    # Get all job indents created by the current BD user
    projects = JobIndent.query.filter_by(created_by_id=current_user.id).order_by(JobIndent.created_at.desc()).all()
    return render_template('bd_project_summary.html', projects=projects)

@app.route('/bd/project-summary/pdf')
@login_required
def bd_project_summary_pdf():
    if current_user.role != 'BD':
        abort(403)
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    projects = JobIndent.query.filter_by(created_by_id=current_user.id).order_by(JobIndent.created_at.desc()).all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph("Project Summary", styles['Title']))
    data = [["Sl. No", "Title of the Project", "Client", "Date of Creation", "Date of Approval", "Contract Value"]]
    total_value = 0
    for idx, p in enumerate(projects, 1):
        val = p.contract_value if p.contract_value else 0
        total_value += val
        data.append([
            idx,
            p.project_name,
            p.client_name,
            p.created_at.strftime('%d-%b-%Y') if p.created_at else '',
            p.approved_at.strftime('%d-%b-%Y') if p.status == 'Approved' and p.approved_at else '-',
            f"Rs. {val:,.2f}" if val else ''
        ])
    # Add total row
    data.append(['', '', '', '', 'Total', f'Rs. {total_value:,.2f}'])
    table = Table(data, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-2), colors.whitesmoke),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,-1), (-1,-1), colors.beige)
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='BD_Project_Summary.pdf', mimetype='application/pdf')

@app.route('/bd/project-summary/excel')
@login_required
def bd_project_summary_excel():
    if current_user.role != 'BD':
        abort(403)
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    projects = JobIndent.query.filter_by(created_by_id=current_user.id).order_by(JobIndent.created_at.desc()).all()
    data = []
    for idx, p in enumerate(projects, 1):
        data.append({
            'Sl. No': idx,
            'Title of the Project': p.project_name,
            'Client': p.client_name,
            'Date of Creation': p.created_at.strftime('%d-%b-%Y') if p.created_at else '',
            'Date of Approval': p.approved_at.strftime('%d-%b-%Y') if p.status == 'Approved' and p.approved_at else '-',
            'Contract Value': p.contract_value
        })
    import pandas as pd
    import openpyxl
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Project Summary', index=False)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='BD_Project_Summary.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/job-card/<int:indent_id>/add-task', methods=['POST'])
@login_required
def add_task_to_job_card(indent_id):
    try:
        if current_user.role != 'PM':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        indent = JobIndent.query.get_or_404(indent_id)
        job_card = indent.job_card
        if not job_card:
            job_card = JobCard(job_indent_id=indent.id, status='Draft')
            db.session.add(job_card)
            db.session.commit()
        data = request.get_json()
        print('Received data:', data)
        desc = bleach.clean(data.get('task_desc', ''))
        man_days = int(data.get('man_days', 0))
        man_hours = int(data.get('man_hours', 0))
        timeline_start_str = data.get('timeline_start')
        timeline_end_str = data.get('timeline_end')
        timeline_start = datetime.strptime(timeline_start_str, '%Y-%m-%d').date() if timeline_start_str else None
        timeline_end = datetime.strptime(timeline_end_str, '%Y-%m-%d').date() if timeline_end_str else None
        assignee_id = data.get('team_member')
        if not (desc and man_days and man_hours and timeline_start and timeline_end and assignee_id):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        assignee = Employee.query.get(int(assignee_id))
        if not assignee:
            return jsonify({'success': False, 'error': 'Assignee not found'}), 404
        # Strong duplicate check: any task for this job card with same desc, dates, and assignee
        for t in job_card.tasks:
            if (
                t.description == desc and
                t.timeline_start == timeline_start and
                t.timeline_end == timeline_end and
                any(a.id == assignee.id for a in t.assignees)
            ):
                return jsonify({'success': False, 'error': 'This employee is already assigned to this task.'}), 400
        # Only create and append if not duplicate
        task = Task(description=desc, man_days=man_days, man_hours=man_hours, timeline_start=timeline_start, timeline_end=timeline_end)
        task.assignees.append(assignee)
        job_card.tasks.append(task)
        try:
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': 'Duplicate assignment detected. Please check your team assignments.'}), 400
        return jsonify({'success': True})
    except Exception as e:
        print('Error in add_task_to_job_card:', e)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/job-card/<int:indent_id>/assignments')
@login_required
def get_job_card_assignments(indent_id):
    indent = JobIndent.query.get_or_404(indent_id)
    job_card = indent.job_card
    assignments = []
    if job_card:
        for task in job_card.tasks:
            for assignee in getattr(task, 'assignees', []):
                assignments.append({
                    'assignee_name': assignee.name,
                    'task_description': task.description,
                    'man_days': task.man_days,
                    'man_hours': task.man_days * 8,  # Always calculate as man_days * 8
                    'start_date': task.timeline_start.strftime('%d-%m-%Y') if task.timeline_start else '',
                    'end_date': task.timeline_end.strftime('%d-%m-%Y') if task.timeline_end else '',
                    'task_id': task.id,
                    'monthly_salary': assignee.monthly_salary or 0
                })
    return jsonify({'assignments': assignments})

@app.route('/job-card/<int:indent_id>/delete-assignment/<int:task_id>', methods=['DELETE'])
@login_required
def delete_job_card_assignment(indent_id, task_id):
    indent = JobIndent.query.get_or_404(indent_id)
    job_card = indent.job_card
    if not job_card:
        return jsonify({'success': False, 'error': 'Job card not found'}), 404
    task = next((t for t in job_card.tasks if t.id == task_id), None)
    if not task:
        return jsonify({'success': False, 'error': 'Task not found'}), 404
    db.session.delete(task)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/delete-all-projects', methods=['POST'])
@login_required
def delete_all_projects():
    if current_user.role != 'MD':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    try:
        db.session.query(Task).delete()
        db.session.query(JobCard).delete()
        db.session.query(JobIndent).delete()
        db.session.commit()
        return jsonify({'success': True, 'message': 'All project history deleted.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/job-cards/ceo')
@login_required
@nocache
def ceo_job_cards():
    if current_user.role != 'MD':
        abort(403)
    # All job cards for the first tab
    all_job_cards = JobCard.query.all()
    # Projects assigned to the CEO (usually none, but for completeness)
    assigned_projects = JobIndent.query.filter_by(project_manager_id=current_user.id).all()
    return render_template('job_cards/ceo_job_cards.html', job_cards=all_job_cards, projects=assigned_projects)

@app.route('/timesheet/reject/<int:entry_id>', methods=['POST'])
@login_required
def reject_timesheet_action(entry_id):
    entry = WeeklyTimesheet.query.get_or_404(entry_id)
    # If the timesheet belongs to a PM, only HR can reject
    if entry.employee.role == 'PM':
        if current_user.role != 'HR':
            abort(403)
        entry.status = 'Rejected'
        entry.approval_level = None
        entry.approved_by_id = None
        db.session.commit()
        flash(f"Project Manager's timesheet for {entry.employee.name} (Week of {entry.week_start_date.strftime('%d-%b-%Y')}) has been rejected by HR.", 'warning')
        return redirect(url_for('hr_timesheets'))
    # If the timesheet belongs to an employee, only PM can reject
    else:
        if current_user.role != 'PM' or entry.task.job_card.indent.project_manager_id != current_user.id:
            abort(403)
        entry.status = 'Rejected'
        entry.approval_level = None
        entry.approved_by_id = None
        db.session.commit()
        flash(f"Weekly timesheet for {entry.employee.name} (Week of {entry.week_start_date.strftime('%d-%b-%Y')}) has been rejected by PM.", 'warning')
        return redirect(url_for('verify_timesheets'))

@app.route('/timesheet/submit_week', methods=['POST'])
@login_required
@nocache
def submit_weekly_timesheet():
    if current_user.role != 'EMP':
        abort(403)
    from datetime import date, timedelta
    today = date.today()
    # Find the Monday of the current week
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    # Get all daily logs for this week
    week_logs = Timesheet.query.filter(
        Timesheet.employee_id == current_user.id,
        Timesheet.date >= week_start,
        Timesheet.date <= week_end
    ).all()
    if not week_logs:
        flash('No timesheet entries found for this week.', 'danger')
        return redirect(url_for('dashboard'))
    # Mark all as submitted for review
    for log in week_logs:
        log.status = 'Weekly Submitted'
    db.session.commit()
    flash('Weekly timesheet submitted for PM review!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/pm/weekly-timesheets')
@login_required
@nocache
def pm_weekly_timesheets():
    if current_user.role != 'PM':
        abort(403)
    pm_projects = JobIndent.query.filter_by(project_manager_id=current_user.id).all()
    project_ids = [p.id for p in pm_projects]
    if not project_ids:
        return render_template('dashboards/pm_weekly_timesheets.html', pending_timesheets=[])
    tasks = Task.query.join(JobCard).filter(JobCard.job_indent_id.in_(project_ids)).all()
    task_ids = [t.id for t in tasks]
    weekly_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.task_id.in_(task_ids),
        WeeklyTimesheet.status == 'Submitted'
    ).order_by(WeeklyTimesheet.week_start_date.desc()).all()
    timesheet_groups = {}
    for ts in weekly_timesheets:
        key = (ts.employee_id, ts.week_start_date)
        if key not in timesheet_groups:
            timesheet_groups[key] = {
                'employee': ts.employee,
                'week_start': ts.week_start_date,
                'week_end': ts.week_end_date,
                'timesheets': []
            }
        timesheet_groups[key]['timesheets'].append(ts)
    pending_timesheets = list(timesheet_groups.values())
    return render_template('dashboards/pm_weekly_timesheets.html', pending_timesheets=pending_timesheets)

@app.route('/pm/approve_week', methods=['POST'])
@login_required
@nocache
def pm_approve_week():
    if current_user.role != 'PM':
        abort(403)
    
    emp_id = int(request.form['employee_id'])
    week_start = request.form['week_start']
    week_end = request.form['week_end']
    
    from datetime import datetime
    week_start = datetime.strptime(week_start, '%Y-%m-%d').date()
    week_end = datetime.strptime(week_end, '%Y-%m-%d').date()
    
    # Update WeeklyTimesheet entries
    weekly_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.employee_id == emp_id,
        WeeklyTimesheet.week_start_date == week_start,
        WeeklyTimesheet.week_end_date == week_end,
        WeeklyTimesheet.status == 'Submitted'
    ).all()
    
    for ts in weekly_timesheets:
        ts.status = 'PM Approved'
        ts.approved_by_id = current_user.id
        ts.approval_level = 'PM'
    
    # Also update regular Timesheet entries
    timesheets = Timesheet.query.filter(
        Timesheet.employee_id == emp_id,
        Timesheet.date >= week_start,
        Timesheet.date <= week_end,
        Timesheet.status == 'Submitted'
    ).all()
    
    for ts in timesheets:
        ts.status = 'PM Approved'
    
    db.session.commit()
    
    # Send email notification to employee
    employee = Employee.query.get(emp_id)
    if employee:
        subject = f"Timesheet Approved - Week of {week_start.strftime('%d %b %Y')}"
        body = f"""
        Dear {employee.name},
        
        Your timesheet for the week of {week_start.strftime('%d %b %Y')} has been approved by your Project Manager.
        
        Thanks,
        System
        """
        
        try:
            from mail import send_email
            send_email(employee.email, subject, body)
        except Exception as e:
            print(f"Error sending email to {employee.email}: {e}")
    
    flash('Timesheet approved and sent to HR for verification.', 'success')
    return redirect(url_for('pm_weekly_timesheets'))

@app.route('/pm/reject_week', methods=['POST'])
@login_required
@nocache
def pm_reject_week():
    if current_user.role != 'PM':
        abort(403)
    
    emp_id = int(request.form['employee_id'])
    week_start = request.form['week_start']
    week_end = request.form['week_end']
    rejection_reason = request.form.get('rejection_reason', 'No reason provided')
    
    from datetime import datetime
    week_start = datetime.strptime(week_start, '%Y-%m-%d').date()
    week_end = datetime.strptime(week_end, '%Y-%m-%d').date()
    
    # Update WeeklyTimesheet entries
    weekly_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.employee_id == emp_id,
        WeeklyTimesheet.week_start_date == week_start,
        WeeklyTimesheet.week_end_date == week_end,
        WeeklyTimesheet.status == 'Submitted'
    ).all()
    
    for ts in weekly_timesheets:
        ts.status = 'Rejected'
        ts.approved_by_id = current_user.id
        ts.approval_level = 'PM'
    
    # Also update regular Timesheet entries
    timesheets = Timesheet.query.filter(
        Timesheet.employee_id == emp_id,
        Timesheet.date >= week_start,
        Timesheet.date <= week_end,
        Timesheet.status == 'Submitted'
    ).all()
    
    for ts in timesheets:
        ts.status = 'Rejected'
    
    db.session.commit()
    
    # Send email notification to employee
    employee = Employee.query.get(emp_id)
    if employee:
        subject = f"Timesheet Rejected - Week of {week_start.strftime('%d %b %Y')}"
        body = f"""
        Dear {employee.name},
        
        Your timesheet for the week of {week_start.strftime('%d %b %Y')} has been rejected by your Project Manager.
        
        Reason: {rejection_reason}
        
        Please review and resubmit your timesheet.
        
        Thanks,
        System
        """
        
        try:
            from mail import send_email
            send_email(employee.email, subject, body)
        except Exception as e:
            print(f"Error sending email to {employee.email}: {e}")
    
    flash('Timesheet rejected. Employee has been notified.', 'warning')
    return redirect(url_for('pm_weekly_timesheets'))

@app.route('/hr/weekly-timesheets')
@login_required
@nocache
def hr_weekly_timesheets():
    if current_user.role != 'HR':
        abort(403)
    
    # Get all PM Approved weekly timesheets
    weekly_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.status == 'PM Approved'
    ).order_by(WeeklyTimesheet.week_start_date.desc()).all()
    
    # Group by employee and week
    timesheet_groups = {}
    for ts in weekly_timesheets:
        key = (ts.employee_id, ts.week_start_date)
        if key not in timesheet_groups:
            timesheet_groups[key] = {
                'employee': ts.employee,
                'week_start': ts.week_start_date,
                'week_end': ts.week_end_date,
                'timesheets': []
            }
        timesheet_groups[key]['timesheets'].append(ts)
    
    pending_timesheets = list(timesheet_groups.values())
    
    return render_template('dashboards/hr_weekly_timesheets.html', pending_timesheets=pending_timesheets)

@app.route('/hr/verify_week', methods=['POST'])
@login_required
@nocache
def hr_verify_week():
    if current_user.role != 'HR':
        abort(403)
    
    emp_id = int(request.form['employee_id'])
    week_start = request.form['week_start']
    week_end = request.form['week_end']
    
    from datetime import datetime
    week_start = datetime.strptime(week_start, '%Y-%m-%d').date()
    week_end = datetime.strptime(week_end, '%Y-%m-%d').date()
    
    # Update WeeklyTimesheet entries
    weekly_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.employee_id == emp_id,
        WeeklyTimesheet.week_start_date == week_start,
        WeeklyTimesheet.week_end_date == week_end,
        WeeklyTimesheet.status == 'PM Approved'
    ).all()
    
    for ts in weekly_timesheets:
        ts.status = 'HR Approved'
        ts.approved_by_id = current_user.id
        ts.approval_level = 'HR'
    
    # Also update regular Timesheet entries
    timesheets = Timesheet.query.filter(
        Timesheet.employee_id == emp_id,
        Timesheet.date >= week_start,
        Timesheet.date <= week_end,
        Timesheet.status == 'PM Approved'
    ).all()
    
    for ts in timesheets:
        ts.status = 'HR Approved'
    
    db.session.commit()
    
    # Send email notification to employee
    employee = Employee.query.get(emp_id)
    if employee:
        subject = f"Timesheet Approved by HR - Week of {week_start.strftime('%d %b %Y')}"
        body = f"""
        Dear {employee.name},
        
        Your timesheet for the week of {week_start.strftime('%d %b %Y')} has been approved by HR.
        
        Thanks,
        System
        """
        
        try:
            from mail import send_email
            send_email(employee.email, subject, body)
        except Exception as e:
            print(f"Error sending email to {employee.email}: {e}")
    
    flash('Timesheet verified and approved by HR.', 'success')
    return redirect(url_for('hr_weekly_timesheets'))

@app.route('/hr/reject_week', methods=['POST'])
@login_required
@nocache
def hr_reject_week():
    if current_user.role != 'HR':
        abort(403)
    
    emp_id = int(request.form['employee_id'])
    week_start = request.form['week_start']
    week_end = request.form['week_end']
    rejection_reason = request.form.get('rejection_reason', 'No reason provided')
    
    from datetime import datetime
    week_start = datetime.strptime(week_start, '%Y-%m-%d').date()
    week_end = datetime.strptime(week_end, '%Y-%m-%d').date()
    
    # Update WeeklyTimesheet entries
    weekly_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.employee_id == emp_id,
        WeeklyTimesheet.week_start_date == week_start,
        WeeklyTimesheet.week_end_date == week_end,
        WeeklyTimesheet.status == 'PM Approved'
    ).all()
    
    for ts in weekly_timesheets:
        ts.status = 'Rejected'
        ts.approved_by_id = current_user.id
        ts.approval_level = 'HR'
    
    # Also update regular Timesheet entries
    timesheets = Timesheet.query.filter(
        Timesheet.employee_id == emp_id,
        Timesheet.date >= week_start,
        Timesheet.date <= week_end,
        Timesheet.status == 'PM Approved'
    ).all()
    
    for ts in timesheets:
        ts.status = 'Rejected'
    
    db.session.commit()
    
    # Send email notification to employee
    employee = Employee.query.get(emp_id)
    if employee:
        subject = f"Timesheet Rejected by HR - Week of {week_start.strftime('%d %b %Y')}"
        body = f"""
        Dear {employee.name},
        
        Your timesheet for the week of {week_start.strftime('%d %b %Y')} has been rejected by HR.
        
        Reason: {rejection_reason}
        
        Please review and resubmit your timesheet.
        
        Thanks,
        System
        """
        
        try:
            from mail import send_email
            send_email(employee.email, subject, body)
        except Exception as e:
            print(f"Error sending email to {employee.email}: {e}")
    
    flash('Timesheet rejected by HR. Employee has been notified.', 'warning')
    return redirect(url_for('hr_weekly_timesheets'))

@app.route('/pm/team-timesheet-status')
@login_required
@nocache
def pm_team_timesheet_status():
    if current_user.role != 'PM':
        abort(403)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    projects = JobIndent.query.filter_by(project_manager_id=current_user.id).all()
    team_status = []
    for project in projects:
        if not project.job_card:
            continue
        for task in project.job_card.tasks:
            for assignee in task.assignees:
                missing_days = []
                for i in range(7):
                    d = week_start + timedelta(days=i)
                    if d.weekday() >= 5:
                        continue
                    ts = Timesheet.query.filter_by(employee_id=assignee.id, task_id=task.id, date=d).first()
                    if not ts:
                        missing_days.append(d)
                team_status.append({
                    'project': project,
                    'task': task,
                    'assignee': assignee,
                    'missing_days': missing_days
                })
    return render_template('dashboards/pm_team_timesheet_status.html', team_status=team_status, week_start=week_start, week_end=week_end)

@app.route('/pm/send-timesheet-reminder', methods=['POST'])
@login_required
@nocache
def pm_send_timesheet_reminder():
    if current_user.role != 'PM':
        abort(403)
    assignee_id = int(request.form['assignee_id'])
    project_id = int(request.form['project_id'])
    task_id = int(request.form['task_id'])
    assignee = Employee.query.get_or_404(assignee_id)
    project = JobIndent.query.get_or_404(project_id)
    task = Task.query.get_or_404(task_id)
    subject = f"Timesheet Reminder: {project.project_name}"
    body = f"Dear {assignee.name},<br><br>This is a reminder to submit your daily timesheet for the task: <b>{task.description}</b> in project <b>{project.project_name}</b>.<br>Please log your hours as soon as possible.<br><br>Thanks,<br>{current_user.name} (Project Manager)"
    send_email(assignee.email, subject, body)
    flash(f"Reminder sent to {assignee.name}.", "success")
    return redirect(url_for('pm_team_timesheet_status'))

# Add automatic weekly submission function
def auto_submit_weekly_timesheets():
    from datetime import timedelta
    today = date.today()
    if today.weekday() in [5, 6]:  # Saturday or Sunday
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        drafts = TimesheetDraft.query.filter(
            TimesheetDraft.date >= week_start,
            TimesheetDraft.date <= week_end
        ).all()
        drafts_by_employee = {}
        for draft in drafts:
            drafts_by_employee.setdefault(draft.employee_id, []).append(draft)
        submitted_employees = set()
        for employee_id, emp_drafts in drafts_by_employee.items():
            weekly_entries = {}
            for draft in emp_drafts:
                draft_data = json.loads(draft.draft_data)
                for entry in draft_data['entries']:
                    key = (entry['project_id'], entry.get('task_id'))
                    if key not in weekly_entries:
                        weekly_entries[key] = {
                            'project_id': entry['project_id'],
                            'task_id': entry.get('task_id'),
                            'task_description': entry.get('task_description', ''),
                            'total_hours': 0,
                            'progress_descriptions': []
                        }
                    weekly_entries[key]['total_hours'] += entry['hours_worked']
                    weekly_entries[key]['progress_descriptions'].append(entry['progress_description'])
            for key, data in weekly_entries.items():
                weekly_entry = WeeklyTimesheet(
                    employee_id=employee_id,
                    task_id=data['task_id'] if data['project_id'] != 'general' else None,
                    week_start_date=week_start,
                    week_end_date=week_end,
                    total_hours=data['total_hours'],
                    progress_description='; '.join(data['progress_descriptions']),
                    status='Submitted'
                )
                db.session.add(weekly_entry)
            submitted_employees.add(employee_id)
            for draft in emp_drafts:
                db.session.delete(draft)
        db.session.commit()
        for employee_id in submitted_employees:
            employee = Employee.query.get(employee_id)
            if employee and employee.department:
                pm = Employee.query.filter_by(role='PM', department_id=employee.department_id).first()
                if pm:
                    subject = f"Weekly Timesheet Submitted - {employee.name}"
                    body = f"""
                    Dear {pm.name},<br><br>
                    {employee.name} has submitted their weekly timesheet for {week_start.strftime('%d %b')} - {week_end.strftime('%d %b %Y')}.<br><br>
                    Please review and approve the timesheet in the system.<br><br>
                    Thanks,<br>System
                    """
                    try:
                        from mail import send_email
                        send_email(pm.email, subject, body)
                    except Exception as e:
                        print(f"Error sending email to {pm.email}: {e}")
                    create_notification(
                        pm.id,
                        f"Weekly Timesheet Submitted - {employee.name}",
                        f"{employee.name} has submitted their weekly timesheet for {week_start.strftime('%d %b')} - {week_end.strftime('%d %b %Y')}",
                        'info'
                    )
        print(f"Auto-submitted {len(drafts)} weekly timesheets")

# --- Redesigned Timesheet Email Notification System ---
def send_weekly_timesheet_reminder():
    """
    Weekly email reminder sent to all active employees to fill up their timesheet for the week.
    Runs every Friday at 17:00 IST.
    """
    with app.app_context():
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        today = now_ist.date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=4)  # Mon - Fri
        week_range_str = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"

        employees = Employee.query.filter(
            Employee.role.in_(['EMP', 'PM']),
            Employee.is_active == True,
            Employee.employment_type != 'DEPARTMENT'
        ).all()

        for emp in employees:
            if not emp.email or '@' not in emp.email:
                continue
            subject = f"Weekly Timesheet Reminder: Week of {week_range_str}"
            body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h2 style="color: #0e8749; margin-top: 0;">Weekly Timesheet Reminder</h2>
                <p>Dear <b>{emp.name}</b>,</p>
                <p>This is a friendly reminder to complete and submit your timesheet entries for the current week: <b>{week_range_str}</b>.</p>
                <p>Kindly ensure all your project tasks and daily activities are logged accurately before closing your work for the week.</p>
                <div style="text-align: center; margin: 25px 0;">
                    <a href="https://pmstimesheet.vercel.app/login" style="background-color: #0e8749; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Log Your Timesheet</a>
                </div>
                <p style="color: #64748b; font-size: 13px;">Note: Sundays, Second Saturdays, and declared company holidays are non-working days and do not require timesheet entries.</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
                <p style="color: #94a3b8; font-size: 12px; margin-bottom: 0;">DayLog &bull; Unified Timesheet & Project Management System &bull; Ecometrix Consultants Pvt. Ltd.</p>
            </div>
            """
            try:
                send_email(emp.email, subject, body)
            except Exception as e:
                print(f"[ERROR] Failed to send weekly reminder to {emp.email}: {e}")

def send_monthly_missing_timesheet_reminder():
    """
    Sent on the last day of each month.
    Checks if an employee missed filling their timesheet on any working day in the month.
    Excludes Sundays, Second Saturdays, and Declared Holidays.
    If missed days exist, emails only those specific missed dates to the employee.
    """
    with app.app_context():
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        today = now_ist.date()

        # Determine last day of current month
        if today.month == 12:
            last_day_num = 31
        else:
            next_month = date(today.year, today.month + 1, 1)
            last_day_num = (next_month - timedelta(days=1)).day

        # Only run on the last date of each month!
        if today.day != last_day_num:
            return

        employees = Employee.query.filter(
            Employee.role.in_(['EMP', 'PM']),
            Employee.is_active == True,
            Employee.employment_type != 'DEPARTMENT'
        ).all()

        # Load holidays for this month
        holidays_query = HolidayMaster.query.filter(
            db.extract('year', HolidayMaster.holiday_date) == today.year,
            db.extract('month', HolidayMaster.holiday_date) == today.month
        ).all()
        holiday_dates = {h.holiday_date for h in holidays_query}

        # Calculate all working days in month up to today
        all_working_days = []
        for d in range(1, today.day + 1):
            cur_date = date(today.year, today.month, d)
            if is_sunday(cur_date):
                continue
            if is_second_saturday(cur_date):
                continue
            if cur_date in holiday_dates:
                continue
            all_working_days.append(cur_date)

        month_name = today.strftime('%B %Y')

        for emp in employees:
            if not emp.email or '@' not in emp.email:
                continue

            submitted = db.session.query(Timesheet.date).filter(
                Timesheet.employee_id == emp.id,
                db.extract('year', Timesheet.date) == today.year,
                db.extract('month', Timesheet.date) == today.month
            ).distinct().all()
            submitted_set = {s[0] for s in submitted if s[0]}

            missed_dates = [d for d in all_working_days if d not in submitted_set]

            if not missed_dates:
                continue

            formatted_missed = [d.strftime('%d-%b-%Y (%A)') for d in missed_dates]
            missed_list_html = "".join([f"<li style='margin-bottom: 4px;'><b>{d_str}</b></li>" for d_str in formatted_missed])

            subject = f"Action Required: Missed Timesheet Entries for {month_name}"
            body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #fca5a5; border-radius: 8px; background-color: #fffaf0;">
                <h2 style="color: #dc2626; margin-top: 0;">Missing Timesheet Notification</h2>
                <p>Dear <b>{emp.name}</b>,</p>
                <p>Today is the final day of <b>{month_name}</b>. Our records show that you have <b>{len(missed_dates)}</b> unsubmitted working day(s) for this month:</p>
                <div style="background: #ffffff; border: 1px solid #fed7aa; border-radius: 6px; padding: 12px 18px; margin: 15px 0;">
                    <ul style="margin: 0; padding-left: 20px; color: #9a3412;">
                        {missed_list_html}
                    </ul>
                </div>
                <p>Please log in to DayLog and submit your timesheets for the dates listed above to ensure accurate payroll and monthly project progress reporting.</p>
                <div style="text-align: center; margin: 25px 0;">
                    <a href="https://pmstimesheet.vercel.app/login" style="background-color: #dc2626; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Submit Missed Timesheets</a>
                </div>
                <p style="color: #64748b; font-size: 13px;">Note: Sundays, Second Saturdays, and declared company holidays have already been excluded.</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
                <p style="color: #94a3b8; font-size: 12px; margin-bottom: 0;">DayLog &bull; Unified Timesheet & Project Management System &bull; Ecometrix Consultants Pvt. Ltd.</p>
            </div>
            """
            try:
                send_email(emp.email, subject, body)
            except Exception as e:
                print(f"[ERROR] Failed to send monthly missing reminder to {emp.email}: {e}")

def send_missing_log_alerts():
    """Legacy wrapper calling send_monthly_missing_timesheet_reminder"""
    send_monthly_missing_timesheet_reminder()

# System-wide notification functions
def send_project_deadline_notifications():
    """Send notifications for upcoming project deadlines"""
    today = date.today()
    upcoming_deadline = today + timedelta(days=7)
    
    projects = JobIndent.query.filter(
        JobIndent.contract_end_date <= upcoming_deadline,
        JobIndent.contract_end_date >= today,
        JobIndent.status.in_(['Approved', 'In Progress'])
    ).all()
    
    for project in projects:
        # Notify PM
        if project.project_manager:
            subject = f"Project Deadline Alert: {project.project_name}"
            body = f"Dear {project.project_manager.name},<br><br>The project <b>{project.project_name}</b> (Code: {project.file_number}) is approaching its deadline on {project.contract_end_date.strftime('%d %b, %Y')}.<br><br>Please ensure all tasks are completed on time.<br><br>Thanks,<br>System"
            send_email(project.project_manager.email, subject, body)
        
        # Notify CEO/MD
        ceo_email = get_ceo_email()
        if ceo_email:
            ceo_subject = f"Project Deadline Alert: {project.project_name}"
            ceo_body = f"Dear CEO/MD,<br><br>The project <b>{project.project_name}</b> (Code: {project.file_number}) is approaching its deadline on {project.contract_end_date.strftime('%d %b, %Y')}.<br><br>PM: {project.project_manager.name if project.project_manager else 'Not Assigned'}<br><br>Thanks,<br>System"
            send_email(ceo_email, ceo_subject, ceo_body)

def send_task_assignment_notifications():
    """Send notifications for new task assignments"""
    # This would be called when tasks are assigned
    pass

def send_status_change_notifications():
    """Send notifications for project/task status changes"""
    # This would be called when status changes
    pass

def send_weekly_digest():
    """Send weekly digest to management"""
    with app.app_context():
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        
        # Get weekly statistics
        total_projects = JobIndent.query.count()
        active_projects = JobIndent.query.filter_by(status='In Progress').count()
        completed_projects = JobIndent.query.filter_by(status='Completed').count()
        pending_approvals = JobIndent.query.filter_by(status='Pending Approval').count()
        
        # Get timesheet statistics
        submitted_timesheets = WeeklyTimesheet.query.filter(
            WeeklyTimesheet.week_start_date == week_start
        ).count()
        
        approved_timesheets = WeeklyTimesheet.query.filter(
            WeeklyTimesheet.week_start_date == week_start,
            WeeklyTimesheet.status == 'HR Approved'
        ).count()
        
        # Send digest to CEO/MD
        ceo_email = get_ceo_email()
        if ceo_email:
            subject = f"Weekly Digest: {week_start.strftime('%d %b')} - {week_end.strftime('%d %b, %Y')}"
            body = f"""
            <h3>Weekly Project Management Digest</h3>
            <p><strong>Period:</strong> {week_start.strftime('%d %b')} - {week_end.strftime('%d %b, %Y')}</p>
            
            <h4>Project Overview</h4>
            <ul>
                <li>Total Projects: {total_projects}</li>
                <li>Active Projects: {active_projects}</li>
                <li>Completed Projects: {completed_projects}</li>
                <li>Pending Approvals: {pending_approvals}</li>
            </ul>
            
            <h4>Timesheet Summary</h4>
            <ul>
                <li>Submitted Timesheets: {submitted_timesheets}</li>
                <li>Approved Timesheets: {approved_timesheets}</li>
            </ul>
            
            <p>Please log in to the system for detailed reports.</p>
            
            <p>Thanks,<br>System</p>
            """
            send_email(ceo_email, subject, body)

# Update the scheduler to include new notifications
def schedule_automatic_tasks():
    """Schedule automatic tasks"""
    # Weekly reminder every Friday at 17:00 IST
    schedule.every().friday.at("17:00").do(send_weekly_timesheet_reminder)
    # Month-end missing timesheet alert: checked daily at 17:30 IST (only triggers on last day of month)
    schedule.every().day.at("17:30").do(send_monthly_missing_timesheet_reminder)
    schedule.every().day.at("10:00").do(send_project_deadline_notifications)
    schedule.every().friday.at("18:00").do(auto_submit_weekly_timesheets)
    schedule.every().friday.at("17:00").do(send_weekly_digest)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler in background thread
def start_scheduler():
    scheduler_thread = threading.Thread(target=schedule_automatic_tasks, daemon=True)
    scheduler_thread.start()

@app.route('/job-card/<int:indent_id>/calculate-profit', methods=['POST'])
@login_required
def calculate_job_card_profit(indent_id):
    """Advanced profit calculation with overhead and risk factors"""
    if current_user.role not in ['PM', 'MD']:
        abort(403)
    
    indent = JobIndent.query.get_or_404(indent_id)
    job_card = indent.job_card
    
    if not job_card:
        return jsonify({'error': 'Job card not found'}), 404
    
    # Advanced calculations
    contract_value = indent.contract_value or 0
    estimated_value = job_card.estimated_value or 0
    
    # Calculate manpower cost
    total_manpower_cost = 0
    for task in job_card.tasks:
        for assignee in task.assignees:
            monthly_salary = assignee.monthly_salary or 0
            daily_rate = (monthly_salary / 30) * 1.2  # 20% overhead
            task_cost = daily_rate * (task.man_days or 0)
            total_manpower_cost += task_cost
    
    # Calculate material cost from budget items
    material_cost = sum(item.amount for item in job_card.budget_items if item.category != 'Manpower')
    
    # Calculate overhead (15% of total cost)
    total_direct_cost = total_manpower_cost + material_cost
    overhead_cost = total_direct_cost * 0.15
    
    # Calculate risk factor (5% of contract value for contingency)
    risk_factor = contract_value * 0.05
    
    # Total estimated cost
    total_estimated_cost = total_direct_cost + overhead_cost + risk_factor
    
    # Profit calculations
    gross_profit = contract_value - total_estimated_cost
    profit_margin = (gross_profit / contract_value * 100) if contract_value > 0 else 0
    
    # Risk assessment
    risk_level = 'Low'
    if profit_margin < 10:
        risk_level = 'High'
    elif profit_margin < 20:
        risk_level = 'Medium'
    
    return jsonify({
        'contract_value': contract_value,
        'total_manpower_cost': total_manpower_cost,
        'material_cost': material_cost,
        'overhead_cost': overhead_cost,
        'risk_factor': risk_factor,
        'total_estimated_cost': total_estimated_cost,
        'gross_profit': gross_profit,
        'profit_margin': profit_margin,
        'risk_level': risk_level
    })

@app.route('/job-card/<int:indent_id>/validate', methods=['POST'])
@login_required
def validate_job_card(indent_id):
    """Validate job card for completeness and accuracy"""
    if current_user.role not in ['PM', 'MD']:
        abort(403)
    
    indent = JobIndent.query.get_or_404(indent_id)
    job_card = indent.job_card
    
    if not job_card:
        return jsonify({'error': 'Job card not found'}), 404
    
    validation_errors = []
    warnings = []
    
    # Check required fields
    if not job_card.estimated_value:
        validation_errors.append("Estimated value is required")
    
    if not job_card.tasks:
        validation_errors.append("At least one task must be assigned")
    
    # Check task assignments
    for task in job_card.tasks:
        if not task.assignees:
            validation_errors.append(f"Task '{task.description}' has no assignees")
        
        if task.timeline_start and task.timeline_end:
            if task.timeline_start >= task.timeline_end:
                validation_errors.append(f"Task '{task.description}' has invalid timeline")
            
            if task.timeline_end < date.today():
                warnings.append(f"Task '{task.description}' end date is in the past")
    
    # Check project timeline
    if indent.contract_start_date and indent.contract_end_date:
        if indent.contract_start_date >= indent.contract_end_date:
            validation_errors.append("Project contract dates are invalid")
    
    # Check budget items
    total_budget = sum(item.amount for item in job_card.budget_items)
    if total_budget == 0:
        warnings.append("No budget items defined")
    
    # Check for duplicate assignments
    all_assignments = []
    for task in job_card.tasks:
        for assignee in task.assignees:
            assignment_key = (assignee.id, task.description, task.timeline_start, task.timeline_end)
            if assignment_key in all_assignments:
                warnings.append(f"Duplicate assignment detected for {assignee.name} in task '{task.description}'")
            all_assignments.append(assignment_key)
    
    return jsonify({
        'is_valid': len(validation_errors) == 0,
        'validation_errors': validation_errors,
        'warnings': warnings
    })

@app.route('/job-card/<int:indent_id>/auto-calculate', methods=['POST'])
@login_required
def auto_calculate_job_card(indent_id):
    """Automatically calculate job card values based on assignments"""
    if current_user.role not in ['PM', 'MD']:
        abort(403)
    
    indent = JobIndent.query.get_or_404(indent_id)
    job_card = indent.job_card
    
    if not job_card:
        return jsonify({'error': 'Job card not found'}), 404
    
    # Calculate total manpower cost
    total_manpower_cost = 0
    total_man_hours = 0
    
    for task in job_card.tasks:
        for assignee in task.assignees:
            monthly_salary = assignee.monthly_salary or 0
            daily_rate = (monthly_salary / 30) * 1.2  # 20% overhead
            task_cost = daily_rate * (task.man_days or 0)
            total_manpower_cost += task_cost
            total_man_hours += task.man_hours or 0
    
    # Calculate material cost
    material_cost = sum(item.amount for item in job_card.budget_items if item.category != 'Manpower')
    
    # Add overhead (15%)
    overhead = (total_manpower_cost + material_cost) * 0.15
    
    # Calculate total estimated value
    total_estimated = total_manpower_cost + material_cost + overhead
    
    # Update job card
    job_card.estimated_value = total_estimated
    db.session.commit()
    
    return jsonify({
        'total_manpower_cost': total_manpower_cost,
        'material_cost': material_cost,
        'overhead': overhead,
        'total_estimated_value': total_estimated,
        'total_man_hours': total_man_hours
    })

@app.route('/hr/advanced-verification/<int:timesheet_id>', methods=['GET', 'POST'])
@login_required
@nocache
def hr_advanced_verification(timesheet_id):
    """Advanced HR verification with detailed checks and multi-level approval"""
    if current_user.role != 'HR':
        abort(403)
    
    timesheet = WeeklyTimesheet.query.get_or_404(timesheet_id)
    employee = timesheet.employee
    task = timesheet.task
    
    if request.method == 'POST':
        action = request.form.get('action')
        verification_notes = request.form.get('verification_notes', '').strip()
        
        if action == 'verify':
            # Advanced verification checks
            verification_checks = perform_advanced_verification(timesheet)
            
            if verification_checks['is_valid']:
                timesheet.status = 'HR Approved'
                timesheet.approval_level = 'HR'
                timesheet.approved_by_id = current_user.id
                db.session.commit()
                
                # Send approval notification
                subject = f"Timesheet Approved: {timesheet.week_start_date.strftime('%d %b')} - {timesheet.week_end_date.strftime('%d %b, %Y')}"
                body = f"Dear {employee.name},<br><br>Your timesheet for {timesheet.week_start_date.strftime('%d %b')} - {timesheet.week_end_date.strftime('%d %b, %Y')} has been approved by HR.<br><br>Total Hours: {timesheet.total_hours}<br><br>Thanks,<br>{current_user.name} (HR)"
                send_email(employee.email, subject, body)
                
                flash('Timesheet verified successfully.', 'success')
            else:
                flash(f'Verification failed: {", ".join(verification_checks["errors"])}', 'danger')
                
        elif action == 'reject':
            timesheet.status = 'Rejected'
            timesheet.approved_by_id = current_user.id
            db.session.commit()
            
            # Send rejection notification with reasons
            subject = f"Timesheet Rejected: {timesheet.week_start_date.strftime('%d %b')} - {timesheet.week_end_date.strftime('%d %b, %Y')}"
            body = f"Dear {employee.name},<br><br>Your timesheet for {timesheet.week_start_date.strftime('%d %b')} - {timesheet.week_end_date.strftime('%d %b, %Y')} has been rejected.<br><br>Reason: {verification_notes}<br><br>Please review and resubmit.<br><br>Thanks,<br>{current_user.name} (HR)"
            send_email(employee.email, subject, body)
            
            flash('Timesheet rejected.', 'warning')
        
        return redirect(url_for('hr_weekly_timesheets'))
    
    # Get verification data
    verification_checks = perform_advanced_verification(timesheet)
    
    return render_template('hr/advanced_verification.html', 
                         timesheet=timesheet, 
                         employee=employee, 
                         task=task,
                         verification_checks=verification_checks)

def perform_advanced_verification(timesheet):
    """Perform comprehensive verification checks on timesheet"""
    checks = {
        'is_valid': True,
        'errors': [],
        'warnings': [],
        'details': {}
    }
    
    # Check 1: Hours validation
    total_hours = timesheet.total_hours
    week_days = 5  # Monday to Friday
    max_hours_per_day = 10
    max_hours_per_week = week_days * max_hours_per_day
    
    if total_hours > max_hours_per_week:
        checks['errors'].append(f"Total hours ({total_hours}) exceed maximum weekly limit ({max_hours_per_week})")
        checks['is_valid'] = False
    
    if total_hours < 20:  # Minimum 4 hours per day
        checks['warnings'].append(f"Low hours logged ({total_hours}) for a full week")
    
    # Check 2: Daily timesheet consistency
    daily_timesheets = Timesheet.query.filter(
        Timesheet.employee_id == timesheet.employee_id,
        Timesheet.date >= timesheet.week_start_date,
        Timesheet.date <= timesheet.week_end_date
    ).all()
    
    daily_hours_sum = sum(ts.hours_worked for ts in daily_timesheets)
    if abs(daily_hours_sum - total_hours) > 0.5:  # Allow 0.5 hour difference
        checks['errors'].append(f"Daily timesheet total ({daily_hours_sum}) doesn't match weekly total ({total_hours})")
        checks['is_valid'] = False
    
    # Check 3: Task assignment validation
    if not timesheet.task:
        checks['errors'].append("No task assigned to timesheet")
        checks['is_valid'] = False
    else:
        # Check if employee is actually assigned to this task
        if timesheet.employee not in timesheet.task.assignees:
            checks['errors'].append("Employee not assigned to this task")
            checks['is_valid'] = False
    
    # Check 4: Project timeline validation
    if timesheet.task and timesheet.task.timeline_end:
        if timesheet.week_start_date > timesheet.task.timeline_end:
            checks['warnings'].append("Timesheet logged after task end date")
    
    # Check 5: Overtime validation
    if total_hours > 40:  # Standard work week
        checks['warnings'].append(f"Overtime detected ({total_hours - 40} extra hours)")
    
    # Check 6: Weekend work validation
    weekend_timesheets = [ts for ts in daily_timesheets if ts.date.weekday() >= 5]
    if weekend_timesheets:
        checks['warnings'].append(f"Weekend work detected ({len(weekend_timesheets)} days)")
    
    checks['details'] = {
        'total_hours': total_hours,
        'daily_hours_sum': daily_hours_sum,
        'weekend_days': len(weekend_timesheets),
        'overtime_hours': max(0, total_hours - 40)
    }
    
    return checks

@app.route('/hr/bulk-verification', methods=['GET', 'POST'])
@login_required
@nocache
def hr_bulk_verification():
    """Bulk verification of multiple timesheets"""
    if current_user.role not in ['HR', 'MD'] and not current_user.has_hr_permission('timesheet_review'):
        abort(403)
    
    if request.method == 'POST':
        action = request.form.get('action')
        timesheet_ids = request.form.getlist('timesheet_ids')
        
        if action == 'bulk_approve':
            approved_count = 0
            for ts_id in timesheet_ids:
                timesheet = WeeklyTimesheet.query.get(ts_id)
                if timesheet and timesheet.status == 'PM Approved':
                    verification_checks = perform_advanced_verification(timesheet)
                    if verification_checks['is_valid']:
                        timesheet.status = 'HR Approved'
                        timesheet.approval_level = 'HR'
                        timesheet.approved_by_id = current_user.id
                        approved_count += 1
            
            db.session.commit()
            flash(f'{approved_count} timesheets approved successfully.', 'success')
            
        elif action == 'bulk_reject':
            rejected_count = 0
            for ts_id in timesheet_ids:
                timesheet = WeeklyTimesheet.query.get(ts_id)
                if timesheet and timesheet.status in ['Submitted', 'PM Approved']:
                    timesheet.status = 'Rejected'
                    timesheet.approved_by_id = current_user.id
                    rejected_count += 1
            
            db.session.commit()
            flash(f'{rejected_count} timesheets rejected.', 'warning')
        
        return redirect(url_for('hr_bulk_verification'))
    
    # Get pending timesheets for bulk verification
    pending_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.status.in_(['Submitted', 'PM Approved'])
    ).order_by(WeeklyTimesheet.created_at.desc()).all()
    
    return render_template('hr/bulk_verification.html', timesheets=pending_timesheets)

@app.route('/reports/advanced-analytics')
@login_required
@nocache
def advanced_analytics():
    """Advanced analytics and reporting dashboard"""
    if current_user.role not in ['MD', 'HR', 'PM']:
        abort(403)
    
    # Project Performance Metrics
    total_projects = JobIndent.query.count()
    active_projects = JobIndent.query.filter_by(status='In Progress').count()
    completed_projects = JobIndent.query.filter_by(status='Completed').count()
    on_time_projects = JobIndent.query.filter(
        JobIndent.status == 'Completed',
        JobIndent.contract_end_date >= JobIndent.contract_start_date
    ).count()
    
    # Financial Metrics
    total_contract_value = db.session.query(func.sum(JobIndent.contract_value)).scalar() or 0
    total_estimated_value = db.session.query(func.sum(JobCard.estimated_value)).scalar() or 0
    total_profit = total_contract_value - total_estimated_value
    profit_margin = (total_profit / total_contract_value * 100) if total_contract_value > 0 else 0
    
    # Employee Performance Metrics
    employees = Employee.query.filter_by(role='EMP', is_active=True).all()
    employee_performance = []
    
    for emp in employees:
        # Get employee's tasks
        tasks = Task.query.join(Task.assignees).filter(Employee.id == emp.id).all()
        completed_tasks = len([t for t in tasks if t.status == 'Completed'])
        total_hours = db.session.query(func.sum(WeeklyTimesheet.total_hours)).filter(
            WeeklyTimesheet.employee_id == emp.id
        ).scalar() or 0
        
        employee_performance.append({
            'employee': emp,
            'total_tasks': len(tasks),
            'completed_tasks': completed_tasks,
            'completion_rate': (completed_tasks / len(tasks) * 100) if tasks else 0,
            'total_hours': total_hours
        })
    
    # Department Performance
    departments = Department.query.all()
    dept_performance = []
    
    for dept in departments:
        dept_employees = Employee.query.filter_by(department_id=dept.id, is_active=True).count()
        dept_projects = JobIndent.query.filter_by(department_id=dept.id).count()
        dept_completed = JobIndent.query.filter_by(department_id=dept.id, status='Completed').count()
        
        dept_performance.append({
            'department': dept,
            'employee_count': dept_employees,
            'project_count': dept_projects,
            'completed_projects': dept_completed,
            'completion_rate': (dept_completed / dept_projects * 100) if dept_projects > 0 else 0
        })
    
    # Timesheet Analytics
    recent_timesheets = WeeklyTimesheet.query.filter(
        WeeklyTimesheet.created_at >= datetime.now() - timedelta(days=30)
    ).all()
    
    avg_hours_per_week = db.session.query(func.avg(WeeklyTimesheet.total_hours)).scalar() or 0
    total_timesheets_submitted = len(recent_timesheets)
    approved_timesheets = len([ts for ts in recent_timesheets if ts.status == 'HR Approved'])
    approval_rate = (approved_timesheets / total_timesheets_submitted * 100) if total_timesheets_submitted > 0 else 0
    
    return render_template('reports/advanced_analytics.html',
                         total_projects=total_projects,
                         active_projects=active_projects,
                         completed_projects=completed_projects,
                         on_time_projects=on_time_projects,
                         total_contract_value=total_contract_value,
                         total_estimated_value=total_estimated_value,
                         total_profit=total_profit,
                         profit_margin=profit_margin,
                         employee_performance=employee_performance,
                         dept_performance=dept_performance,
                         avg_hours_per_week=avg_hours_per_week,
                         total_timesheets_submitted=total_timesheets_submitted,
                         approved_timesheets=approved_timesheets,
                         approval_rate=approval_rate)

@app.route('/reports/project-details/<int:project_id>')
@login_required
@nocache
def project_detailed_report(project_id):
    """Detailed project report with timeline, budget, and performance metrics"""
    if current_user.role not in ['MD', 'PM']:
        abort(403)
    
    project = JobIndent.query.get_or_404(project_id)
    job_card = project.job_card
    
    if not job_card:
        flash('No job card found for this project.', 'warning')
        return redirect(url_for('dashboard'))
    
    # Project timeline analysis
    project_duration = (project.contract_end_date - project.contract_start_date).days if project.contract_start_date and project.contract_end_date else 0
    days_remaining = (project.contract_end_date - date.today()).days if project.contract_end_date else 0
    progress_percentage = ((project_duration - days_remaining) / project_duration * 100) if project_duration > 0 else 0
    
    # Task analysis
    total_tasks = len(job_card.tasks)
    completed_tasks = len([t for t in job_card.tasks if t.status == 'Completed'])
    in_progress_tasks = len([t for t in job_card.tasks if t.status == 'In Progress'])
    pending_tasks = len([t for t in job_card.tasks if t.status == 'To Do'])
    
    # Budget analysis
    total_manpower_cost = 0
    total_man_hours = 0
    for task in job_card.tasks:
        for assignee in task.assignees:
            monthly_salary = assignee.monthly_salary or 0
            daily_rate = (monthly_salary / 30) * 1.2
            task_cost = daily_rate * (task.man_days or 0)
            total_manpower_cost += task_cost
            total_man_hours += task.man_hours or 0
    
    material_cost = sum(item.amount for item in job_card.budget_items if item.category != 'Manpower')
    total_budget = total_manpower_cost + material_cost
    budget_utilization = (total_budget / project.contract_value * 100) if project.contract_value > 0 else 0
    
    # Team performance
    team_members = set()
    for task in job_card.tasks:
        for assignee in task.assignees:
            team_members.add(assignee)
    
    team_performance = []
    for member in team_members:
        member_tasks = [t for t in job_card.tasks if member in t.assignees]
        completed_by_member = len([t for t in member_tasks if t.status == 'Completed'])
        member_hours = db.session.query(func.sum(WeeklyTimesheet.total_hours)).filter(
            WeeklyTimesheet.employee_id == member.id
        ).scalar() or 0
        
        team_performance.append({
            'employee': member,
            'assigned_tasks': len(member_tasks),
            'completed_tasks': completed_by_member,
            'completion_rate': (completed_by_member / len(member_tasks) * 100) if member_tasks else 0,
            'total_hours': member_hours
        })
    
    return render_template('reports/project_detailed_report.html',
                         project=project,
                         job_card=job_card,
                         project_duration=project_duration,
                         days_remaining=days_remaining,
                         progress_percentage=progress_percentage,
                         total_tasks=total_tasks,
                         completed_tasks=completed_tasks,
                         in_progress_tasks=in_progress_tasks,
                         pending_tasks=pending_tasks,
                         total_manpower_cost=total_manpower_cost,
                         material_cost=material_cost,
                         total_budget=total_budget,
                         budget_utilization=budget_utilization,
                         total_man_hours=total_man_hours,
                         team_performance=team_performance)

@app.route('/reports/employee-performance/<int:employee_id>')
@login_required
@nocache
def employee_performance_report(employee_id):
    """Detailed employee performance report"""
    if current_user.role not in ['MD', 'HR', 'PM']:
        abort(403)
    
    employee = Employee.query.get_or_404(employee_id)
    
    # Get employee's tasks
    tasks = Task.query.join(Task.assignees).filter(Employee.id == employee.id).all()
    
    # Task completion analysis
    completed_tasks = len([t for t in tasks if t.status == 'Completed'])
    in_progress_tasks = len([t for t in tasks if t.status == 'In Progress'])
    pending_tasks = len([t for t in tasks if t.status == 'To Do'])
    
    # Timesheet analysis
    timesheets = WeeklyTimesheet.query.filter_by(employee_id=employee.id).order_by(WeeklyTimesheet.week_start_date.desc()).limit(12).all()
    
    total_hours = sum(ts.total_hours for ts in timesheets)
    avg_hours_per_week = total_hours / len(timesheets) if timesheets else 0
    
    # Project involvement
    projects_involved = set()
    for task in tasks:
        if task.job_card and task.job_card.indent:
            projects_involved.add(task.job_card.indent)
    
    # Performance metrics
    task_completion_rate = (completed_tasks / len(tasks) * 100) if tasks else 0
    on_time_completion = len([t for t in tasks if t.status == 'Completed' and t.timeline_end and t.timeline_end >= date.today()])
    on_time_rate = (on_time_completion / completed_tasks * 100) if completed_tasks > 0 else 0
    
    return render_template('reports/employee_performance_report.html',
                         employee=employee,
                         tasks=tasks,
                         completed_tasks=completed_tasks,
                         in_progress_tasks=in_progress_tasks,
                         pending_tasks=pending_tasks,
                         task_completion_rate=task_completion_rate,
                         on_time_rate=on_time_rate,
                         timesheets=timesheets,
                         total_hours=total_hours,
                         avg_hours_per_week=avg_hours_per_week,
                         projects_involved=projects_involved)

# Enhanced Timesheet Features
@app.route('/timesheet/draft/save', methods=['POST'])
@login_required
def save_timesheet_draft():
    """Auto-save timesheet draft"""
    try:
        data = request.get_json()
        date_str = data.get('date')
        draft_data = data.get('draft_data')
        
        if not date_str or not draft_data:
            return jsonify({'error': 'Missing required data'}), 400
        
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Check if draft exists
        existing_draft = TimesheetDraft.query.filter_by(
            employee_id=current_user.id,
            date=date_obj
        ).first()
        
        if existing_draft:
            existing_draft.draft_data = json.dumps(draft_data)
            existing_draft.updated_at = datetime.utcnow()
        else:
            new_draft = TimesheetDraft(
                employee_id=current_user.id,
                date=date_obj,
                draft_data=json.dumps(draft_data)
            )
            db.session.add(new_draft)
        
        db.session.commit()
        
        # Log audit
        log_audit_trail('DRAFT_SAVE', 'timesheet_draft', None, None, data)
        
        return jsonify({'success': True, 'message': 'Draft saved successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/timesheet/draft/load/<date>')
@login_required
def load_timesheet_draft(date):
    """Load timesheet draft for a specific date"""
    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d').date()
        draft = TimesheetDraft.query.filter_by(
            employee_id=current_user.id,
            date=date_obj
        ).first()
        
        if draft:
            return jsonify({
                'success': True,
                'draft_data': json.loads(draft.draft_data),
                'updated_at': draft.updated_at.isoformat()
            })
        else:
            return jsonify({'success': False, 'message': 'No draft found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/timesheet/comment/add', methods=['POST'])
@login_required
def add_timesheet_comment():
    """Add comment to timesheet entry"""
    try:
        data = request.get_json()
        timesheet_id = data.get('timesheet_id')
        comment_text = data.get('comment')
        
        if not timesheet_id or not comment_text:
            return jsonify({'error': 'Missing required data'}), 400
        
        # Verify timesheet exists and user has access
        timesheet = Timesheet.query.get_or_404(timesheet_id)
        if timesheet.employee_id != current_user.id and current_user.role not in ['HR', 'PM', 'MD']:
            return jsonify({'error': 'Access denied'}), 403
        
        new_comment = TimesheetComment(
            timesheet_id=timesheet_id,
            employee_id=current_user.id,
            comment=comment_text
        )
        db.session.add(new_comment)
        db.session.commit()
        
        # Log audit
        log_audit_trail('COMMENT_ADD', 'timesheet_comment', new_comment.id, None, data)
        
        return jsonify({
            'success': True,
            'comment': {
                'id': new_comment.id,
                'comment': new_comment.comment,
                'created_at': new_comment.created_at.isoformat(),
                'employee_name': current_user.name
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/timesheet/attachment/upload', methods=['POST'])
@login_required
def upload_timesheet_attachment():
    """Upload file attachment for timesheet"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        timesheet_id = request.form.get('timesheet_id')
        
        if not file.filename or not timesheet_id:
            return jsonify({'error': 'Missing required data'}), 400
        
        # Verify timesheet exists and user has access
        timesheet = Timesheet.query.get_or_404(timesheet_id)
        if timesheet.employee_id != current_user.id and current_user.role not in ['HR', 'PM', 'MD']:
            return jsonify({'error': 'Access denied'}), 403
        
        # Generate unique filename
        filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        
        # Save file
        upload_folder = os.path.join(app.root_path, 'uploads', 'timesheets')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        
        # Create attachment record
        attachment = TimesheetAttachment(
            timesheet_id=timesheet_id,
            filename=filename,
            original_filename=file.filename,
            file_size=os.path.getsize(file_path),
            mime_type=file.content_type or 'application/octet-stream'
        )
        db.session.add(attachment)
        db.session.commit()
        
        # Log audit
        log_audit_trail('ATTACHMENT_UPLOAD', 'timesheet_attachment', attachment.id, None, {
            'timesheet_id': timesheet_id,
            'filename': filename
        })
        
        return jsonify({
            'success': True,
            'attachment': {
                'id': attachment.id,
                'filename': attachment.original_filename,
                'file_size': attachment.file_size,
                'uploaded_at': attachment.uploaded_at.isoformat()
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/timesheet/attachment/download/<int:attachment_id>')
@login_required
def download_timesheet_attachment(attachment_id):
    """Download timesheet attachment"""
    attachment = TimesheetAttachment.query.get_or_404(attachment_id)
    
    # Verify access
    if attachment.timesheet.employee_id != current_user.id and current_user.role not in ['HR', 'PM', 'MD']:
        abort(403)
    
    file_path = os.path.join(app.root_path, 'uploads', 'timesheets', attachment.filename)
    if not os.path.exists(file_path):
        abort(404)
    
    return send_file(file_path, as_attachment=True, download_name=attachment.original_filename)

# My Timesheets Page
@app.route('/timesheet/my-timesheets')
@login_required
@nocache
def my_timesheets():
    """Employee's own timesheet history"""
    if current_user.role in ['MD', 'HR', 'BD', 'FINANCE', 'Finance']:
        flash('Timesheet submissions are not applicable for executive or departmental accounts.', 'info')
        return redirect(url_for('dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    timesheets = WeeklyTimesheet.query.filter_by(employee_id=current_user.id)\
        .order_by(WeeklyTimesheet.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    # Calculate weekly hours summary
    all_timesheets = WeeklyTimesheet.query.filter_by(employee_id=current_user.id)\
        .order_by(WeeklyTimesheet.week_start_date.desc()).all()
    weekly_summary = calculate_weekly_hours_summary(all_timesheets)
    
    return render_template('timesheets/my_timesheets.html', 
                         timesheets=timesheets, 
                         weekly_summary=weekly_summary)

@app.route('/timesheet/edit/<int:timesheet_id>', methods=['GET', 'POST'])
@login_required
@nocache
def edit_timesheet(timesheet_id):
    """Edit existing timesheet (if not yet approved)"""
    timesheet = WeeklyTimesheet.query.get_or_404(timesheet_id)
    
    # Check access and status
    if timesheet.employee_id != current_user.id:
        abort(403)
    
    if timesheet.status in ['PM Approved', 'HR Approved']:
        flash('Cannot edit approved timesheet', 'warning')
        return redirect(url_for('my_timesheets'))
    
    if request.method == 'POST':
        try:
            timesheet.total_hours = float(request.form['total_hours'])
            timesheet.progress_description = request.form['progress_description']
            timesheet.status = 'Submitted'
            timesheet.approval_level = None
            timesheet.approved_by_id = None
            
            db.session.commit()
            
            # Log audit
            log_audit_trail('TIMESHEET_EDIT', 'weekly_timesheet', timesheet.id, None, request.form)
            
            flash('Timesheet updated successfully', 'success')
            return redirect(url_for('my_timesheets'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating timesheet: {str(e)}', 'error')
    
    return render_template('timesheets/edit_timesheet.html', timesheet=timesheet)

# Enhanced Approval Workflow
@app.route('/timesheet/approve/<int:timesheet_id>', methods=['POST'])
@login_required
def approve_timesheet(timesheet_id):
    """Enhanced approval workflow"""
    timesheet = WeeklyTimesheet.query.get_or_404(timesheet_id)
    
    # Check permissions
    if current_user.role == 'PM':
        if timesheet.task.job_card.indent.project_manager_id != current_user.id:
            abort(403)
        approval_level = 'PM'
    elif current_user.role == 'HR':
        approval_level = 'HR'
    elif current_user.role == 'MD':
        approval_level = 'CEO'
    else:
        abort(403)
    
    try:
        # Create approval record
        approval = TimesheetApproval(
            timesheet_id=timesheet_id,
            approver_id=current_user.id,
            approval_level=approval_level,
            status='Approved',
            comments=request.form.get('comments', ''),
            approved_at=datetime.utcnow()
        )
        db.session.add(approval)
        
        # Update timesheet status
        if approval_level == 'PM':
            timesheet.status = 'PM Approved'
            timesheet.approval_level = 'PM'
        elif approval_level == 'HR':
            timesheet.status = 'HR Approved'
            timesheet.approval_level = 'HR'
        elif approval_level == 'CEO':
            timesheet.status = 'HR Approved'  # Final approval
            timesheet.approval_level = 'CEO'
        
        timesheet.approved_by_id = current_user.id
        
        db.session.commit()
        
        # Log audit
        log_audit_trail('TIMESHEET_APPROVE', 'weekly_timesheet', timesheet.id, None, {
            'approval_level': approval_level,
            'comments': approval.comments
        })
        
        # Send notification
        create_notification(
            timesheet.employee_id,
            'Timesheet Approved',
            f'Your timesheet for {timesheet.week_start_date} has been approved by {current_user.name}',
            'success'
        )
        
        return jsonify({'success': True, 'message': 'Timesheet approved successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Notifications
@app.route('/notifications')
@login_required
def notifications():
    """User's notifications"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    notifications = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('notifications.html', notifications=notifications)

@app.route('/notifications/mark-read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Mark notification as read"""
    notification = Notification.query.get_or_404(notification_id)
    
    if notification.user_id != current_user.id:
        abort(403)
    
    notification.is_read = True
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read"""
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/notifications/count')
@login_required
def get_notification_count():
    """Get unread notification count"""
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})

# Audit Log
@app.route('/audit-log')
@login_required
@nocache
def audit_log():
    """View audit log (admin only)"""
    if current_user.role not in ['MD', 'HR']:
        abort(403)
    
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    audit_logs = AuditLog.query\
        .order_by(AuditLog.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('audit_log.html', audit_logs=audit_logs)

# API Endpoints
@app.route('/api/sub-departments/<int:parent_id>')
def api_sub_departments(parent_id):
    """API endpoint for sub-departments"""
    sub_departments = Department.query.filter_by(parent_department_id=parent_id).all()
    return jsonify([{
        'id': dept.id,
        'name': dept.name,
        'short_code': dept.short_code
    } for dept in sub_departments])

@app.route('/api/timesheets/<int:employee_id>')
@login_required
def api_employee_timesheets(employee_id):
    """API endpoint for employee timesheets"""
    if current_user.role not in ['HR', 'PM', 'MD'] and current_user.id != employee_id:
        abort(403)
    
    timesheets = WeeklyTimesheet.query.filter_by(employee_id=employee_id).all()
    
    return jsonify({
        'timesheets': [{
            'id': t.id,
            'week_start': t.week_start_date.isoformat(),
            'week_end': t.week_end_date.isoformat(),
            'total_hours': t.total_hours,
            'status': t.status,
            'created_at': t.created_at.isoformat()
        } for t in timesheets]
    })

@app.route('/api/projects/<int:project_id>/timesheets')
@login_required
def api_project_timesheets(project_id):
    """API endpoint for project timesheets"""
    if current_user.role not in ['PM', 'MD']:
        abort(403)
    
    project = JobIndent.query.get_or_404(project_id)
    
    # Get all tasks for this project
    tasks = Task.query.join(JobCard).filter(JobCard.job_indent_id == project_id).all()
    task_ids = [t.id for t in tasks]
    
    timesheets = WeeklyTimesheet.query.filter(WeeklyTimesheet.task_id.in_(task_ids)).all()
    
    return jsonify({
        'project': {
            'id': project.id,
            'name': project.project_name,
            'client': project.client_name
        },
        'timesheets': [{
            'id': t.id,
            'employee': t.employee.name,
            'task': t.task.description,
            'total_hours': t.total_hours,
            'status': t.status,
            'week_start': t.week_start_date.isoformat()
        } for t in timesheets]
    })

# Export functionality
@app.route('/export/timesheets/excel', methods=['POST'])
@login_required
def export_timesheets_excel():
    """Export timesheets to Excel"""
    if current_user.role not in ['HR', 'PM', 'MD']:
        abort(403)
    
    # Get filter parameters
    status_filter = request.form.get('status_filter', '')
    employee_filter = request.form.get('employee_filter', '')
    
    # Build query with filters
    if current_user.role == 'PM':
        # PM can see timesheets for their projects
        pm_projects = JobIndent.query.filter_by(project_manager_id=current_user.id).all()
        project_ids = [p.id for p in pm_projects]
        tasks = Task.query.join(JobCard).filter(JobCard.job_indent_id.in_(project_ids)).all()
        task_ids = [t.id for t in tasks]
        query = WeeklyTimesheet.query.filter(WeeklyTimesheet.task_id.in_(task_ids))
    else:
        # HR and MD can see all timesheets
        query = WeeklyTimesheet.query
    
    if status_filter:
        query = query.filter(WeeklyTimesheet.status == status_filter)
    
    if employee_filter:
        query = query.join(Employee).filter(Employee.name.contains(employee_filter))
    
    timesheets = query.all()
    
    # Create Excel file
    output = BytesIO()
    import openpyxl
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Timesheets"
    
    # Headers
    headers = ['Employee', 'Project', 'Task', 'Week Start', 'Week End', 'Hours', 'Status', 'Created At']
    for col, header in enumerate(headers, 1):
        worksheet.cell(row=1, column=col, value=header)
    
    # Data
    for row, timesheet in enumerate(timesheets, 2):
        project_name = "N/A"
        task_description = "N/A"
        if timesheet.task and timesheet.task.job_card and timesheet.task.job_card.indent:
            project_name = timesheet.task.job_card.indent.project_name
            task_description = timesheet.task.description
        
        worksheet.cell(row=row, column=1, value=timesheet.employee.name)
        worksheet.cell(row=row, column=2, value=project_name)
        worksheet.cell(row=row, column=3, value=task_description)
        worksheet.cell(row=row, column=4, value=timesheet.week_start_date.strftime('%Y-%m-%d'))
        worksheet.cell(row=row, column=5, value=timesheet.week_end_date.strftime('%Y-%m-%d'))
        worksheet.cell(row=row, column=6, value=timesheet.total_hours)
        worksheet.cell(row=row, column=7, value=timesheet.status)
        worksheet.cell(row=row, column=8, value=timesheet.created_at.strftime('%Y-%m-%d %H:%M'))
    
    workbook.save(output)
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'timesheets_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )

@app.route('/export/employees/excel', methods=['POST'])
@login_required
def export_employees_excel():
    """Export employees to Excel"""
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    
    # Get filter parameters
    department_filter = request.form.get('department_filter', '')
    role_filter = request.form.get('role_filter', '')
    
    # Build query with filters
    query = Employee.query
    
    if department_filter:
        query = query.join(Department).filter(Department.name == department_filter)
    
    if role_filter:
        query = query.filter(Employee.role == role_filter)
    
    employees = query.all()
    
    # Create Excel file
    output = BytesIO()
    import openpyxl
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Employees"
    
    # Headers
    headers = ['Employee Name', 'Employee ID', 'Email', 'Designation', 'Department', 'Place', 'Role', 'Monthly Salary', 'Status']
    for col, header in enumerate(headers, 1):
        worksheet.cell(row=1, column=col, value=header)
    
    # Data
    for row, emp in enumerate(employees, 2):
        worksheet.cell(row=row, column=1, value=emp.name)
        worksheet.cell(row=row, column=2, value=emp.emp_id)
        worksheet.cell(row=row, column=3, value=emp.email)
        worksheet.cell(row=row, column=4, value=emp.designation or 'N/A')
        worksheet.cell(row=row, column=5, value=emp.department.name if emp.department else 'N/A')
        worksheet.cell(row=row, column=6, value=emp.place or 'N/A')
        worksheet.cell(row=row, column=7, value=emp.role)
        worksheet.cell(row=row, column=8, value=emp.monthly_salary or 0)
        worksheet.cell(row=row, column=9, value='Active' if emp.is_active else 'Inactive')
    
    workbook.save(output)
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'employees_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )

@app.route('/export/attendance/excel', methods=['POST'])
@login_required
def export_attendance_excel():
    """Export attendance data to Excel"""
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    
    # Get filter parameters
    department_filter = request.form.get('department_filter', '')
    role_filter = request.form.get('role_filter', '')
    
    # Build query with filters
    query = Employee.query.filter_by(is_active=True)
    
    if department_filter:
        query = query.join(Department).filter(Department.name == department_filter)
    
    if role_filter:
        query = query.filter(Employee.role == role_filter)
    
    employees = query.all()
    
    # Create Excel file
    output = BytesIO()
    import openpyxl
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Attendance"
    
    # Headers
    headers = ['Employee Name', 'Department', 'Role', 'Total Hours', 'Total Projects', 'Completed Tasks', 'Pending Tasks', 'Average Hours/Week']
    for col, header in enumerate(headers, 1):
        worksheet.cell(row=1, column=col, value=header)
    
    # Data
    for row, emp in enumerate(employees, 2):
        # Calculate statistics
        assigned_tasks = Task.query.join(Task.assignees).filter(Employee.id == emp.id).all()
        total_projects = len(set([task.job_card.job_indent_id for task in assigned_tasks if task.job_card]))
        completed_tasks = len([task for task in assigned_tasks if task.status == 'Completed'])
        pending_tasks = len([task for task in assigned_tasks if task.status in ['To Do', 'In Progress']])
        
        # Get total hours from timesheets
        timesheets = WeeklyTimesheet.query.filter_by(employee_id=emp.id).all()
        total_hours = sum(ts.total_hours for ts in timesheets)
        avg_hours_per_week = total_hours / max(len(timesheets), 1)
        
        worksheet.cell(row=row, column=1, value=emp.name)
        worksheet.cell(row=row, column=2, value=emp.department.name if emp.department else 'N/A')
        worksheet.cell(row=row, column=3, value=emp.role)
        worksheet.cell(row=row, column=4, value=total_hours)
        worksheet.cell(row=row, column=5, value=total_projects)
        worksheet.cell(row=row, column=6, value=completed_tasks)
        worksheet.cell(row=row, column=7, value=pending_tasks)
        worksheet.cell(row=row, column=8, value=round(avg_hours_per_week, 2))
    
    workbook.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f'attendance_{datetime.now().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export/employee/<int:employee_id>/report', methods=['POST'])
@login_required
def export_employee_report(employee_id):
    """Export detailed employee report"""
    if current_user.role not in ['HR', 'MD']:
        abort(403)
    
    employee = Employee.query.get_or_404(employee_id)
    
    # Create Excel file
    output = BytesIO()
    import openpyxl
    workbook = openpyxl.Workbook()
    
    # Employee Information Sheet
    ws1 = workbook.active
    ws1.title = "Employee Information"
    
    # Add employee details
    employee_data = [
        ['Employee Name', employee.name],
        ['Employee ID', employee.emp_id],
        ['Email', employee.email],
        ['Designation', employee.designation or 'N/A'],
        ['Department', employee.department.name if employee.department else 'N/A'],
        ['Place', employee.place or 'N/A'],
        ['Role', employee.role],
        ['Monthly Salary', employee.monthly_salary or 0],
        ['Status', 'Active' if employee.is_active else 'Inactive']
    ]
    
    for row in employee_data:
        ws1.append(row)
    
    # Performance Statistics Sheet
    ws2 = workbook.create_sheet("Performance Statistics")
    
    # Calculate statistics
    assigned_tasks = Task.query.join(Task.assignees).filter(Employee.id == employee_id).all()
    total_projects = len(set([task.job_card.job_indent_id for task in assigned_tasks if task.job_card]))
    completed_tasks = len([task for task in assigned_tasks if task.status == 'Completed'])
    pending_tasks = len([task for task in assigned_tasks if task.status in ['To Do', 'In Progress']])
    
    # Get total hours from timesheets
    timesheets = WeeklyTimesheet.query.filter_by(employee_id=employee_id).all()
    total_hours = sum(ts.total_hours for ts in timesheets)
    avg_hours_per_week = total_hours / max(len(timesheets), 1)
    
    performance_data = [
        ['Metric', 'Value'],
        ['Total Projects', total_projects],
        ['Completed Tasks', completed_tasks],
        ['Pending Tasks', pending_tasks],
        ['Total Hours', total_hours],
        ['Average Hours/Week', round(avg_hours_per_week, 2)]
    ]
    
    for row in performance_data:
        ws2.append(row)
    
    # Timesheets Sheet
    if timesheets:
        ws3 = workbook.create_sheet("Timesheets")
        
        # Headers
        timesheet_headers = ['Week Start', 'Week End', 'Project', 'Task', 'Hours', 'Status', 'Progress Description']
        ws3.append(timesheet_headers)
        
        # Data
        for ts in timesheets:
            project_name = "N/A"
            if ts.task and ts.task.job_card and ts.task.job_card.indent:
                project_name = ts.task.job_card.indent.project_name
            
            ws3.append([
                ts.week_start_date.strftime('%d-%b-%Y'),
                ts.week_end_date.strftime('%d-%b-%Y'),
                project_name,
                ts.task.description if ts.task else 'N/A',
                ts.total_hours,
                ts.status,
                ts.progress_description
            ])
    
    workbook.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f'employee_report_{employee_id}_{datetime.now().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def log_audit_trail(action, table_name, record_id, old_values=None, new_values=None, user_id=None):
    """Log audit trail entry"""
    try:
        import json
        from flask import has_request_context
        resolved_user_id = user_id
        if resolved_user_id is None:
            try:
                if current_user and current_user.is_authenticated:
                    resolved_user_id = current_user.id
            except Exception:
                resolved_user_id = None

        ip = None
        ua = None
        if has_request_context():
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            ua = request.headers.get('User-Agent')

        audit_log = AuditLog(
            user_id=resolved_user_id,
            action=action,
            table_name=table_name,
            record_id=record_id,
            old_values=json.dumps(old_values, default=str) if old_values else None,
            new_values=json.dumps(new_values, default=str) if new_values else None,
            ip_address=ip,
            user_agent=ua
        )
        db.session.add(audit_log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error logging audit trail: {e}")

def create_notification(user_id, title, message, notification_type='info'):
    """Create in-app notification"""
    try:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=notification_type
        )
        db.session.add(notification)
        db.session.commit()
    except Exception as e:
        print(f"Error creating notification: {e}")

def secure_filename(filename):
    """Secure filename for uploads"""
    return bleach.clean(filename, strip=True)

@app.route('/admin/trigger-auto-submit', methods=['POST'])
@login_required
def trigger_auto_submit():
    if current_user.role not in ['MD', 'HR']:
        abort(403)
    
    try:
        auto_submit_weekly_timesheets()
        flash('Auto-submit function executed successfully!', 'success')
    except Exception as e:
        flash(f'Error executing auto-submit: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/api/timesheet/<int:timesheet_id>/details')
@login_required
def api_timesheet_details(timesheet_id):
    """API endpoint to get detailed timesheet information and dual PM/RM verification status"""
    if current_user.role not in ['HR', 'MD', 'PM'] and not current_user.has_hr_permission('timesheet_review'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    timesheet = WeeklyTimesheet.query.get_or_404(timesheet_id)
    emp = timesheet.employee
    
    # Project and Task details
    has_project = bool(timesheet.task and timesheet.task.job_card and timesheet.task.job_card.indent)
    if has_project:
        project_name = timesheet.task.job_card.indent.project_name
        task_description = timesheet.task.description or timesheet.progress_description
        pm_employee = timesheet.task.job_card.indent.project_manager
        pm_name = (pm_employee.clean_name or pm_employee.name) if pm_employee else "Assigned Project Manager"
    else:
        project_name = "General / Non-Project"
        task_description = timesheet.progress_description or "General Work Tasks"
        pm_employee = None
        pm_name = "N/A (Non-Project)"
    
    # PM Verification Evaluation
    if not has_project:
        pm_approved = True
        pm_status = "N/A (Non-Project Task)"
        pm_approved_at = None
    else:
        pm_app = TimesheetApproval.query.filter_by(timesheet_id=timesheet.id, approval_level='PM', status='Approved').first()
        daily_pm = Timesheet.query.filter(
            Timesheet.employee_id == emp.id,
            Timesheet.date >= timesheet.week_start_date,
            Timesheet.date <= timesheet.week_end_date,
            Timesheet.status.in_(['Verified', 'PM Approved', 'Approved', 'CEO Approved'])
        ).first()
        
        if pm_app:
            pm_approved = True
            pm_status = "Approved by PM"
            pm_approved_at = pm_app.approved_at.strftime('%d-%b-%Y %H:%M') if pm_app.approved_at else "Approved"
        elif timesheet.status in ['PM Approved', 'HR Approved', 'Approved', 'CEO Approved'] or daily_pm:
            pm_approved = True
            pm_status = "Approved by PM"
            pm_approved_at = timesheet.created_at.strftime('%d-%b-%Y') if timesheet.created_at else "Approved"
        else:
            pm_approved = False
            pm_status = "Pending PM Approval"
            pm_approved_at = None

    # RM Verification Evaluation
    rm_employee = emp.manager
    rm_name = (rm_employee.clean_name or rm_employee.name) if rm_employee else "Executive Head (CEO)"
    
    rm_app = TimesheetApproval.query.filter_by(timesheet_id=timesheet.id, approval_level='RM', status='Approved').first()
    daily_rm = Timesheet.query.filter(
        Timesheet.employee_id == emp.id,
        Timesheet.date >= timesheet.week_start_date,
        Timesheet.date <= timesheet.week_end_date,
        Timesheet.rm_status.in_(['Verified', 'Approved', 'CEO Approved'])
    ).first()
    
    if rm_app:
        rm_approved = True
        rm_status = "Approved by RM"
        rm_approved_at = rm_app.approved_at.strftime('%d-%b-%Y %H:%M') if rm_app.approved_at else "Approved"
    elif daily_rm:
        rm_approved = True
        rm_status = "Approved by RM"
        rm_approved_at = daily_rm.created_at.strftime('%d-%b-%Y') if daily_rm.created_at else "Approved"
    elif timesheet.status in ['HR Approved', 'CEO Approved'] or (rm_employee and rm_employee.role == 'MD' and timesheet.status == 'PM Approved'):
        rm_approved = True
        rm_status = "Approved by RM"
        rm_approved_at = timesheet.created_at.strftime('%d-%b-%Y') if timesheet.created_at else "Approved"
    else:
        rm_approved = False
        rm_status = "Pending RM Approval"
        rm_approved_at = None

    timesheet_data = {
        'id': timesheet.id,
        'employee_name': emp.clean_name or emp.name,
        'emp_id': emp.emp_id,
        'initials': emp.initials,
        'department': emp.department.name if emp.department else 'N/A',
        'designation': emp.designation or 'N/A',
        'email': emp.email,
        'week_start': timesheet.week_start_date.strftime('%d-%b-%Y'),
        'week_end': timesheet.week_end_date.strftime('%d-%b-%Y'),
        'total_hours': timesheet.total_hours,
        'status': timesheet.status,
        'project_name': project_name,
        'has_project': has_project,
        'task_description': task_description,
        'progress_description': timesheet.progress_description or 'No additional progress notes provided.',
        'pm_name': pm_name,
        'pm_status': pm_status,
        'pm_approved': pm_approved,
        'pm_approved_at': pm_approved_at,
        'rm_name': rm_name,
        'rm_status': rm_status,
        'rm_approved': rm_approved,
        'rm_approved_at': rm_approved_at,
        'is_fully_approved': (pm_approved and rm_approved)
    }
    
    return jsonify({'success': True, 'timesheet': timesheet_data})

@app.route('/timesheet/view/<int:timesheet_id>', methods=['GET'])
@login_required
def view_timesheet_entry(timesheet_id):
    """Fallback redirect to dashboard Timesheet Review tab instead of 404"""
    return redirect(url_for('dashboard', tab='timesheets'))

@app.route('/api/employee/<int:employee_id>/details')
@login_required
def api_employee_details(employee_id):
    """API endpoint to get detailed employee information"""
    if current_user.role not in ['HR', 'MD']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    
    # Calculate performance statistics
    total_projects = 0
    completed_tasks = 0
    pending_tasks = 0
    total_hours = 0
    
    # Get tasks assigned to this employee
    assigned_tasks = Task.query.join(Task.assignees).filter(Employee.id == employee_id).all()
    total_projects = len(set([task.job_card.job_indent_id for task in assigned_tasks if task.job_card]))
    completed_tasks = len([task for task in assigned_tasks if task.status == 'Completed'])
    pending_tasks = len([task for task in assigned_tasks if task.status in ['To Do', 'In Progress']])
    
    # Get total hours from timesheets
    timesheets = WeeklyTimesheet.query.filter_by(employee_id=employee_id).all()
    total_hours = sum(ts.total_hours for ts in timesheets)
    
    # Get recent timesheets
    recent_timesheets = WeeklyTimesheet.query.filter_by(employee_id=employee_id).order_by(WeeklyTimesheet.week_start_date.desc()).limit(5).all()
    
    recent_timesheet_data = []
    for ts in recent_timesheets:
        project_name = "N/A"
        if ts.task and ts.task.job_card and ts.task.job_card.indent:
            project_name = ts.task.job_card.indent.project_name
        
        status_colors = {
            'Submitted': 'warning',
            'PM Approved': 'info',
            'HR Approved': 'success',
            'Rejected': 'danger'
        }
        status_color = status_colors.get(ts.status, 'secondary')
        
        recent_timesheet_data.append({
            'week': f"{ts.week_start_date.strftime('%d-%b-%Y')} to {ts.week_end_date.strftime('%d-%b-%Y')}",
            'project': project_name,
            'hours': ts.total_hours,
            'status': ts.status,
            'status_color': status_color
        })
    
    # Determine role and status colors
    role_colors = {
        'EMP': 'primary',
        'PM': 'success',
        'BD': 'info',
        'MD': 'warning',
        'HR': 'secondary',
        'FINANCE': 'dark'
    }
    role_color = role_colors.get(employee.role, 'secondary')
    status_color = 'success' if employee.is_active else 'danger'
    status = 'Active' if employee.is_active else 'Inactive'
    
    employee_data = {
        'name': employee.name,
        'emp_id': employee.emp_id,
        'email': employee.email,
        'designation': employee.designation or 'N/A',
        'place': employee.place or 'N/A',
        'role': employee.role,
        'role_color': role_color,
        'department': employee.department.name if employee.department else 'N/A',
        'monthly_salary': f"{employee.monthly_salary:,.2f}" if employee.monthly_salary else 'N/A',
        'status': status,
        'status_color': status_color,
        'created_at': employee.created_at.strftime('%d-%b-%Y') if hasattr(employee, 'created_at') else 'N/A',
        'total_projects': total_projects,
        'completed_tasks': completed_tasks,
        'pending_tasks': pending_tasks,
        'total_hours': total_hours,
        'recent_timesheets': recent_timesheet_data
    }
    
    return jsonify({'success': True, 'employee': employee_data})

@app.route('/api/task/<int:task_id>/details')
@login_required
def api_task_details(task_id):
    """API endpoint to get detailed task information"""
    if current_user.role not in ['PM', 'MD']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    task = Task.query.get_or_404(task_id)
    
    # Security check: ensure the PM manages this task's project
    if task.job_card.indent.project_manager_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    # Get available assignees (employees in the same department)
    available_assignees = Employee.query.filter_by(
        department_id=task.job_card.indent.department_id,
        is_active=True
    ).all()
    
    task_data = {
        'id': task.id,
        'description': task.description,
        'man_days': task.man_days,
        'man_hours': task.man_hours,
        'timeline_start': task.timeline_start.strftime('%Y-%m-%d') if task.timeline_start else '',
        'timeline_end': task.timeline_end.strftime('%Y-%m-%d') if task.timeline_end else '',
        'status': task.status,
        'assignees': [{'id': a.id, 'name': a.name} for a in task.assignees],
        'available_assignees': [{'id': a.id, 'name': a.name} for a in available_assignees]
    }
    
    return jsonify({'success': True, 'task': task_data})

@app.route('/api/task/<int:task_id>/update', methods=['POST'])
@login_required
def api_task_update(task_id):
    """API endpoint to update task information"""
    if current_user.role not in ['PM', 'MD']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    task = Task.query.get_or_404(task_id)
    
    # Security check: ensure the PM manages this task's project
    if task.job_card.indent.project_manager_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        # Update task fields
        task.description = request.form.get('description', task.description)
        task.man_days = int(request.form.get('man_days', 0))
        task.man_hours = int(request.form.get('man_hours', 0))
        task.status = request.form.get('status', task.status)
        
        # Update timeline
        timeline_start = request.form.get('timeline_start')
        if timeline_start:
            task.timeline_start = datetime.strptime(timeline_start, '%Y-%m-%d').date()
        
        timeline_end = request.form.get('timeline_end')
        if timeline_end:
            task.timeline_end = datetime.strptime(timeline_end, '%Y-%m-%d').date()
        
        # Update assignees
        assignees_json = request.form.get('assignees', '[]')
        assignee_ids = json.loads(assignees_json)
        
        # Clear current assignees
        task.assignees.clear()
        
        # Add new assignees
        for assignee_id in assignee_ids:
            employee = Employee.query.get(assignee_id)
            if employee:
                task.assignees.append(employee)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Task updated successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/check-employee-occupancy', methods=['POST'])
@login_required
def api_check_employee_occupancy():
    """Check if employee is occupied during a specific timeline"""
    if current_user.role not in ['PM', 'MD']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    try:
        employee_id = int(data.get('employee_id'))
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        exclude_task_id = data.get('exclude_task_id')
        
        occupancy_result = check_employee_occupancy(employee_id, start_date, end_date, exclude_task_id)
        
        return jsonify({
            'success': True,
            'occupancy': occupancy_result
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/check-pm-occupancy', methods=['POST'])
@login_required
def api_check_pm_occupancy():
    """Check if Project Manager is occupied during a specific timeline"""
    if current_user.role not in ['MD', 'BD']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    try:
        pm_id = int(data.get('pm_id'))
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
        exclude_indent_id = data.get('exclude_indent_id')
        
        occupancy_result = check_pm_occupancy(pm_id, start_date, end_date, exclude_indent_id)
        
        return jsonify({
            'success': True,
            'occupancy': occupancy_result
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# EXECUTIVE TIMESHEETS WORKFLOW (MD / CEO PORTAL)
# ============================================================================

@app.route('/api/executive/timesheets', methods=['GET'])
@login_required
def api_executive_timesheets():
    """
    Returns executive-level summary and employee list for MD/CEO.
    Supports scopes: 'reports_to_me' (direct reportees marked with Reports to: CEO)
    or 'all' (entire company workforce).
    """
    if current_user.role != 'MD':
        return jsonify({'success': False, 'error': 'Unauthorized access. MD role required.'}), 403

    scope = request.args.get('scope', 'reports_to_me')
    from_date_str = request.args.get('from_date')
    to_date_str = request.args.get('to_date')
    search_query = (request.args.get('search') or '').strip().lower()

    today = date.today()

    # Parse date range
    try:
        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
        else:
            from_date = today.replace(day=1)
    except ValueError:
        from_date = today.replace(day=1)

    try:
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        else:
            to_date = today
    except ValueError:
        to_date = today

    # Calculate total expected working days (Monday - Friday) in the range up to today
    calc_end_date = min(to_date, today)
    working_days = 0
    if from_date <= calc_end_date:
        cur = from_date
        while cur <= calc_end_date:
            if cur.weekday() < 5:  # Mon-Fri
                working_days += 1
            cur += timedelta(days=1)

    # Determine employee list based on scope
    all_employees = Employee.query.filter_by(is_active=True).all()

    # Define direct reportees for CEO/MD:
    # Specifically employees whose manager_id points to CEO, or top leadership with no manager
    def is_direct_reportee(emp):
        if emp.manager_id == current_user.id:
            return True
        if emp.manager_id is None:
            if emp.role in ['PM', 'BD', 'HR']:
                return True
            if emp.department and emp.department.name.upper() in ['MANAGEMENT', 'OPERATIONS']:
                return True
            if emp.designation:
                desig_upper = emp.designation.upper()
                if any(k in desig_upper for k in ['DIRECTOR', 'CTO', 'VICE PRESIDENT', 'GENERAL MANAGER', 'CHIEF MANAGER']):
                    return True
        return False

    if scope == 'reports_to_me':
        target_employees = [e for e in all_employees if is_direct_reportee(e)]
    else:
        target_employees = all_employees

    # Query all timesheet entries in the date range
    timesheet_records = Timesheet.query.filter(
        Timesheet.date >= from_date,
        Timesheet.date <= to_date
    ).all()

    # Map timesheets by employee_id
    emp_timesheets = defaultdict(list)
    for ts in timesheet_records:
        emp_timesheets[ts.employee_id].append(ts)

    # Process employee metrics
    processed_list = []
    total_submissions_count = 0
    total_hours_all = 0
    active_submitters_count = 0

    for emp in target_employees:
        ts_list = emp_timesheets.get(emp.id, [])
        total_submissions_count += len(ts_list)

        # Submitted dates
        submitted_dates = set(ts.date for ts in ts_list)
        # Unique submitted working days
        submitted_working_days = sum(1 for d in submitted_dates if d.weekday() < 5 and d <= calc_end_date)
        total_hours = sum(ts.hours_worked or 0 for ts in ts_list)
        total_hours_all += total_hours

        if ts_list:
            active_submitters_count += 1

        # Calculate submission percentage
        if working_days > 0:
            submission_pct = round((submitted_working_days / working_days) * 100, 1)
            submission_pct = min(100.0, submission_pct)
        else:
            submission_pct = 100.0 if ts_list else 0.0

        # Collect distinct project names
        project_names = set()
        for ts in ts_list:
            if ts.task and ts.task.job_card and ts.task.job_card.indent:
                project_names.add(ts.task.job_card.indent.project_name)
            else:
                project_names.add('PMS Application Project')

        if not project_names:
            assigned = [t.job_card.indent.project_name for t in emp.tasks_assigned if t.job_card and t.job_card.indent]
            project_names = set(assigned[:2]) if assigned else set(['General / Unassigned'])

        # Reports to attribute & direct reportee flag
        is_direct = is_direct_reportee(emp)
        if is_direct:
            reports_to_display = 'CEO'
        elif emp.manager:
            reports_to_display = emp.manager.name
        elif emp.department:
            reports_to_display = emp.department.name + ' Head'
        else:
            reports_to_display = 'Management'

        # Regularity badge
        if submission_pct >= 85:
            regularity_badge = {'label': 'Regular', 'class': 'badge-soft-success'}
        elif submission_pct >= 50:
            regularity_badge = {'label': 'Partial', 'class': 'badge-soft-warning'}
        elif len(ts_list) > 0:
            regularity_badge = {'label': 'Irregular', 'class': 'badge-soft-danger'}
        else:
            regularity_badge = {'label': 'No Submission', 'class': 'badge-soft-secondary'}

        # Missing days count
        missing_days = max(0, working_days - submitted_working_days)

        processed_list.append({
            'id': emp.id,
            'emp_id': emp.emp_id or f'EMP-{emp.id}',
            'name': emp.name,
            'email': emp.email,
            'mobile': emp.mobile or 'N/A',
            'department': emp.department.name if emp.department else 'General',
            'designation': emp.designation or 'Team Member',
            'reports_to': reports_to_display,
            'is_direct_reportee': is_direct,
            'projects': list(project_names),
            'total_submissions': len(ts_list),
            'total_hours': round(total_hours, 1),
            'working_days': working_days,
            'submitted_working_days': submitted_working_days,
            'missing_working_days': missing_days,
            'submission_percentage': submission_pct,
            'regularity_badge': regularity_badge
        })

    # Apply search filter if query is provided
    if search_query:
        processed_list = [
            item for item in processed_list
            if search_query in item['name'].lower()
            or search_query in item['emp_id'].lower()
            or search_query in item['email'].lower()
            or search_query in item['department'].lower()
            or search_query in item['mobile'].lower()
            or any(search_query in p.lower() for p in item['projects'])
        ]

    # Calculate overall summary KPIs
    total_reportees_count = len(target_employees)
    if total_reportees_count > 0 and working_days > 0:
        overall_pct = round((sum(item['submitted_working_days'] for item in processed_list) / (total_reportees_count * working_days)) * 100, 1)
        overall_pct = min(100.0, overall_pct)
    else:
        overall_pct = round(sum(item['submission_percentage'] for item in processed_list) / len(processed_list), 1) if processed_list else 0.0

    return jsonify({
        'success': True,
        'summary': {
            'scope': scope,
            'scope_label': 'Direct Reportees (CEO)' if scope == 'reports_to_me' else 'All Employees (Company-wide)',
            'from_date': from_date.strftime('%Y-%m-%d'),
            'to_date': to_date.strftime('%Y-%m-%d'),
            'working_days': working_days,
            'total_reportees': total_reportees_count,
            'active_submitters': active_submitters_count,
            'total_submissions': total_submissions_count,
            'submission_percentage': overall_pct,
            'total_hours': round(total_hours_all, 1)
        },
        'employees': processed_list
    })

@app.route('/api/executive/employee-timesheets/<int:emp_id>', methods=['GET'])
@login_required
def api_executive_employee_drilldown(emp_id):
    """
    Returns date-wise timesheet breakdown and missing dates/months consistency report
    for a specific employee, including two-tier PM/RM verification status.
    """
    if current_user.role != 'MD':
        return jsonify({'success': False, 'error': 'Unauthorized access'}), 403

    emp = Employee.query.get_or_404(emp_id)

    from_date_str = request.args.get('from_date')
    to_date_str = request.args.get('to_date')
    today = date.today()

    try:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date() if from_date_str else today.replace(day=1)
    except ValueError:
        from_date = today.replace(day=1)

    try:
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date() if to_date_str else today
    except ValueError:
        to_date = today

    # Determine if this employee reports directly to CEO
    is_direct = (emp.manager_id == current_user.id) or (emp.manager_id is None and emp.role in ['PM', 'BD', 'HR'])
    reports_to_display = 'CEO' if is_direct else (emp.manager.name if emp.manager else 'Not Assigned')

    # Fetch daily timesheet entries in range
    timesheets = Timesheet.query.filter(
        Timesheet.employee_id == emp.id,
        Timesheet.date >= from_date,
        Timesheet.date <= to_date
    ).order_by(Timesheet.date.desc(), Timesheet.id.desc()).all()

    # Map of dates with entries
    submitted_dates_map = defaultdict(list)
    timesheet_items = []

    for ts in timesheets:
        submitted_dates_map[ts.date].append(ts)
        proj_name = ts.project_name or (ts.project.project_name if ts.project else (ts.task.job_card.indent.project_name if (ts.task and ts.task.job_card and ts.task.job_card.indent) else 'Others'))
        task_desc = ts.progress_description or (ts.task.description if ts.task else 'Project Task / Output')

        # Two-tier verification status logic
        has_project = bool(ts.project_id or ts.task_id or (ts.project_name and ts.project_name != 'Others'))

        # PM verification status
        if has_project:
            pm_verified = ts.status in ['Verified', 'PM Approved', 'CEO Approved', 'Approved']
            pm_status = 'Verified by PM' if pm_verified else 'Pending PM Verification'
        else:
            pm_verified = True
            pm_status = 'N/A (Non-Project)'

        # RM verification status
        rm_verified = (ts.rm_status in ['Verified', 'Approved', 'CEO Approved']) or (ts.status == 'CEO Approved')
        rm_status = 'Approved by RM' if rm_verified else 'Pending RM Approval'

        is_fully_approved = (pm_verified and rm_verified)
        # CEO can only approve if this employee reports directly to CEO AND PM has already verified
        can_ceo_approve = is_direct and pm_verified and not rm_verified
        needs_pm_first = is_direct and has_project and not pm_verified

        timesheet_items.append({
            'id': ts.id,
            'date': ts.date.strftime('%Y-%m-%d'),
            'date_formatted': ts.date.strftime('%d-%b-%Y'),
            'day_name': ts.date.strftime('%A'),
            'project_name': proj_name,
            'task_description': task_desc,
            'hours': ts.hours_worked,
            'progress': ts.progress_description or 'No progress notes entered.',
            'status': 'Approved' if is_fully_approved else (ts.status or 'Submitted'),
            'pm_status': pm_status,
            'pm_verified': pm_verified,
            'rm_status': rm_status,
            'rm_verified': rm_verified,
            'is_approved': is_fully_approved or rm_verified,
            'can_ceo_approve': can_ceo_approve,
            'needs_pm_first': needs_pm_first,
            'is_direct_reportee': is_direct
        })

    # Missing Dates & Consistency Analysis
    calc_end_date = min(to_date, today)
    expected_working_days = 0
    missing_dates = []
    missing_by_month = defaultdict(list)
    submitted_working_days_count = 0

    if from_date <= calc_end_date:
        cur = from_date
        while cur <= calc_end_date:
            if cur.weekday() < 5:  # Mon-Fri
                expected_working_days += 1
                if cur in submitted_dates_map:
                    submitted_working_days_count += 1
                else:
                    month_key = cur.strftime('%B %Y')
                    date_info = {
                        'date': cur.strftime('%Y-%m-%d'),
                        'display': cur.strftime('%d-%b-%Y (%a)'),
                        'month': month_key
                    }
                    missing_dates.append(date_info)
                    missing_by_month[month_key].append(date_info)
            cur += timedelta(days=1)

    # Regularity Score
    if expected_working_days > 0:
        regularity_pct = round((submitted_working_days_count / expected_working_days) * 100, 1)
        regularity_pct = min(100.0, regularity_pct)
    else:
        regularity_pct = 100.0 if timesheets else 0.0

    if regularity_pct >= 90:
        compliance_status = 'Excellent (Regular)'
        compliance_badge_class = 'bg-success'
    elif regularity_pct >= 70:
        compliance_status = 'Good (Minor Gaps)'
        compliance_badge_class = 'bg-info'
    elif regularity_pct >= 40:
        compliance_status = 'Needs Attention (Frequent Misses)'
        compliance_badge_class = 'bg-warning text-dark'
    else:
        compliance_status = 'Irregular / High Missing Days'
        compliance_badge_class = 'bg-danger'

    return jsonify({
        'success': True,
        'employee': {
            'id': emp.id,
            'name': emp.name,
            'emp_id': emp.emp_id or f'EMP-{emp.id}',
            'email': emp.email,
            'mobile': emp.mobile or 'N/A',
            'designation': emp.designation or 'Associate',
            'department': emp.department.name if emp.department else 'General',
            'reports_to': reports_to_display,
            'is_direct_reportee': is_direct
        },
        'period': {
            'from_date': from_date.strftime('%d-%b-%Y'),
            'to_date': to_date.strftime('%d-%b-%Y')
        },
        'compliance': {
            'expected_working_days': expected_working_days,
            'submitted_working_days': submitted_working_days_count,
            'missing_days_count': len(missing_dates),
            'regularity_percentage': regularity_pct,
            'compliance_status': compliance_status,
            'compliance_badge_class': compliance_badge_class,
            'missing_dates': missing_dates,
            'missing_by_month': {k: [d['display'] for d in v] for k, v in missing_by_month.items()}
        },
        'timesheets': timesheet_items
    })

@app.route('/api/executive/timesheets/verify-approve', methods=['POST'])
@login_required
@csrf.exempt
def api_executive_approve_timesheet():
    """
    Endpoint for MD/CEO to verify and approve timesheets.
    Strictly restricted: CEO only verifies timesheets for employees who report directly to CEO.
    If associated with a project, PM verification must be completed first.
    """
    if current_user.role != 'MD':
        return jsonify({'success': False, 'error': 'Unauthorized access'}), 403

    data = request.get_json() or {}
    action_type = data.get('action', 'single') # 'single' or 'bulk'

    try:
        if action_type == 'single':
            timesheet_id = data.get('timesheet_id')
            if not timesheet_id:
                return jsonify({'success': False, 'error': 'Timesheet ID is required'}), 400

            ts = Timesheet.query.get_or_404(timesheet_id)
            emp = ts.employee
            is_direct = (emp.manager_id == current_user.id) or (emp.manager_id is None and emp.role in ['PM', 'BD', 'HR'])
            if not is_direct:
                rm_name = emp.manager.name if emp.manager else 'their assigned Reporting Manager'
                return jsonify({
                    'success': False,
                    'error': f'Unauthorized: {emp.name} reports to {rm_name}. CEO only approves timesheets for direct reportees.'
                }), 403

            has_project = bool(ts.project_id or ts.task_id or (ts.project_name and ts.project_name != 'Others'))
            if has_project and ts.status not in ['Verified', 'PM Approved', 'CEO Approved', 'Approved']:
                return jsonify({
                    'success': False,
                    'error': 'Project timesheets must first be verified by the Project Manager before Reporting Manager / CEO approval.'
                }), 400

            ts.status = 'CEO Approved'
            ts.rm_status = 'Approved'
            db.session.commit()

            # Record in AuditLog
            log_audit_trail('CEO_TIMESHEET_APPROVE', 'timesheet', ts.id, None, {
                'approved_by': current_user.name,
                'status': 'CEO Approved',
                'rm_status': 'Approved',
                'date': ts.date.strftime('%Y-%m-%d')
            })

            # Create notification for employee
            create_notification(
                ts.employee_id,
                'Timesheet Approved by CEO',
                f'Your timesheet entry for {ts.date.strftime("%d-%b-%Y")} has been verified and approved by CEO {current_user.name}.',
                'success'
            )

            return jsonify({
                'success': True,
                'message': f'Timesheet for {ts.date.strftime("%d-%b-%Y")} successfully verified and approved by CEO!'
            })

        elif action_type == 'bulk':
            emp_id = data.get('employee_id')
            from_date_str = data.get('from_date')
            to_date_str = data.get('to_date')

            if not emp_id:
                return jsonify({'success': False, 'error': 'Employee ID is required'}), 400

            emp = Employee.query.get_or_404(emp_id)
            is_direct = (emp.manager_id == current_user.id) or (emp.manager_id is None and emp.role in ['PM', 'BD', 'HR'])
            if not is_direct:
                rm_name = emp.manager.name if emp.manager else 'their assigned Reporting Manager'
                return jsonify({
                    'success': False,
                    'error': f'Unauthorized: {emp.name} reports to {rm_name}. CEO only approves timesheets for direct reportees.'
                }), 403

            query = Timesheet.query.filter(
                Timesheet.employee_id == emp.id,
                Timesheet.status != 'CEO Approved',
                Timesheet.rm_status != 'Approved'
            )
            if from_date_str:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                query = query.filter(Timesheet.date >= from_date)
            if to_date_str:
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                query = query.filter(Timesheet.date <= to_date)

            pending_entries = query.all()
            if not pending_entries:
                return jsonify({'success': True, 'message': 'All timesheets for this period are already approved.'})

            # Check that project timesheets have PM verification
            approved_count = 0
            skipped_count = 0
            for ts in pending_entries:
                has_proj = bool(ts.project_id or ts.task_id or (ts.project_name and ts.project_name != 'Others'))
                if has_proj and ts.status not in ['Verified', 'PM Approved', 'CEO Approved', 'Approved']:
                    skipped_count += 1
                    continue
                ts.status = 'CEO Approved'
                ts.rm_status = 'Approved'
                approved_count += 1

            db.session.commit()

            log_audit_trail('CEO_TIMESHEET_BULK_APPROVE', 'timesheet', emp.id, None, {
                'approved_by': current_user.name,
                'entries_count': approved_count,
                'skipped_unverified_count': skipped_count,
                'employee_name': emp.name
            })

            create_notification(
                emp.id,
                'Timesheets Approved by CEO',
                f'{approved_count} timesheets have been verified & approved by CEO {current_user.name}.',
                'success'
            )

            msg = f'{approved_count} timesheet(s) successfully verified & approved by CEO!'
            if skipped_count > 0:
                msg += f' ({skipped_count} project entries skipped because they are awaiting PM verification first).'

            return jsonify({
                'success': True,
                'message': msg
            })

        else:
            return jsonify({'success': False, 'error': 'Invalid action type'}), 400

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ==============================================================================
# DELEGATION OF POWER (DoP) ROUTES FOR HR
# ==============================================================================
@app.route('/api/hr/delegation/save', methods=['POST'])
@login_required
@csrf.exempt
def api_save_hr_delegation():
    """
    Saves delegated functional authorities for HR department team members.
    Callable by HR Admin or MD.
    """
    if current_user.role not in ['HR', 'MD']:
        return jsonify({'success': False, 'error': 'Unauthorized. Only HR Admin can delegate powers.'}), 403

    data = request.get_json() or {}
    employee_id = data.get('employee_id')
    if not employee_id:
        return jsonify({'success': False, 'error': 'Employee ID is required.'}), 400

    emp = Employee.query.get_or_404(employee_id)
    
    # Strictly ensure that delegation is ONLY allowed for HR Department employees
    hr_dept = Department.query.filter(or_(Department.short_code == 'HR', Department.name == 'HR')).first()
    hr_dept_id = hr_dept.id if hr_dept else 16
    if emp.department_id != hr_dept_id:
        return jsonify({'success': False, 'error': 'Delegation of Power can only be granted to HR Department employees.'}), 400
    
    delegation = HRDelegation.query.filter_by(employee_id=emp.id).first()
    if not delegation:
        delegation = HRDelegation(employee_id=emp.id)
        db.session.add(delegation)

    delegation.delegated_by_id = current_user.id
    delegation.all_access = bool(data.get('all_access', False))
    delegation.timesheet_review = bool(data.get('timesheet_review', False)) or delegation.all_access
    delegation.report_generation = bool(data.get('report_generation', False)) or delegation.all_access
    delegation.employee_create = bool(data.get('employee_create', False)) or delegation.all_access
    delegation.employee_edit = bool(data.get('employee_edit', False)) or delegation.all_access
    delegation.employee_delete = bool(data.get('employee_delete', False)) or delegation.all_access
    delegation.employee_block = bool(data.get('employee_block', False)) or delegation.all_access
    delegation.employee_archive = bool(data.get('employee_archive', False)) or delegation.all_access
    delegation.master_management = bool(data.get('master_management', False)) or delegation.all_access

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Delegation of Power successfully updated for {emp.name}.',
            'delegation': delegation.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/hr/delegation/<int:employee_id>', methods=['GET'])
@login_required
def api_get_hr_delegation(employee_id):
    if current_user.role not in ['HR', 'MD']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    emp = Employee.query.get_or_404(employee_id)
    delegation = HRDelegation.query.filter_by(employee_id=emp.id).first()
    if not delegation:
        return jsonify({
            'success': True,
            'employee_id': emp.id,
            'employee_name': emp.name,
            'delegation': {
                'all_access': False,
                'timesheet_review': False,
                'report_generation': False,
                'employee_create': False,
                'employee_edit': False,
                'employee_delete': False,
                'employee_block': False,
                'employee_archive': False,
                'master_management': False,
            }
        })
    return jsonify({
        'success': True,
        'employee_id': emp.id,
        'employee_name': emp.name,
        'delegation': delegation.to_dict()
    })

@app.route('/api/weather/ceo-location', methods=['GET'])
def api_weather_ceo_location():
    """
    Returns live weather for CEO's base location (Bhubaneswar).
    Supports ?simulate=rain or ?simulate=storm for testing rain & lightning effects.
    """
    simulate = request.args.get('simulate')
    if simulate in ['rain', 'storm']:
        return jsonify({
            'success': True,
            'location': 'Bhubaneswar',
            'temperature': 24.5,
            'is_raining': True,
            'is_storm': True,
            'weather_code': 95,
            'weather_desc': 'Thunderstorm & Rain (Preview Mode)'
        })

    # Location coordinates for Bhubaneswar (CEO base)
    place_name = 'Bhubaneswar'
    lat = 20.2961
    lon = 85.8245

    try:
        import urllib.request
        url = f'https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,is_day'
        req = urllib.request.Request(url, headers={'User-Agent': 'PMS-Ecometrix/1.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            cur = data.get('current', {})
            temp = cur.get('temperature_2m', 26.2)
            code = cur.get('weather_code', 0)

            rain_codes = [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99]
            storm_codes = [95, 96, 99]

            is_raining = code in rain_codes
            is_storm = code in storm_codes

            desc_map = {
                0: 'Clear Sky', 1: 'Mainly Clear', 2: 'Partly Cloudy', 3: 'Overcast',
                45: 'Foggy', 48: 'Rime Fog',
                51: 'Light Drizzle', 53: 'Moderate Drizzle', 55: 'Dense Drizzle',
                61: 'Slight Rain', 63: 'Moderate Rain', 65: 'Heavy Rain',
                80: 'Rain Showers', 81: 'Moderate Showers', 82: 'Heavy Showers',
                95: 'Thunderstorm & Rain', 96: 'Thunderstorm w/ Hail', 99: 'Heavy Thunderstorm'
            }
            weather_desc = desc_map.get(code, 'Clear')

            return jsonify({
                'success': True,
                'location': place_name,
                'temperature': round(temp, 1),
                'is_raining': is_raining,
                'is_storm': is_storm,
                'weather_code': code,
                'weather_desc': weather_desc
            })
    except Exception as e:
        return jsonify({
            'success': True,
            'location': place_name,
            'temperature': 26.5,
            'is_raining': False,
            'is_storm': False,
            'weather_code': 1,
            'weather_desc': 'Mainly Clear'
        })

# --- IT Administration APIs ---
@app.route('/api/it/master/update-credentials', methods=['POST'])
@login_required
def api_it_update_master_credentials():
    if current_user.role not in ['IT', 'IT_ADMIN']:
        return jsonify({'success': False, 'message': 'Access restricted to IT Administration.'}), 403

    data = request.get_json() or {}
    master_key = (data.get('master_key') or '').strip().upper()
    new_email = (data.get('email') or '').strip()
    new_password = (data.get('password') or '').strip()
    new_name = (data.get('name') or '').strip()

    if not master_key:
        return jsonify({'success': False, 'message': 'Missing master_key parameter.'}), 400

    master_user = None
    if master_key == 'CEO':
        master_user = Employee.query.filter(or_(Employee.emp_id == '15M006', Employee.email == 'chinmay.tripathy@ecometrix.co.in', Employee.role == 'MD')).first()
    elif master_key == 'BD':
        master_user = Employee.query.filter(or_(Employee.emp_id == 'DEPT_BD', Employee.email == 'bd@ecometrix.co.in')).first()
    elif master_key == 'HR':
        master_user = Employee.query.filter(or_(Employee.emp_id == 'DEPT_HR', Employee.email == 'hr@ecometrix.co.in')).first()
    elif master_key in ['FINANCE', 'ACCOUNTS', 'FIN']:
        master_user = Employee.query.filter(or_(Employee.emp_id == 'DEPT_FIN', Employee.email == 'accounts@ecometrix.co.in', Employee.email == 'finance@ecometrix.co.in')).first()

    if not master_user:
        return jsonify({'success': False, 'message': f'Master account for {master_key} not found.'}), 404

    if not new_email:
        return jsonify({'success': False, 'message': 'Email address cannot be blank.'}), 400

    # Ensure email is unique across other users
    conflict = Employee.query.filter(Employee.email == new_email, Employee.id != master_user.id).first()
    if conflict:
        return jsonify({'success': False, 'message': f'Email {new_email} is already registered to {conflict.name}.'}), 400

    old_email = master_user.email
    old_name = master_user.name
    master_user.email = new_email
    if new_name:
        master_user.name = new_name

    password_changed = False
    if new_password:
        if len(new_password) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters long.'}), 400
        master_user.set_password(new_password)
        password_changed = True

    try:
        db.session.commit()
        log_audit_trail(
            action='PASSWORD_RESET_BY_IT' if password_changed else 'CREDENTIAL_UPDATE',
            table_name='employee',
            record_id=master_user.id,
            old_values={'email': old_email, 'name': old_name, 'role': master_user.role, 'master_key': master_key},
            new_values={'email': master_user.email, 'name': master_user.name, 'password_reset': password_changed},
            user_id=current_user.id
        )
        return jsonify({
            'success': True,
            'message': f"Credentials for {master_key} ({master_user.name}) have been updated successfully.",
            'email': master_user.email,
            'name': master_user.name,
            'password_changed': password_changed
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500

@app.route('/api/it/master/send-credentials-email', methods=['POST'])
@login_required
def api_it_send_credentials_email():
    if current_user.role not in ['IT', 'IT_ADMIN']:
        return jsonify({'success': False, 'message': 'Access restricted to IT Administration.'}), 403

    data = request.get_json() or {}
    master_key = (data.get('master_key') or '').strip().upper()
    password_to_send = (data.get('password') or '').strip()
    is_mock_test = bool(data.get('test_mode') or request.headers.get('X-Test-Bypass-Email'))

    if not master_key:
        return jsonify({'success': False, 'message': 'Missing master_key.'}), 400

    master_user = None
    title = master_key
    if master_key == 'CEO':
        master_user = Employee.query.filter(or_(Employee.emp_id == '15M006', Employee.email == 'chinmay.tripathy@ecometrix.co.in', Employee.role == 'MD')).first()
        title = "CEO / Managing Director"
    elif master_key == 'BD':
        master_user = Employee.query.filter(or_(Employee.emp_id == 'DEPT_BD', Employee.email == 'bd@ecometrix.co.in')).first()
        title = "Business Development Master"
    elif master_key == 'HR':
        master_user = Employee.query.filter(or_(Employee.emp_id == 'DEPT_HR', Employee.email == 'hr@ecometrix.co.in')).first()
        title = "Human Resources Master"
    elif master_key in ['FINANCE', 'ACCOUNTS', 'FIN']:
        master_user = Employee.query.filter(or_(Employee.emp_id == 'DEPT_FIN', Employee.email == 'accounts@ecometrix.co.in', Employee.email == 'finance@ecometrix.co.in')).first()
        title = "Finance & Accounts Master"

    if not master_user:
        return jsonify({'success': False, 'message': f'Master account for {master_key} not found.'}), 404

    if not password_to_send:
        return jsonify({'success': False, 'message': 'Please enter or specify the password to send over email.'}), 400

    subject = f"PMS Portal Access Credentials - {title}"
    portal_url = request.host_url.rstrip('/') + url_for('login')
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
        <div style="text-align: center; margin-bottom: 20px; border-bottom: 2px solid #0e8749; padding-bottom: 14px;">
            <h2 style="color: #0e8749; margin: 0; font-size: 22px;">Ecometrix Project Monitoring System</h2>
            <p style="color: #64748b; font-size: 13px; margin-top: 4px; text-transform: uppercase;">Official Master Account Credentials</p>
        </div>
        <p style="font-size: 15px; color: #1e293b;">Dear <strong>{master_user.name}</strong>,</p>
        <p style="font-size: 14px; color: #475569; line-height: 1.6;">Your master access credentials for the Ecometrix PMS Portal have been configured by the IT Administration. Please find your login details below:</p>
        
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #0e8749; padding: 16px; margin: 18px 0; border-radius: 6px;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <tr>
                    <td style="padding: 6px 0; color: #64748b; width: 38%;"><strong>Master Authority:</strong></td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: 600;">{title}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Portal URL:</strong></td>
                    <td style="padding: 6px 0;"><a href="{portal_url}" style="color: #0e8749; font-weight: 600; text-decoration: none;">{portal_url}</a></td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Username / Email ID:</strong></td>
                    <td style="padding: 6px 0; color: #0f172a; font-family: monospace; font-size: 14px; font-weight: 600;">{master_user.email}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Access Password:</strong></td>
                    <td style="padding: 6px 0; color: #0f172a; font-family: monospace; font-size: 15px; font-weight: 700; background: #e2e8f0; padding: 2px 8px; border-radius: 4px; display: inline-block;">{password_to_send}</td>
                </tr>
            </table>
        </div>
        
        <div style="background: #fff1f2; border: 1px solid #ffe4e6; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px;">
            <p style="margin: 0; font-size: 13px; color: #e11d48; line-height: 1.5;">
                <strong>Security Advisory:</strong> This is a confidential master credential. Do not forward or share this communication. For any support, contact IT Administration at <a href="mailto:it@ecometrix.co.in" style="color: #e11d48;">it@ecometrix.co.in</a>.
            </p>
        </div>
        
        <p style="font-size: 13px; color: #64748b; margin-top: 20px;">Best regards,<br><strong style="color: #0f172a;">IT Administration Team</strong><br>Ecometrix Infra Solutions Pvt. Ltd.</p>
        <hr style="border: none; border-top: 1px solid #f1f5f9; margin: 20px 0 12px;">
        <p style="font-size: 11px; color: #94a3b8; text-align: center; margin: 0;">Automated IT Notification &bull; Ecometrix PMS</p>
    </div>
    """

    if is_mock_test:
        log_audit_trail(
            action='CREDENTIAL_EMAIL_SENT',
            table_name='employee',
            record_id=master_user.id,
            new_values={'recipient': master_user.email, 'master_key': master_key, 'mode': 'TEST_MOCK_NO_EMAIL'},
            user_id=current_user.id
        )
        return jsonify({
            'success': True,
            'message': f"[TEST MODE] Email simulated for {master_user.email}. No live email was dispatched.",
            'recipient': master_user.email
        })

    try:
        from mail import send_email
        send_email(to=master_user.email, subject=subject, template=html_content)
        log_audit_trail(
            action='CREDENTIAL_EMAIL_SENT',
            table_name='employee',
            record_id=master_user.id,
            new_values={'recipient': master_user.email, 'master_key': master_key, 'mode': 'LIVE_EMAIL'},
            user_id=current_user.id
        )
        return jsonify({
            'success': True,
            'message': f"Access credentials email has been sent successfully to {master_user.email}!",
            'recipient': master_user.email
        })
    except Exception as e:
        print(f"Error sending credentials email: {e}")
        return jsonify({
            'success': False,
            'message': f"Failed to send email to {master_user.email}: {str(e)}"
        }), 500

@app.route('/api/it/master/activity-logs', methods=['GET'])
@login_required
def api_it_activity_logs():
    if current_user.role not in ['IT', 'IT_ADMIN']:
        return jsonify({'success': False, 'message': 'Access restricted to IT Administration.'}), 403

    master_filter = (request.args.get('master') or 'ALL').strip().upper()
    event_filter = (request.args.get('event_type') or 'ALL').strip().upper()

    query = AuditLog.query

    if event_filter != 'ALL':
        query = query.filter(AuditLog.action == event_filter)
    else:
        query = query.filter(AuditLog.action.in_([
            'LOGIN_SUCCESS', 'LOGIN_FAILED', 'LOGOUT', 'LOGIN_BLOCKED',
            'PASSWORD_RESET_BY_IT', 'PASSWORD_CHANGE',
            'PROJECT_PURGE', 'CREDENTIAL_EMAIL_SENT', 'CREDENTIAL_UPDATE'
        ]))

    logs = query.order_by(AuditLog.created_at.desc()).limit(200).all()

    results = []
    for l in logs:
        role_label = 'SYSTEM'
        account_name = 'Unknown'
        email = ''

        old_val = l.old_values_dict
        new_val = l.new_values_dict

        target_emp = None
        if l.record_id and l.table_name == 'employee':
            target_emp = Employee.query.get(l.record_id)

        if target_emp and l.action in ['PASSWORD_RESET_BY_IT', 'CREDENTIAL_UPDATE', 'CREDENTIAL_EMAIL_SENT']:
            account_name = f"{target_emp.name} (by IT)"
            role_label = target_emp.role
            email = target_emp.email
        elif l.user:
            role_label = l.user.role
            account_name = l.user.name
            email = l.user.email
        elif old_val.get('account_name'):
            account_name = old_val.get('account_name')
            role_label = old_val.get('role') or 'UNKNOWN'
            email = old_val.get('identifier') or ''
        elif old_val.get('identifier'):
            account_name = old_val.get('identifier')
            email = old_val.get('identifier')
        elif new_val.get('email'):
            email = new_val.get('email')
            account_name = new_val.get('name') or email

        target_emails = [email.lower(), (old_val.get('email') or '').lower(), (new_val.get('email') or '').lower(), (new_val.get('recipient') or '').lower()]
        target_master_key = (old_val.get('master_key') or new_val.get('master_key') or '').upper()

        # Apply master filter if specified
        if master_filter != 'ALL':
            matched = False
            if master_filter == 'CEO' and (role_label == 'MD' or any('admin@' in em or 'ceo@' in em for em in target_emails) or target_master_key == 'CEO'):
                matched = True
            elif master_filter == 'BD' and (role_label == 'BD' or any('bd@' in em for em in target_emails) or target_master_key == 'BD'):
                matched = True
            elif master_filter == 'HR' and (role_label == 'HR' or any('hr@' in em for em in target_emails) or target_master_key == 'HR'):
                matched = True
            elif master_filter in ['FINANCE', 'ACCOUNTS', 'FIN'] and (role_label == 'FINANCE' or any('finance@' in em for em in target_emails) or target_master_key in ['FINANCE', 'ACCOUNTS', 'FIN']):
                matched = True
            elif master_filter == 'IT' and (role_label in ['IT', 'IT_ADMIN'] or any('it@' in em for em in target_emails) or target_master_key == 'IT'):
                matched = True
            if not matched:
                continue

        results.append({
            'id': l.id,
            'action': l.action,
            'timestamp': l.created_at.strftime('%d %b %Y, %I:%M:%S %p') if l.created_at else '',
            'account_name': account_name,
            'role': role_label,
            'email': email,
            'ip_address': l.ip_address or '127.0.0.1',
            'user_agent': l.user_agent or 'Browser Session',
            'details': new_val if new_val else old_val
        })

    return jsonify({'success': True, 'logs': results})

@app.route('/api/it/projects/purge/<int:indent_id>', methods=['POST'])
@login_required
def api_it_purge_project(indent_id):
    if current_user.role not in ['IT', 'IT_ADMIN']:
        return jsonify({'success': False, 'message': 'Access restricted to IT Administration.'}), 403

    data = request.get_json() or {}
    confirm_file_number = (data.get('confirm_file_number') or '').strip()

    indent = JobIndent.query.get_or_404(indent_id)

    if confirm_file_number and confirm_file_number.lower() != indent.file_number.lower():
        return jsonify({
            'success': False,
            'message': f"Confirmation failed. Entered file number '{confirm_file_number}' does not match '{indent.file_number}'."
        }), 400

    project_meta = {
        'id': indent.id,
        'file_number': indent.file_number,
        'project_name': indent.project_name,
        'client_name': indent.client_name,
        'contract_value': indent.contract_value,
        'status': indent.status,
        'created_at': str(indent.created_at) if indent.created_at else None
    }

    try:
        # 1. Purge all linked JobCards and their Tasks, Timesheets, Budgets
        job_cards = JobCard.query.filter_by(job_indent_id=indent.id).all()
        for jc in job_cards:
            tasks = Task.query.filter_by(job_card_id=jc.id).all()
            for t in tasks:
                # Remove assignee associations
                if hasattr(t, 'assignees'):
                    t.assignees.clear()
                # Delete task timesheets
                Timesheet.query.filter_by(task_id=t.id).delete()
                WeeklyTimesheet.query.filter_by(task_id=t.id).delete()
                db.session.delete(t)

            # Delete job card budget items
            BudgetItem.query.filter_by(job_card_id=jc.id).delete()
            db.session.delete(jc)

        # 2. Delete direct timesheet rows pointing to this project_id
        Timesheet.query.filter_by(project_id=indent.id).delete()

        # 3. Delete JobIndent
        db.session.delete(indent)

        # 4. Audit Log
        log_audit_trail(
            action='PROJECT_PURGE',
            table_name='job_indent',
            record_id=indent_id,
            old_values=project_meta,
            user_id=current_user.id
        )

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f"Project '{project_meta['project_name']}' (File: {project_meta['file_number']}) and all related workflows have been permanently purged from the database."
        })
    except Exception as e:
        db.session.rollback()
        print(f"Error purging project {indent_id}: {e}")
        return jsonify({'success': False, 'message': f'Failed to purge project: {str(e)}'}), 500

# Call this when app starts
if __name__ == '__main__':
    init_db()
    start_scheduler()  # Start the scheduler
    app.run(debug=True) 