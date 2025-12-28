from flask import Blueprint, render_template, redirect, url_for, request, session, flash, jsonify
from models import db, ContactInquiry, Product, StockAlert  # Added StockAlert
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified
from datetime import datetime
import pytz

# Import the broadcast helper from your whatsapp app file
# Ensure the folder structure allows this import (whatspp.app)
try:
    from whatsapp.app import send_whatsapp_message
except ImportError:
    # Fallback if the folder is named differently or in a different path
    def send_whatsapp_message(to, msg): 
        print(f"Broadcast Helper not found. Would have sent to {to}: {msg}")
        return False

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/dashboard')
def dashboard():
    # --- INQUIRY LOGIC (SQLite) ---
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

    # --- PRODUCT LOGIC ---
    products = Product.query.order_by(Product.id.desc()).all()

    return render_template('admin.html', 
                            inquiries=inquiries, 
                            products=products, 
                            last_seen_id=last_seen_id)

# 1. LIVE SYNC API ROUTE
@admin_bp.route('/admin/api/products')
def get_products_api():
    products = Product.query.all()
    return jsonify([{
        'id': p.id,
        'available_qty': p.available_qty,
        'status': p.status
    } for p in products])

# 2. ADD PRODUCT
@admin_bp.route("/admin/products/add", methods=['POST'])
def add_product():
    name = request.form.get('name')
    stock = int(request.form.get('stock', 0))
    price = float(request.form.get('price', 0.0))
    category = request.form.get('category', 'leafy')
    image_file = request.form.get('image_file', 'default_product.jpg')

    status = "In Stock" if stock > 0 else "Out of Stock"

    try:
        new_product = Product(
            name=name,
            available_qty=stock,
            price=price,
            category=category,
            status=status,
            image_file=image_file
        )
        db.session.add(new_product)
        db.session.commit()
        print(f"✅ SUCCESS: Added {name} to DB")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Insert Error: {e}")

    return redirect(url_for('admin.dashboard') + '#products')

# 3. EDIT PRODUCT (With Automated Restock Broadcast)
@admin_bp.route("/admin/products/edit/<int:id>", methods=['POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    
    try:
        # 1. Capture old status to check for a transition to "In Stock"
        old_status = product.status
        
        new_qty = int(request.form.get('stock', 0))
        new_status = request.form.get('status')
        
        product.name = request.form.get('name')
        product.available_qty = new_qty
        product.price = float(request.form.get('price', 0.0))
        product.category = request.form.get('category')
        product.image_file = request.form.get('image_file')

        # 2. Smart Status Logic
        if new_qty <= 0:
            product.status = "Out of Stock"
        elif new_qty > 0 and old_status == "Out of Stock":
            # Auto-flip to In Stock if stock is added to an OOS item
            product.status = "In Stock"
        else:
            product.status = new_status

        # 3. BROADCAST LOGIC: Notify waiting customers if item is now back in stock
        if product.status == "In Stock" and old_status == "Out of Stock":
            # Find all pending alerts for this product
            pending_alerts = StockAlert.query.filter_by(
                product_name=product.name, 
                is_notified=False
            ).all()
            
            for alert in pending_alerts:
                restock_msg = (
                    f"🌿 *Good News from Leaf Plant!*\n\n"
                    f"*{product.name}* is now back in stock! We have {product.available_qty} units available.\n\n"
                    f"Reply to this message if you'd like to place an order now! ✨"
                )
                
                # Send the WhatsApp message
                if send_whatsapp_message(alert.customer_phone, restock_msg):
                    alert.is_notified = True
                    alert.notified_at = datetime.now(pytz.timezone('Asia/Singapore'))
            
            print(f"📢 BROADCAST: Notified {len(pending_alerts)} customers waiting for {product.name}")

        flag_modified(product, "status")
        db.session.commit()
        print(f"✅ DB Updated ID {id}: {product.name} is now {product.status}")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ UPDATE ERROR: {e}")
        
    return redirect(url_for('admin.dashboard') + '#products')

# 4. DELETE PRODUCT
@admin_bp.route("/admin/products/delete/<int:id>", methods=['POST'])
def delete_product(id):
    product = Product.query.get_or_404(id)
    try:
        db.session.delete(product)
        db.session.commit()
        print(f"✅ SUCCESS: Deleted ID {id}")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Delete Error: {e}")
    
    return redirect(url_for('admin.dashboard') + '#products')

# 5. INQUIRY MANAGEMENT
@admin_bp.route('/admin/delete/<int:id>', methods=['POST'])
def delete_inquiry(id):
    inquiry = ContactInquiry.query.get_or_404(id)
    try:
        db.session.delete(inquiry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error: {e}")
        
    return redirect(url_for('admin.dashboard') + '?refresh=true&tab=customer-service')

@admin_bp.route('/admin/update_status/<int:id>', methods=['POST'])
def update_status(id):
    inquiry = ContactInquiry.query.get_or_404(id)
    new_status = request.form.get('status')
    
    if new_status:
        inquiry.status = new_status
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error updating status: {e}")
            
    return redirect(url_for('admin.dashboard') + '?refresh=true&tab=customer-service')