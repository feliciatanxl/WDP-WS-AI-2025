from models import db, Product, GroupLeader, Customer
from whatsapp.app import app 

def seed_data():
    with app.app_context():
        # --- 1. SEED PRODUCTS ---
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

        for crop in crops:
            existing_p = Product.query.filter_by(name=crop["name"]).first()
            if not existing_p:
                new_item = Product(
                    name=crop["name"],
                    price=crop["price"],
                    available_qty=100,
                    status='In Stock',
                    image_file='default_product.jpg'
                )
                db.session.add(new_item)

        # --- 2. SEED TEST GROUP LEADER ---
        # We need a leader first so the customer has someone to belong to
        test_leader = GroupLeader.query.filter_by(name="Test Leader").first()
        if not test_leader:
            test_leader = GroupLeader(
                name="Test Leader",
                area="Singapore Central"
            )
            db.session.add(test_leader)
            db.session.commit() # Commit here so we get the ID for the leader

        # --- 3. SEED YOURSELF AS CUSTOMER ---
        # IMPORTANT: Use the exact phone number you use for WhatsApp (with country code)
        your_phone = "65XXXXXXXX" # <-- CHANGE THIS to your WhatsApp number
        your_name = "Admin Tester"

        existing_c = Customer.query.filter_by(phone=your_phone).first()
        if not existing_c:
            new_customer = Customer(
                name=your_name,
                phone=your_phone,
                email="test@example.com",
                leader_id=test_leader.id  # Links you to the leader
            )
            db.session.add(new_customer)
            print(f"👤 Added {your_name} as a registered customer.")
        else:
            print(f"ℹ️ {your_name} already exists in the database.")

        db.session.commit()
        print("✅ Database seeding complete.")

if __name__ == "__main__":
    seed_data()