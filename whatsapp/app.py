# ==============================================================================
# 0. PATH FIX (Adds root directory so it can find models.py)
# ==============================================================================
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ==============================================================================
# 1. Standard Imports
# ==============================================================================
import requests
import re
from datetime import datetime
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv
import pytz

# Import all models
from models import db, ContactInquiry, Product, Customer, WhatsAppOrder, WhatsAppLead

# ==============================================================================
# 2. Configuration & Security
# ==============================================================================
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env')) 

YOUR_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID") 
YOUR_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, '..', 'leafplant.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

processed_messages = set()
conversation_history = {} 

try:
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    client = None

# ==============================================================================
# 3. Database Helper Logic (CRUD & STOCK GUARD)
# ==============================================================================
def get_inventory_string():
    """Retrieves stock and explicitly marks items as SOLD OUT for the AI."""
    products = Product.query.all()
    if not products:
        return "No stock data available."
    
    output = "CURRENT FARM INVENTORY:\n"
    for p in products:
        status = "AVAILABLE" if p.available_qty > 0 else "SOLD OUT"
        output += f"- {p.name}: ${p.price} | {p.available_qty} left ({status})\n"
    return output

def deduct_stock_db(product_name, qty_to_deduct):
    product = Product.query.filter(Product.name.ilike(f"%{product_name}%")).first()
    if product and product.available_qty >= int(qty_to_deduct):
        product.available_qty -= int(qty_to_deduct)
        db.session.commit()
        return True
    return False

# ==============================================================================
# 4. New Prospect Handling (STRICT DATA COLLECTION & SG TIME)
# ==============================================================================
def handle_new_prospect(customer_number, customer_message, history):
    # Get current SG time to inform the AI context
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%Y-%m-%d %H:%M:%S")

    system_prompt = f"""
    You are 'Leaf Plant Onboarding AI'. Current SG Time: {sg_now}.
    
    YOUR GOAL: You MUST collect both the user's NAME and their NEIGHBORHOOD.
    
    STRICT RULES:
    1. If name is missing, ask for it. 
    2. If neighborhood is missing, ask for it (to find a local Group Leader).
    3. DO NOT take orders yet. Explain that the Group Leader protects their privacy.
    
    EXTRACTION (At bottom of reply):
    - Tag: [[NAME: Name]] (If provided)
    - Tag: [[ADDRESS: Neighborhood]] (If provided)
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        address_match = re.search(r"\[\[ADDRESS:\s*(.*?)\]\]", ai_reply)
        name_match = re.search(r"\[\[NAME:\s*(.*?)\]\]", ai_reply)
        
        if address_match or name_match:
            existing_lead = WhatsAppLead.query.filter_by(phone=customer_number).first()
            
            if not existing_lead:
                new_lead = WhatsAppLead(
                    phone=customer_number,
                    extracted_name=name_match.group(1).strip() if name_match else "New Prospect",
                    neighborhood=address_match.group(1).strip() if address_match else "Pending",
                    status='Awaiting Info'
                )
                db.session.add(new_lead)
            else:
                if address_match: existing_lead.neighborhood = address_match.group(1).strip()
                if name_match: existing_lead.extracted_name = name_match.group(1).strip()
                
                # Check if lead is now complete
                if existing_lead.neighborhood != "Pending" and existing_lead.extracted_name != "New Prospect":
                    existing_lead.status = 'Awaiting Assignment'
            
            db.session.commit()
            print(f"🔥 [SG TIME SYNC] Lead progress saved at {sg_now}")

        clean_reply = re.sub(r"\[\[ADDRESS:.*?\]\]", "", ai_reply)
        clean_reply = re.sub(r"\[\[NAME:.*?\]\]", "", clean_reply)
        return clean_reply.strip()

    except Exception as e:
        db.session.rollback()
        return "Welcome! May I have your name and neighborhood to link you with a local leader?"

# ==============================================================================
# 5. AI Sales Engine (FOR REGISTERED MEMBERS ONLY)
# ==============================================================================
def get_openai_response(customer_message, customer_number, customer_obj):
    if not client: return "AI Offline."
    
    if customer_number not in conversation_history: conversation_history[customer_number] = []
    history = conversation_history[customer_number][-4:]
    
    stock_list = get_inventory_string()
    leader = customer_obj.leader
    leader_name = leader.name if leader else "the farm"
    
    system_prompt = f"""
    You are 'Leaf Plant AI'. Customer: {customer_obj.name}. Leader: {leader_name}.
    - GREETING: Use their name.
    - STOCK GUARD: If an item is 'SOLD OUT', do NOT allow an order.
    - DISCOUNT: Apply 10% Member Discount.
    - INVENTORY:
    {stock_list}
    
    Tag order: [[DATA: Item | Qty | TotalPrice]].
    TotalPrice = (List Price * Qty) * 0.90
    """

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        if "[[DATA:" in ai_reply:
            match = re.search(r"\[\[DATA:\s*(.*?)\s*\]\]", ai_reply)
            if match:
                parts = [p.strip() for p in match.group(1).split('|')]
                if len(parts) == 3:
                    item, qty, cost = parts[0], parts[1], parts[2]
                    
                    if deduct_stock_db(item, qty):
                        commission = float(cost) * 0.111 
                        new_order = WhatsAppOrder(
                            customer_id=customer_obj.id,
                            leader_id=customer_obj.leader_id,
                            customer_phone=customer_number,
                            product_name=item,
                            quantity=int(qty),
                            total_price=float(cost),
                            commission_earned=commission,
                            order_status='Confirmed'
                        )
                        db.session.add(new_order)
                        db.session.commit()
                        
                        ai_reply += f"\n\n✅ *ORDER SECURED*\nItem: {item}\nQty: {qty}\nTotal: ${cost}\nYour Leader, {leader_name}, will manage delivery!"
                    else:
                        ai_reply = f"Sorry {customer_obj.name}, {item} just sold out!"

        return re.sub(r"\[\[DATA:.*?\]\]", "", ai_reply).strip()
    except Exception as e:
        db.session.rollback()
        print(f"❌ [SALES ERROR] {e}")
        return "Syncing with farm... please try again."

# ==============================================================================
# 6. Webhook Handling (THE GATEKEEPER)
# ==============================================================================
@app.route('/webhook', methods=['POST'])
def handle_message():
    data = request.get_json()
    try:
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        customer_number, msg_id, customer_message = msg['from'], msg['id'], msg['text']['body']
    except: return jsonify({"status": "error"}), 200

    if msg_id in processed_messages: return jsonify({"status": "duplicate"}), 200
    processed_messages.add(msg_id) 

    # AUTHENTICATION GATE
    customer = Customer.query.filter_by(phone=customer_number).first()
    
    if customer:
        # PATH A: REGISTERED MEMBER (Can Order)
        reply = get_openai_response(customer_message, customer_number, customer)
    else:
        # PATH B: UNKNOWN LEAD (Onboarding Only)
        history = conversation_history.get(customer_number, [])[-4:]
        reply = handle_new_prospect(customer_number, customer_message, history)

    if customer_number not in conversation_history: conversation_history[customer_number] = []
    conversation_history[customer_number].append({"role": "user", "content": customer_message})
    conversation_history[customer_number].append({"role": "assistant", "content": reply})

    requests.post(f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages", 
                 headers={"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}"},
                 json={"messaging_product": "whatsapp", "to": customer_number, "type": "text", "text": {"body": reply}})
        
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all() 
    app.run(port=5000, debug=True)