from flask import Flask, render_template, redirect, url_for, request, jsonify
from models import db, Product, ContactInquiry 
import os
from sqlalchemy.orm.attributes import flag_modified

app = Flask(__name__)

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
db_path = os.path.join(root_dir, 'leafplant.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# ==============================================================================
# 1. LIVE DATA API
# ==============================================================================
@app.route("/admin/api/products")
def get_products_api():
    products = Product.query.order_by(Product.id.desc()).all()
    # This JSON feed tells the JavaScript on your dashboard when numbers change
    return jsonify([{
        'id': p.id,
        'available_qty': p.available_qty,
        'status': p.status
    } for p in products])

# ==============================================================================
# 2. DASHBOARD VIEW
# ==============================================================================
@app.route("/admin/dashboard")
def admin_dashboard():
    products = Product.query.order_by(Product.id.desc()).all()
    inquiries = ContactInquiry.query.all()
    return render_template("admin.html", products=products, inquiries=inquiries)

# ==============================================================================
# 3. ADD PRODUCT (With Auto-Status)
# ==============================================================================
@app.route("/admin/products/add", methods=['POST'])
def add_product():
    name = request.form.get('name')
    stock = int(request.form.get('stock', 0))
    price = float(request.form.get('price', 0.0))
    image_file = request.form.get('image_file', 'default.png')
    category = request.form.get('category')

    # AUTO-STATUS LOGIC: Prevents "0 units | In Stock"
    status = "In Stock" if stock > 0 else "Out of Stock"

    new_product = Product(
        name=name,
        available_qty=stock,
        price=price,
        status=status,
        image_file=image_file,
        category=category
    )
    db.session.add(new_product)
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

# ==============================================================================
# 4. EDIT/UPDATE PRODUCT (Smart Sync Logic)
# ==============================================================================
# root/product_routes.py Logic check
@app.route('/admin/update-stock-level', methods=['POST'])
def update_stock_level():
    product_id = request.form.get('product_id')
    new_qty = int(request.form.get('stock', 0))
    manual_dropdown_status = request.form.get('status')
    
    product = db.session.get(Product, product_id)
    
    if product:
        product.available_qty = new_qty
        # Capture Category correctly
        product.category = request.form.get('category') 

        # If quantity is 0, safety first: always Out of Stock
        if new_qty <= 0:
            product.status = "Out of Stock"
        else:
            # Respect the Admin's manual choice if quantity is > 0
            product.status = manual_dropdown_status

        flag_modified(product, "status")
        db.session.commit()
    return redirect(url_for("admin_dashboard"))

# ==============================================================================
# 5. DELETE PRODUCT
# ==============================================================================
@app.route("/admin/products/delete/<int:id>")
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    with app.app_context():
        db.create_all() 
    app.run(debug=True, port=5001)