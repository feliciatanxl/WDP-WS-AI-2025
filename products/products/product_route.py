from flask import Flask, render_template, redirect, url_for, request
from models import db, Product, ContactInquiry # Import your models and db

app = Flask(__name__)

# 1. Point to your SQLite file (leafplant.db)
import os
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'leafplant.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 2. Initialize the database
db.init_app(app)

@app.route("/admin/dashboard")
def admin_dashboard():
    # Fetch using SQLAlchemy (this fixes the 'price' error!)
    # These return objects so product.price and product.name will work in HTML
    products = Product.query.order_by(Product.id.desc()).all()
    inquiries = ContactInquiry.query.all()
    
    return render_template("admin.html", products=products, inquiries=inquiries)

@app.route("/admin/products/add", methods=['POST'])
def add_product():
    name = request.form.get('name')
    stock = request.form.get('stock')
    price = request.form.get('price')

    # Create the object using your model names (available_qty)
    new_product = Product(
        name=name,
        available_qty=int(stock),
        price=float(price)
    )
    db.session.add(new_product)
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/products/delete/<int:id>")
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    with app.app_context():
        db.create_all() # Ensures the leafplant.db file is created
    app.run(debug=True, port=5001)