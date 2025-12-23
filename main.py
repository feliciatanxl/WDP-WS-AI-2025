import os
import io
import csv
import pytz
import requests  # Required for WhatsApp API calls
from datetime import datetime
from flask import Flask, send_from_directory, render_template, Response, request, redirect, url_for
from models import db, WhatsAppOrder, GroupLeader, Product, StockAlert 
from contact.route import contact_bp 
from admin.routes import admin_bp 
from sqlalchemy.orm.attributes import flag_modified # Required for DB persistence

def create_app():
    app = Flask(__name__)

    # Database Configuration
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'leafplant.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'dev-key-123'

    # Initialize Database
    db.init_app(app)

    # Register Blueprints
    app.register_blueprint(contact_bp)
    app.register_blueprint(admin_bp)

    # ==============================================================================
    # 1. AUTOMATED STOCK ALERT TRIGGER
    # ==============================================================================
    def send_restock_broadcast(product_name, new_qty):
        access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
        phone_id = os.getenv("PHONE_NUMBER_ID")
        
        pending_alerts = StockAlert.query.filter_by(
            product_name=product_name, 
            is_notified=False
        ).all()
        
        for alert in pending_alerts:
            message_body = f"Hi! Good news from the farm: back in stock: {product_name} ({new_qty} available). Would you like to place an order?"
            
            url = f"https://graph.facebook.com/v24.0/{phone_id}/messages"
            headers = {"Authorization": f"Bearer {access_token}"}
            payload = {
                "messaging_product": "whatsapp",
                "to": alert.customer_phone,
                "type": "text",
                "text": {"body": message_body}
            }
            
            try:
                response = requests.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    alert.is_notified = True 
            except Exception as e:
                print(f"Broadcast Error for {alert.customer_phone}: {e}")
        
        db.session.commit()

    # ==============================================================================
    # 2. PRODUCT UPDATE ROUTE (Two-Way Auto-Sync Fix)
    # ==============================================================================
    @app.route('/admin/update-stock-level', methods=['POST'])
    def update_stock_level():
        product_id = request.form.get('product_id') 
        new_qty = int(request.form.get('stock', 0))
        
        product = Product.query.get(product_id)
        if product:
            old_qty = product.available_qty
            
            # Update core fields
            product.name = request.form.get('name')
            product.available_qty = new_qty
            product.price = float(request.form.get('price'))
            product.image_file = request.form.get('image_file')

            # --- THE TWO-WAY DB SYNC FIX ---
            if new_qty <= 0:
                # Force "Out of Stock" string in DB if qty is 0
                product.status = "Out of Stock"
            else:
                # Force "In Stock" string in DB if qty is 1 or more
                # This fixes the issue of items staying "Out of Stock" when quantity > 0
                product.status = "In Stock"
            
            # Mark status as modified to force SQLAlchemy to push text to leafplant.db
            flag_modified(product, "status")
            db.session.commit()
            
            # 2. TRIGGER LOGIC: Only if it was 0 and now it is > 0
            if old_qty == 0 and new_qty > 0:
                send_restock_broadcast(product.name, new_qty)
                print(f"DEBUG: Restock broadcast triggered for {product.name}")
                
        return redirect('/admin/dashboard#products')

    # ==============================================================================
    # 3. FARM REPORT ROUTE (Keep as is)
    # ==============================================================================
    @app.route('/admin/generate-farm-report')
    def generate_farm_report():
        sgt = pytz.timezone('Asia/Singapore')
        today_str = datetime.now(sgt).strftime('%Y-%m-%d')
        
        report_data = db.session.query(
            GroupLeader.name,
            WhatsAppOrder.product_name,
            db.func.sum(WhatsAppOrder.quantity)
        ).join(GroupLeader, WhatsAppOrder.leader_id == GroupLeader.id)\
        .filter(db.func.strftime('%Y-%m-%d', WhatsAppOrder.timestamp) == today_str)\
        .group_by(GroupLeader.name, WhatsAppOrder.product_name).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Leader Name', 'Product', 'Total Quantity'])
        for row in report_data:
            writer.writerow(row)
        
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=farm_report_{today_str}.csv"}
        )

    # ==============================================================================
    # 4. Global Routes (Keep as is)
    # ==============================================================================
    @app.route('/favicon.ico')
    def favicon_root():
        return send_from_directory(
            os.path.join(app.root_path, 'static', 'image'),
            'favicon.png', 
            mimetype='image/png'
        )

    @app.route('/')
    def index(): return render_template('index.html')

    @app.route('/about')
    def about(): return render_template('about.html')

    @app.route('/product')
    def product(): return render_template('product.html')

    @app.route('/article')
    def article(): return render_template('article.html')

    @app.route('/account')
    def account(): return render_template('account.html')

    @app.route('/orders')
    def orders(): return render_template('orders.html')

    @app.route('/payment')
    def payment(): return render_template('payment.html')

    @app.route('/review')
    def review(): return render_template('review.html')

    @app.route('/leader')
    def leader():
        leader_data = GroupLeader.query.first() 
        if not leader_data:
            leader_data = {"name": "Test Leader", "area": "Pending Area", "members": []}
        return render_template('leader.html', leader=leader_data)

    # Create Tables
    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001)