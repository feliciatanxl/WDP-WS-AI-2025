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
from models import db, ContactInquiry, Product, Customer, WhatsAppOrder, WhatsAppLead, StockAlert

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
# 5. AI Sales Engine (PROACTIVE & MULTI-LANGUAGE)
# ==============================================================================
def get_openai_response(customer_message, customer_number, customer_obj):
    if not client: return "AI Offline."
    
    stock_list = get_inventory_string()
    leader_name = customer_obj.leader.name if customer_obj.leader else "your local leader"
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%A, %d %B %Y")

    # IMPROVED SYSTEM PROMPT: Fixes Language Drift and Context Loss
    system_prompt = f"""
    You are 'Farm Sales AI'. Today is {sg_now}. 
    Customer: {customer_obj.name}. Assigned Leader: {leader_name}.
    
    STRICT BUSINESS RULES:
    1. LANGUAGE CONSISTENCY: Respond ONLY in English or the customer's last used language. 
       NEVER switch to French or other languages randomly.
    
    2. CONTEXT AWARENESS (RESTOCK ALERTS): 
       - If the conversation history shows a "Back in Stock" notification was just sent,
         assume the user's "Yes" refers to that specific product (e.g., Mizuna).
       - Immediately ask: "Great! How many boxes of [Product Name] would you like?"

    3. PRODUCT NAME PERSISTENCE: 
       - NEVER use generic terms like "the chosen item" or "the product." 
       - Always use the specific name (e.g., "Mizuna", "Xiao Bai Cai").

    4. PRIVACY: Particulars stay with {leader_name} and are not shared with the farm.
    5. INVENTORY & PRICING: {stock_list}. Apply 10% Member Discount.
    
    6. DOUBLE CONFIRMATION FLOW:
       - STEP 1: Calculate total (Member Price) and ASK for confirmation.
         DO NOT show the math formula. Just state: "That will be $11.25 for 5 boxes of Mizuna."
       - STEP 2: ONLY IF they say "Yes", provide the internal tag [[DATA: Item Name | Quantity | MemberTotalPrice]].
    """

    # Maintain History (Last 5 messages for context memory)
    if customer_number not in conversation_history: conversation_history[customer_number] = []
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[customer_number][-5:])
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        # --- STOCK ALERT TRACKING ---
        if "sold out" in ai_reply.lower() or "alert" in ai_reply.lower():
            for p in Product.query.all():
                if p.name.lower() in customer_message.lower():
                    new_alert = StockAlert(customer_phone=customer_number, product_name=p.name)
                    db.session.add(new_alert)
                    db.session.commit()

        # --- ORDER PROCESSING (Wait for "Yes" Confirmation) ---
        data_match = re.search(r"\[\[DATA:\s*(.*?)\s*\]\]", ai_reply)
        if data_match:
            raw_data = data_match.group(1)
            parts = [p.strip() for p in raw_data.split('|')]
            if len(parts) == 3:
                item_name, qty_str, price_str = parts[0], parts[1], parts[2]
                qty = int(re.sub(r'[^\d]', '', qty_str))
                total_cost = float(re.sub(r'[^\d.]', '', price_str))
                
                if deduct_stock_db(item_name, qty):
                    commission = total_cost * 0.111 
                    new_order = WhatsAppOrder(
                        customer_id=customer_obj.id, leader_id=customer_obj.leader_id,
                        customer_phone=customer_number, product_name=item_name,
                        quantity=qty, total_price=total_cost,
                        commission_earned=commission, order_status='Confirmed'
                    )
                    db.session.add(new_order)
                    db.session.commit()
                    
                    clean_reply = re.sub(r"\[\[DATA:.*?\]\]", "", ai_reply).strip()
                    return f"{clean_reply}\n\n✅ *ORDER SECURED*\n{qty}x {item_name} confirmed! {leader_name} will manage your delivery."

        return re.sub(r"\[\[DATA:.*?\]\]", "", ai_reply).strip()

    except Exception as e:
        db.session.rollback()
        print(f"DEBUG ERROR: {e}") 
        return "I'm having a bit of trouble connecting to the farm. Please try again in a moment!"
    
# ==============================================================================
# 6. Webhook Handling (THE GATEKEEPER)
# ==============================================================================
@app.route('/webhook', methods=['POST'])
def handle_message():
    data = request.get_json()
    try:
        # 1. Extract message details
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        customer_number, msg_id, customer_message = msg['from'], msg['id'], msg['text']['body']
        
        # 2. Duplicate Check: This stops the bot from replying twice to the same ID
        if msg_id in processed_messages: 
            return jsonify({"status": "duplicate"}), 200
        processed_messages.add(msg_id) 

        # 3. Authentication & Response Generation
        customer = Customer.query.filter_by(phone=customer_number).first()
        if customer:
            reply = get_openai_response(customer_message, customer_number, customer)
        else:
            history = conversation_history.get(customer_number, [])[-4:]
            reply = handle_new_prospect(customer_number, customer_message, history)

        # 4. Save History
        if customer_number not in conversation_history: conversation_history[customer_number] = []
        conversation_history[customer_number].append({"role": "user", "content": customer_message})
        conversation_history[customer_number].append({"role": "assistant", "content": reply})

        # 5. Send Response back to WhatsApp
        requests.post(f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages", 
                     headers={"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}"},
                     json={"messaging_product": "whatsapp", "to": customer_number, "type": "text", "text": {"body": reply}})
        
        # 6. IMMEDIATELY tell Meta to stop retrying
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"WEBHOOK ERROR: {e}")
        # Even on error, return 200 so Meta stops retrying the 'broken' message
        return jsonify({"status": "error_logged"}), 200
    
if __name__ == '__main__':
    with app.app_context():
        db.create_all() 
    app.run(port=5000, debug=True)