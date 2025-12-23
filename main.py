import os
import io
import csv
import pytz
from datetime import datetime
from flask import Flask, send_from_directory, render_template, Response
from models import db, WhatsAppOrder, GroupLeader # Added models for the query
from contact.route import contact_bp 
from admin.routes import admin_bp 

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
    # 1. FARM REPORT ROUTE (Link to Dashboard Button)
    # ==============================================================================
    @app.route('/admin/generate-farm-report')
    def generate_farm_report():
        # Set Singapore Time context
        sgt = pytz.timezone('Asia/Singapore')
        today_str = datetime.now(sgt).strftime('%Y-%m-%d')
        
        # Query for today's confirmed orders
        # We group by Leader to protect individual buyer particulars
        report_data = db.session.query(
            GroupLeader.name,
            WhatsAppOrder.product_name,
            db.func.sum(WhatsAppOrder.quantity)
        ).join(GroupLeader, WhatsAppOrder.leader_id == GroupLeader.id)\
        .filter(db.func.strftime('%Y-%m-%d', WhatsAppOrder.timestamp) == today_str)\
        .group_by(GroupLeader.name, WhatsAppOrder.product_name).all()

        # Generate the CSV in-memory
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Leader Name', 'Product', 'Total Quantity'])
        
        for row in report_data:
            writer.writerow(row)
        
        # Send file to browser for ERP/Microsoft Dynamics sync
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=farm_report_{today_str}.csv"}
        )

    # ==============================================================================
    # 2. Global Routes
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