import os
import io
import csv
import pytz
import requests
from datetime import datetime
from flask import Flask, send_from_directory, render_template, Response, request, redirect, url_for, jsonify
from dotenv import load_dotenv
from sqlalchemy import event

# Database and Model Imports
# Note: set_sqlite_pragma is the helper function we defined in models.py
from models import db, WhatsAppOrder, GroupLeader, Product, StockAlert, Customer, WhatsAppLead, set_sqlite_pragma
from sqlalchemy.orm.attributes import flag_modified

# Blueprint Imports
from contact.route import contact_bp 
from admin.routes import admin_bp 
from leader.route import leader_bp

# Load environment variables (.env file)
load_dotenv()

def create_app():
    app = Flask(__name__)

    # --- Database Configuration ---
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'leafplant.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-123')

    # Initialize Database
    db.init_app(app)

    # ==============================================================================
    # SQLITE CONFIGURATION REGISTRATION (FIXED)
    # ==============================================================================
    # This attaches the busy_timeout fix to the engine AFTER the app is created.
    # This prevents the "Working outside of application context" error.
    with app.app_context():
        event.listen(db.engine, "connect", set_sqlite_pragma)

    # Register Blueprints
    app.register_blueprint(contact_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(leader_bp)

    # ==============================================================================
    # 1. AUTOMATED STOCK ALERT TRIGGER (WHATSAPP BROADCAST)
    # ==============================================================================
    def send_restock_broadcast(product_name, new_qty):
        access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
        phone_id = os.getenv("PHONE_NUMBER_ID")
        
        if not access_token or not phone_id:
            print("⚠️ ALERT: WhatsApp credentials missing. Broadcast skipped.")
            return

        # Fetch only users waiting for this specific item who haven't been notified
        pending_alerts = StockAlert.query.filter_by(
            product_name=product_name, 
            is_notified=False
        ).all()
        
        if not pending_alerts:
            print(f"ℹ️ No pending alerts for {product_name}")
            return

        for alert in pending_alerts:
            message_body = (f"🌿 *FARM RESTOCK ALERT*\n\n"
                            f"Hi! Good news from the farm: *{product_name}* is back in stock! "
                            f"({new_qty} units available). 🚜\n\n"
                            f"Would you like to place an order?")
            
            url = f"https://graph.facebook.com/v24.0/{phone_id}/messages"
            headers = {"Authorization": f"Bearer {access_token}"}
            payload = {
                "messaging_product": "whatsapp",
                "to": alert.customer_phone,
                "type": "text",
                "text": {"body": message_body}
            }
            
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                if response.status_code == 200:
                    # Mark notified so they don't get duplicate messages
                    alert.is_notified = True 
                    alert.notified_at = datetime.now(pytz.timezone('Asia/Singapore'))
                    print(f"✅ Alert sent and DB marked for {alert.customer_phone}")
                else:
                    print(f"❌ WhatsApp API Error {response.status_code}: {response.text}")
            except Exception as e:
                print(f"❌ Broadcast Connection Error: {e}")
        
        db.session.commit() # Save all notified flags to leafplant.db

    # ==============================================================================
    # 2. PRODUCT UPDATE ROUTE (TRIGGERS BROADCAST)
    # ==============================================================================
    @app.route('/admin/update-stock-level', methods=['POST'])
    def update_stock_level():
        # 1. Capture data from form (matches names in admin.html)
        product_id = request.form.get('product_id') 
        new_qty = int(request.form.get('stock', 0))
        new_status = request.form.get('status') 
        
        product = Product.query.get_or_404(product_id)
        old_status = product.status # Record state before update
        
        # 2. Update object
        product.name = request.form.get('name')
        product.available_qty = new_qty
        product.price = float(request.form.get('price'))
        product.image_file = request.form.get('image_file')
        product.category = request.form.get('category')
        product.status = new_status

        # Force status to OOS if quantity is 0
        if product.available_qty <= 0:
            product.status = "Out of Stock"
        
        flag_modified(product, "status")
        db.session.commit()
        
        # 3. TRIGGER BROADCAST: If transitioned from OOS to In Stock
        if old_status == "Out of Stock" and product.status == "In Stock" and new_qty > 0:
            print(f"🚀 Triggering alerts for {product.name}...")
            send_restock_broadcast(product.name, new_qty)
                
        return redirect('/admin/dashboard#products')

    # ==============================================================================
    # 3. FARM REPORT ROUTE (CSV EXPORT)
    # ==============================================================================
    @app.route('/admin/generate-farm-report')
    def generate_farm_report():
        sgt = pytz.timezone('Asia/Singapore')
        today_str = datetime.now(sgt).strftime('%Y-%m-%d')
        
        report_data = db.session.query(
            GroupLeader.name,
            GroupLeader.phone,
            GroupLeader.area,
            WhatsAppOrder.product_name,
            db.func.sum(WhatsAppOrder.quantity)
        ).join(GroupLeader, WhatsAppOrder.leader_id == GroupLeader.id)\
        .filter(db.func.strftime('%Y-%m-%d', WhatsAppOrder.timestamp) == today_str)\
        .group_by(GroupLeader.name, GroupLeader.phone, GroupLeader.area, WhatsAppOrder.product_name).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Leader Name', 'Leader Phone', 'Area', 'Product', 'Total Quantity'])
        
        for row in report_data:
            writer.writerow(row)
        
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=farm_report_{today_str}.csv"}
        )

    # ==============================================================================
    # 4. LEADER DASHBOARD ROUTE
    # ==============================================================================
    @app.route('/leader')
    def leader():
        leader_data = GroupLeader.query.first() 
        if not leader_data:
            return "No leader found. Please configure leaders in the Admin Panel."

        orders = WhatsAppOrder.query.filter_by(leader_id=leader_data.id).all()
        neighbors = Customer.query.filter_by(leader_id=leader_data.id).all()
        pending_leads = WhatsAppLead.query.filter(WhatsAppLead.neighborhood.ilike(f"%{leader_data.area}%")).all()

        total_sales = sum(o.total_price for o in orders if o.order_status == 'Confirmed')
        pending_commission = total_sales * 0.111
        
        sgt = pytz.timezone('Asia/Singapore')
        today = datetime.now(sgt).date()
        today_orders_count = sum(1 for o in orders if o.timestamp.date() == today)

        return render_template('leader.html', 
                               leader=leader_data,
                               orders=orders,
                               neighbors=neighbors,
                               pending_leads=pending_leads,
                               total_sales=total_sales,
                               pending_commission=pending_commission,
                               today_orders_count=today_orders_count)

    # ==============================================================================
    # 5. GLOBAL PUBLIC ROUTES
    # ==============================================================================
    @app.route('/')
    def index(): return render_template('index.html')

    @app.route('/about')
    def about(): return render_template('about.html')

    @app.route('/product')
    def product():
        all_products = Product.query.all() 
        return render_template('product.html', products=all_products)

    @app.route('/article')
    def article(): return render_template('article.html')

    @app.route('/account')
    def account(): return render_template('account.html')

    @app.route('/favicon.ico')
    def favicon_root():
        return send_from_directory(os.path.join(app.root_path, 'static', 'image'), 'favicon.png')

    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001)