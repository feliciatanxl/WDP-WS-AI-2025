import os
import io
import csv
import pytz
import requests
from datetime import datetime
from flask import Flask, send_from_directory, render_template, Response, request, redirect, url_for

# Added missing imports for the leader route logic
from models import db, WhatsAppOrder, GroupLeader, Product, StockAlert, Customer, WhatsAppLead 
from contact.route import contact_bp 
from admin.routes import admin_bp 
from leader.route import leader_bp
from sqlalchemy.orm.attributes import flag_modified

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
    app.register_blueprint(leader_bp)

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
    # 2. PRODUCT UPDATE ROUTE
    # ==============================================================================
    @app.route('/admin/update-stock-level', methods=['POST'])
    def update_stock_level():
        product_id = request.form.get('product_id') 
        new_qty = int(request.form.get('stock', 0))
        
        product = Product.query.get(product_id)
        if product:
            old_qty = product.available_qty
            product.name = request.form.get('name')
            product.available_qty = new_qty
            product.price = float(request.form.get('price'))
            product.image_file = request.form.get('image_file')

            if new_qty <= 0:
                product.status = "Out of Stock"
            else:
                product.status = "In Stock"
            
            flag_modified(product, "status")
            db.session.commit()
            
            if old_qty == 0 and new_qty > 0:
                send_restock_broadcast(product.name, new_qty)
                
        return redirect('/admin/dashboard#products')

    # ==============================================================================
    # 3. FARM REPORT ROUTE
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
    # 4. LEADER ROUTE (FIXED POSITION & LOGIC)
    # ==============================================================================
    @app.route('/leader')
    def leader():
        # Fetch the first leader for testing synchronization
        leader_data = GroupLeader.query.first()
        
        if not leader_data:
            return "No leader found. Please add a leader in the Admin panel first."

        # Fetch related data
        orders = WhatsAppOrder.query.filter_by(leader_id=leader_data.id).all()
        neighbors = Customer.query.filter_by(leader_id=leader_data.id).all()
        
        # Pull leads based on neighborhood area match
        pending_leads = WhatsAppLead.query.filter(
            WhatsAppLead.neighborhood.ilike(f"%{leader_data.area}%")
        ).all()

        # Perform Calculations
        total_sales = sum(order.total_price for order in orders if order.order_status == 'Confirmed')
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
    # 5. GLOBAL ROUTES
    # ==============================================================================
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

    @app.route('/favicon.ico')
    def favicon_root():
        return send_from_directory(os.path.join(app.root_path, 'static', 'image'), 'favicon.png')

    # Create Tables
    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001)