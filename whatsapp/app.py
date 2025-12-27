# ==============================================================================
# 0. PATH FIXED
# ==============================================================================
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ==============================================================================
# 1. Standard Imports FIXED
# ==============================================================================
import requests
import re
import io
from datetime import datetime
from flask import Flask, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv
import pytz
from models import db, ContactInquiry, Product, Customer, WhatsAppOrder, WhatsAppLead, StockAlert, set_sqlite_pragma, GroupLeader
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import event

# ==============================================================================
# 2. Configuration & Security FIXED
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
# 3. Database Helper Logic FIXED
# ==============================================================================
def get_inventory_string():
    db.session.expire_all() 
    products = Product.query.all()
    if not products: return "No stock data available."
    output = "CURRENT FARM INVENTORY:\n"
    for p in products:
        status_label = "AVAILABLE" if (p.status == "In Stock" and p.available_qty > 0) else "SOLD OUT"
        output += f"- {p.name}: ${p.price} | {p.available_qty} units ({status_label})\n"
    return output

def deduct_stock_db(product_name, qty_to_deduct):
    product = Product.query.filter(Product.name.ilike(f"%{product_name}%")).first()
    if product and product.available_qty >= int(qty_to_deduct):
        product.available_qty -= int(qty_to_deduct)
        product.status = "Out of Stock" if product.available_qty <= 0 else "In Stock"
        flag_modified(product, "status")
        db.session.commit()
        return True
    return False

# ==============================================================================
# 4. New Prospect Handling (STRICT ONBOARDING & CONTINUOUS UPDATES)
# ==============================================================================
def handle_new_prospect(customer_number, customer_message, history):
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%Y-%m-%d %H:%M:%S")
    
    # Retrieve first leader info to show to the prospect
    leader = GroupLeader.query.first()
    leader_info = f"{leader.name} (+{str(leader.phone).split('.')[0]})" if leader else "a local delivery representative"

    system_prompt = f"""
    You are 'Leaf Plant Onboarding AI'. Time: {sg_now}. 
    
    GOAL: You MUST collect the user's NAME and NEIGHBORHOOD. 
    DO NOT provide product prices, stock information, or accept orders.
    
    INSTRUCTIONS:
    1. Politely ask for their name and neighborhood.
    2. Once they provide info, tell them their Leader ({leader_info}) will contact them to verify their account.
    3. Clearly state: "Orders can only be placed after registration is finalized."
    
    STRICT DATA EXTRACTION (Include at the very end of EVERY response if info mentioned):
    [[NAME: user_name]] [[ADDRESS: neighborhood]]
    """
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        # Parse tags to update the database in real-time
        name_match = re.search(r"\[\[NAME:\s*(.*?)\]\]", ai_reply)
        addr_match = re.search(r"\[\[ADDRESS:\s*(.*?)\]\]", ai_reply)
        
        # Continuous DB Update Logic
        lead = WhatsAppLead.query.filter_by(phone=customer_number).first()
        
        if name_match or addr_match or not lead:
            if not lead:
                lead = WhatsAppLead(phone=customer_number, extracted_name="New Prospect", neighborhood="Pending")
                db.session.add(lead)
            
            if name_match: 
                name_val = name_match.group(1).strip()
                if name_val.lower() not in ["name", "user_name"]:
                    lead.extracted_name = name_val
            
            if addr_match: 
                addr_val = addr_match.group(1).strip()
                if addr_val.lower() != "neighborhood":
                    lead.neighborhood = addr_val
            
            db.session.commit()

        return ai_reply.split('[[')[0].strip()
    except Exception as e:
        db.session.rollback()
        return "Welcome! To link you with a local leader, may I have your name and neighborhood?"

