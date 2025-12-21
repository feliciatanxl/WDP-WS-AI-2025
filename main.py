import os
from flask import Flask, send_from_directory, render_template
from models import db
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

    # 2. Register Blueprints
    app.register_blueprint(contact_bp)
    app.register_blueprint(admin_bp)

    # Favicon Route
    @app.route('/favicon.ico')
    def favicon_root():
        return send_from_directory(
            os.path.join(app.root_path, 'static', 'image'),
            'favicon.png', 
            mimetype='image/png'
        )

    # Global Routes 
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

    # Create Tables
    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001)