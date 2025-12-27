from flask import Blueprint, render_template, redirect, url_for, request, session, flash
from models import db, ContactInquiry, Product
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified
from datetime import timedelta # Add this to your imports

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

# Adding products with automatic status detection
@admin_bp.route("/admin/products/add", methods=['POST'])
def add_product():
    name = request.form.get('name')
    stock = int(request.form.get('stock', 0))
    price = float(request.form.get('price', 0.0))
    image_file = request.form.get('image_file', 'default_product.jpg')

    # AUTO-STATUS: Forces correct string in DB based on initial stock
    status = "In Stock" if stock > 0 else "Out of Stock"

    try:
        new_product = Product(
            name=name,
            available_qty=stock,
            price=price,
            status=status,
            image_file=image_file
        )
        db.session.add(new_product)
        db.session.commit()
        print(f"✅ SUCCESS: Added {name} as {status} to DB")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Insert Error: {e}")

    return redirect(url_for('admin.dashboard') + '#products')

# Editing products with TWO-WAY forced database synchronization
@admin_bp.route("/admin/products/edit/<int:id>", methods=['POST'])
def edit_product(id):
    product = Product.query.get_or_404(id)
    
    try:
        new_qty = int(request.form.get('stock', 0))

        # Update core fields
        product.name = request.form.get('name')
        product.available_qty = new_qty
        product.price = float(request.form.get('price', 0.0))
        product.image_file = request.form.get('image_file')

        # --- THE TWO-WAY DB SYNC FIX ---
        if new_qty <= 0:
            # Force "Out of Stock" string in DB if qty is 0
            product.status = "Out of Stock"
        else:
            # Force "In Stock" string in DB if qty is 1 or more
            # This fixes items that were stuck as 'Out of Stock' despite having units.
            product.status = "In Stock"

        # Mark 'status' as modified to force SQLAlchemy to push text to leafplant.db
        flag_modified(product, "status")
        db.session.commit()
        print(f"✅ SUCCESS: DB updated ID {id} to {product.status}")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ UPDATE ERROR: {e}")
        
    return redirect(url_for('admin.dashboard') + '#products')

# Delete product
# Change this line in your app.py / admin_bp file
@admin_bp.route("/admin/products/delete/<int:id>", methods=['POST']) # Added methods=['POST']
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
    


# Inquiry Management
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