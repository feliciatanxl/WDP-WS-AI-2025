from models import db, Product
from whatsapp.app import app 

def seed_products():
    # Data following your specific model columns
    crops = [
        {"name": "Mao Bai", "price": 3.40},
        {"name": "Jiu Bai Cai", "price": 3.30},
        {"name": "Xiao Bai Cai", "price": 2.80},
        {"name": "Red Pak Choy", "price": 4.20},
        {"name": "Cos Lettuce", "price": 3.00},
        {"name": "Lollo Bionda Lettuce", "price": 3.20},
        {"name": "Chris Green Lettuce", "price": 2.80},
        {"name": "Mizuna", "price": 2.50}
    ]

    with app.app_context():
        # Optional: Clear existing products if you want a fresh start
        # db.session.query(Product).delete() 

        for crop in crops:
            existing = Product.query.filter_by(name=crop["name"]).first()
            if not existing:
                # Following your model exactly:
                new_item = Product(
                    name=crop["name"],
                    price=crop["price"],
                    available_qty=100,           # Matches your available_qty column
                    status='In Stock',           # Matches your default String(50)
                    image_file='default_product.jpg' # Matches your default String(100)
                )
                db.session.add(new_item)
        
        db.session.commit()
        print(f"✅ Successfully inserted {len(crops)} items into leafplant.db")

if __name__ == "__main__":
    seed_products()