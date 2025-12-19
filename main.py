import os
from flask import Flask, send_from_directory, render_template
from models import db 
# Ensure contact/route.py has contact_bp defined
from contact.route import contact_bp 

def create_app():
    app = Flask(__name__)

    # 1. Database Configuration
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'customer_service.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'dev-key-123'

    # 2. Initialize Database
    db.init_app(app)

    # 3. Register Blueprints
    # This connects the routes defined in contact/route.py
    app.register_blueprint(contact_bp)

    # 4. Favicon Route
    @app.route('/favicon.ico')
    def favicon_root():
        return send_from_directory(
            os.path.join(app.root_path, 'static', 'image'),
            'favicon.png', 
            mimetype='image/png'
        )

    # 5. Global Routes (Linking the templates folder)
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/about')
    def about():
        return render_template('about/about.html')

    @app.route('/product')
    def product():
        return render_template('product/product.html')

    @app.route('/article')
    def article():
        return render_template('article/article.html')

    @app.route('/account')
    def account():
        return render_template('account/account.html')
        
    # 6. Create Tables
    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001)