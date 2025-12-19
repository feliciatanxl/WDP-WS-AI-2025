import os
from flask import Flask
from models import db 
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
    app.register_blueprint(contact_bp)
    
    # 4. Create Tables
    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)