# ==============================================================================
# 5. AI Sales Engine (FOR REGISTERED CUSTOMERS ONLY)
# ==============================================================================
def get_openai_response(customer_message, customer_number, customer_obj):
    if not client: return "AI Offline."
    
    db.session.expire_all() 
    stock_list = get_inventory_string()
    user_input_low = customer_message.lower()

    # --- 1. CAPTURE "YES" TO STOCK ALERT ---
    # This logic detects 'yes' and looks back to find which product was sold out
    if any(word in user_input_low for word in ["yes", "ok", "alert", "notify", "sure", "want"]):
        all_prods = Product.query.all()
        history = conversation_history.get(customer_number, [])
        # Get the context of the last 3 messages to find the product name
        last_msgs = " ".join([m['content'].lower() for m in history[-3:]])
        
        for p in all_prods:
            p_name_low = p.name.lower()
            # If the product name was mentioned recently and it's currently OOS
            if (p_name_low in last_msgs or p_name_low in user_input_low) and p.available_qty <= 0:
                # Check for existing pending alert to avoid duplicates
                existing = StockAlert.query.filter_by(
                    customer_phone=customer_number, 
                    product_name=p.name, 
                    is_notified=False
                ).first()

                if not existing:
                    try:
                        # --- DATABASE INPUT LOGIC ---
                        new_alert = StockAlert(
                            customer_phone=customer_number, 
                            product_name=p.name, 
                            is_notified=False
                        )
                        db.session.add(new_alert)
                        db.session.flush() # Force ID generation
                        db.session.commit() # Save to leafplant.db
                        
                        print(f"✔️ DB SUCCESS: Stock Alert for {p.name} created for {customer_number}")
                        return f"Great! I've added you to the waiting list for *{p.name}*. I'll message you here the moment it's back! 🌿"
                    except Exception as e:
                        db.session.rollback()
                        print(f"❌ DB ERROR saving stock alert: {e}")

    # --- 2. RESTOCK CONTEXT ---
    recent_notif = StockAlert.query.filter_by(customer_phone=customer_number, is_notified=True).order_by(StockAlert.id.desc()).first()
    restock_context = f"User is responding to a restock alert for {recent_notif.product_name}." if recent_notif else ""

    # Prepare Leader Details
    leader_name = customer_obj.leader.name if customer_obj.leader else "your leader"
    leader_phone = str(customer_obj.leader.phone).split('.')[0] if customer_obj.leader else "our help desk"
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%A, %d %B %Y")

    # --- 3. UPDATED SYSTEM PROMPT ---
    system_prompt = f"""
    You are 'Farm Sales AI'. Today: {sg_now}.
    Customer: {customer_obj.name}.
    
    INVENTORY (ONLY TRUST THIS):
    {stock_list}
    
    CONTEXT: {restock_context}
    
    CRITICAL SALES RULES:
    1. If a customer asks for an item and the INVENTORY shows it as SOLD OUT (0 units), you MUST ask: "Would you like me to notify you here as soon as it is back in stock?"
    2. Do NOT suggest alternative products unless you have already offered the restock alert.
    3. If an item is IN STOCK, process the order immediately.
    4. CONFIRMED ORDERS: Tag as [[DATA: Item | Qty | Total]].
    5. Mention delivery via {leader_name} (+{leader_phone}).
    """

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history.get(customer_number, [])[-6:])
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        clean_reply = ai_reply.split('[[')[0].strip()

        # --- 4. ORDER EXTRACTION ---
        data_match = re.search(r"\[\[DATA:\s*(.*?)\s*\]\]", ai_reply)
        if data_match:
            parts = [p.strip() for p in data_match.group(1).split('|')]
            if len(parts) == 3:
                item_name, qty_str, total_cost = parts[0], re.sub(r'[^\d]', '', parts[1]), float(re.sub(r'[^\d.]', '', parts[2]))
                if qty_str and deduct_stock_db(item_name, int(qty_str)):
                    qty = int(qty_str)
                    new_order = WhatsAppOrder(
                        customer_id=customer_obj.id, leader_id=customer_obj.leader_id,
                        customer_phone=customer_number, product_name=item_name,
                        quantity=qty, total_price=total_cost,
                        commission_earned=total_cost * 0.111, order_status='Confirmed'
                    )
                    db.session.add(new_order)
                    db.session.commit()
                    
                    return (f"{clean_reply}\n\n"
                            f"✅ *ORDER SECURED*\n"
                            f"*{qty}x {item_name}* confirmed for delivery.\n\n"
                            f"Your Group Buy Leader, *{leader_name}*, will contact you at *(+{leader_phone})* regarding pickup details! 🌿")
        return clean_reply
    except Exception as e:
        print(f"AI ERROR: {e}")
        return "I'm checking that for you now!"

# ==============================================================================
# 6. Webhook Handling
# ==============================================================================
@app.route('/webhook', methods=['POST'])
def handle_message():
    data = request.get_json()
    value = data.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {})
    if 'messages' not in value: return jsonify({"status": "ignored"}), 200

    try:
        msg = value['messages'][0]
        customer_number, msg_id = msg['from'], msg['id']
        if msg.get('type') != 'text': return jsonify({"status": "non_text"}), 200
        customer_message = msg['text']['body']

        if msg_id in processed_messages: return jsonify({"status": "duplicate"}), 200
        processed_messages.add(msg_id) 

        db.session.expire_all()
        customer = Customer.query.filter_by(phone=customer_number).first()
        
        if customer:
            reply = get_openai_response(customer_message, customer_number, customer)
        else:
            reply = handle_new_prospect(customer_number, customer_message, conversation_history.get(customer_number, [])[-4:])

        if customer_number not in conversation_history: conversation_history[customer_number] = []
        conversation_history[customer_number].append({"role": "user", "content": customer_message})
        conversation_history[customer_number].append({"role": "assistant", "content": reply})

        requests.post(f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages", 
                     headers={"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}"},
                     json={"messaging_product": "whatsapp", "to": customer_number, "type": "text", "text": {"body": reply}})
        return jsonify({"status": "ok"}), 200 
    except Exception as e:
        return jsonify({"status": "error"}), 200

# ==============================================================================
# 7. MAIN EXECUTION BLOCK
# ==============================================================================
if __name__ == '__main__':
    with app.app_context():
        event.listen(db.engine, "connect", set_sqlite_pragma)
        db.create_all() 
    app.run(port=5000, debug=True)