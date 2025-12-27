from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from datetime import datetime
import pytz

db = SQLAlchemy()

# Helper function for Singapore Time
def get_sg_time():
    return datetime.now(pytz.timezone('Asia/Singapore'))

# ==============================================================================
# SQLITE CONFIGURATION (Single File Mode)
# ==============================================================================
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    # Removed WAL mode. Using standard delete mode (standard .db file only)
    cursor.execute("PRAGMA journal_mode=DELETE")
    cursor.execute("PRAGMA synchronous=NORMAL")
    # CRITICAL: This prevents "Database is Locked" errors by waiting up to 30s
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

# ==============================================================================
# 1. WEBSITE DATA: Customer Service (Web Form)
# ==============================================================================
class ContactInquiry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Pending') 
    created_at = db.Column(db.DateTime, default=get_sg_time)

# ==============================================================================
# 2. WHATSAPP DATA: Sales & Lead Intake
# ==============================================================================
class WhatsAppOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    leader_id = db.Column(db.Integer, db.ForeignKey('group_leader.id'))
    
    customer_phone = db.Column(db.String(20), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    commission_earned = db.Column(db.Float, default=0.0)
    order_status = db.Column(db.String(50), default='New Order')
    timestamp = db.Column(db.DateTime, default=get_sg_time)

class WhatsAppLead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    extracted_name = db.Column(db.String(100)) 
    neighborhood = db.Column(db.String(100))     
    status = db.Column(db.String(50), default='Awaiting Assignment')
    created_at = db.Column(db.DateTime, default=get_sg_time)

# ==============================================================================
# 3. CORE BUSINESS DATA: Inventory & Logistics
# ==============================================================================
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    available_qty = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='In Stock')
    image_file = db.Column(db.String(100), nullable=False, default='default_product.jpg')
    category = db.Column(db.String(50), nullable=False, default='leafy')

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120))
    leader_id = db.Column(db.Integer, db.ForeignKey('group_leader.id'))
    orders = db.relationship('WhatsAppOrder', backref='buyer', lazy=True)

class GroupLeader(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=True) 
    area = db.Column(db.String(100)) 
    members = db.relationship('Customer', backref='leader', lazy=True)
    leader_orders = db.relationship('WhatsAppOrder', backref='handling_leader', lazy=True)

class StockAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_phone = db.Column(db.String(20), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=get_sg_time) 
    is_notified = db.Column(db.Boolean, default=False, nullable=False)
    notified_at = db.Column(db.DateTime, nullable=True)