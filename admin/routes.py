from flask import Blueprint, render_template, redirect, url_for, request, session, flash
from models import db, ContactInquiry, Product  # 1. Import Product model
from sqlalchemy import func

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

    # --- PRODUCT LOGIC (SQLite - Fixes 'price' error) ---
    # We query the Product model directly from leafplant.db
    products = Product.query.order_by(Product.id.desc()).all()

    return render_template('admin.html', 
                            inquiries=inquiries, 
                            products=products, 
                            last_seen_id=last_seen_id)

# Adding products to SQLite

@admin_bp.route("/admin/products/add", methods=['POST'])
def add_product():
    # Capture all 5 fields from the form
    name = request.form.get('name')
    stock = request.form.get('stock')
    price = request.form.get('price')
    status = request.form.get('status')
    image_file = request.form.get('image_file')

    try:
        new_product = Product(
            name=name,
            available_qty=int(stock),
            price=float(price),
            status=status,        # Save the status from the dropdown
            image_file=image_file # Save the image link
        )
        db.session.add(new_product)
        db.session.commit()
        print(f"SUCCESS: Added {name} to leafplant.db")
    except Exception as e:
        db.session.rollback()
        print(f"Insert Error: {e}")

    return redirect(url_for('admin.dashboard') + '#products')

#edit product
@admin_bp.route("/admin/products/edit/<int:id>", methods=['POST'])
def edit_product(id):
    # 1. Find the product in leafplant.db by its ID
    product = Product.query.get_or_404(id)
    
    try:
        # 2. Update the product object with data from the modal form
        product.name = request.form.get('name')
        product.available_qty = int(request.form.get('stock'))
        product.price = float(request.form.get('price'))
        product.status = request.form.get('status')
        product.image_file = request.form.get('image_file')

        # 3. Save (Commit) the changes to the database
        db.session.commit()
        print(f"SUCCESS: Updated Product ID {id}")
        
    except Exception as e:
        db.session.rollback()
        print(f"UPDATE ERROR: {e}")
        
    # 4. Redirect back to the dashboard product section
    return redirect(url_for('admin.dashboard') + '#products')
# Delete product from SQLite
@admin_bp.route("/admin/products/delete/<int:id>")
def delete_product(id):
    product = Product.query.get_or_404(id)
    try:
        db.session.delete(product)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Delete Error: {e}")
    
    return redirect(url_for('admin.dashboard') + '#products')

# Inquiry Management (SQLite)
@admin_bp.route('/admin/delete/<int:id>', methods=['POST'])
def delete_inquiry(id):
    inquiry = ContactInquiry.query.get_or_404(id)
    try:
        db.session.delete(inquiry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
        
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
            print(f"Error updating status: {e}")
            
    return redirect(url_for('admin.dashboard') + '?refresh=true&tab=customer-service')