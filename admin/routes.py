from flask import Blueprint, render_template, redirect, url_for, request, session
from models import db, ContactInquiry
from sqlalchemy import func
import pyodbc  # 1. Import pyodbc

admin_bp = Blueprint('admin', __name__)

# 2. Add your SQL Server Connection Helper
def get_sql_server_connection():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=CHAR;"
        "DATABASE=ProductApp;"
        "Trusted_Connection=yes;"
    )

@admin_bp.route('/admin/dashboard')
def dashboard():
    # --- EXISTING INQUIRY LOGIC ---
    max_id_query = db.session.query(func.max(ContactInquiry.id)).scalar()
    current_real_max_id = int(max_id_query) if max_id_query else 0
    
    if 'visible_threshold_id' not in session:
        session['visible_threshold_id'] = current_real_max_id
        session['last_seen_id'] = current_real_max_id

    is_explicit_refresh = request.args.get('refresh') == 'true'

    if is_explicit_refresh:
        session['last_seen_id'] = int(session['visible_threshold_id'])
        session['visible_threshold_id'] = current_real_max_id
    
    visible_threshold = int(session['visible_threshold_id'])
    inquiries = ContactInquiry.query\
        .filter(ContactInquiry.id <= visible_threshold)\
        .order_by(ContactInquiry.created_at.desc())\
        .all()
        
    last_seen_id = int(session.get('last_seen_id', 0))

    # --- NEW PRODUCT LOGIC (SQL SERVER) ---
    products = []
    try:
        conn = get_sql_server_connection()
        cursor = conn.cursor()
        # Fetch products from your SQL Server table
        cursor.execute("SELECT Id, Name, Stock, Price FROM Products ORDER BY Id DESC")
        products = cursor.fetchall()
        conn.close()
        print(f"DEBUG: Successfully fetched {len(products)} products from SQL Server.")
    except Exception as e:
        print(f"DATABASE ERROR (SQL SERVER): {e}")

    # 3. Pass BOTH inquiries and products to the template
    return render_template('admin.html', 
                           inquiries=inquiries, 
                           products=products, 
                           last_seen_id=last_seen_id)
#delete for product management
@admin_bp.route("/admin/products/delete/<int:id>")
def delete_product(id):
    try:
        conn = get_sql_server_connection()
        cursor = conn.cursor()
        # Delete from SQL Server
        cursor.execute("DELETE FROM Products WHERE Id = ?", id)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Delete Error: {e}")
    
    # Redirect back to the dashboard and auto-focus the products tab
    return redirect(url_for('admin.dashboard') + '#products')
#adding of products
@admin_bp.route("/admin/products/add", methods=['POST'])
def add_product():
    name = request.form.get('name')
    stock = request.form.get('stock')
    price = request.form.get('price')

    try:
        conn = get_sql_server_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Products (Name, Stock, Price) VALUES (?, ?, ?)", 
                       (name, stock, price))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Insert Error: {e}")

    return redirect(url_for('admin.dashboard') + '#products')

@admin_bp.route('/admin/delete/<int:id>', methods=['POST'])
def delete_inquiry(id):
    inquiry = ContactInquiry.query.get_or_404(id)
    try:
        db.session.delete(inquiry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
    return redirect(url_for('admin.dashboard') + '#customer-service')