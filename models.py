from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# 1. Website Contact Form (Logical separation)
class ContactInquiry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Pending') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# 2. WhatsApp Orders (Linked to Customer and Leader)
class WhatsAppOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # --- LINKS ---
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    leader_id = db.Column(db.Integer, db.ForeignKey('group_leader.id'))
    
    # --- DATA ---
    customer_phone = db.Column(db.String(20), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    commission_earned = db.Column(db.Float, default=0.0) # NEW: For leader payout
    order_status = db.Column(db.String(50), default='New Order')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# 3. Business Core Data
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    available_qty = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='In Stock')
    image_file = db.Column(db.String(100), nullable=False, default='default_product.jpg')

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120))
    leader_id = db.Column(db.Integer, db.ForeignKey('group_leader.id'))
    # Link back to orders
    orders = db.relationship('WhatsAppOrder', backref='buyer', lazy=True)

class GroupLeader(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    area = db.Column(db.String(100)) 
    members = db.relationship('Customer', backref='leader', lazy=True)
    # Link back to orders for commission tracking
    leader_orders = db.relationship('WhatsAppOrder', backref='handling_leader', lazy=True)
    
class WhatsAppLead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    extracted_name = db.Column(db.String(100)) # AI tries to catch their name
    neighborhood = db.Column(db.String(100))    # Extracted via handle_new_prospect
    status = db.Column(db.String(50), default='Awaiting Assignment') # e.g., 'Assigned', 'Blacklisted'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)