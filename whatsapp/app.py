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
from models import db, ContactInquiry, Product, Customer, WhatsAppOrder, WhatsAppLead, StockAlert
from sqlalchemy.orm.attributes import flag_modified

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
# 3. Database Helper Logic (FIXED: Two-Way Sync for AI Agent)
# ==============================================================================
def get_inventory_string():
    # --- THE CRITICAL FIX ---
    db.session.expire_all() # This forces the bot to re-read the DB file right now
    
    products = Product.query.all()
    if not products: return "No stock data available."
    output = "CURRENT FARM INVENTORY:\n"
    for p in products:
        # Use the actual STATUS column from the DB
        output += f"- {p.name}: ${p.price} | {p.available_qty} left ({p.status})\n"
    return output

def deduct_stock_db(product_name, qty_to_deduct):
    product = Product.query.filter(Product.name.ilike(f"%{product_name}%")).first()
    
    if product and product.available_qty >= int(qty_to_deduct):
        product.available_qty -= int(qty_to_deduct)
        
        # --- THE AUTO-SYNC FIX ---
        if product.available_qty <= 0:
            product.status = "Out of Stock"
        else:
            product.status = "In Stock"
        
        # Mark as modified to force the write to the .db file
        flag_modified(product, "status")
        db.session.commit()
        return True
    return False

# ==============================================================================
# 4. New Prospect Handling FIXED
# ==============================================================================
def handle_new_prospect(customer_number, customer_message, history):
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%Y-%m-%d %H:%M:%S")

    system_prompt = f"""
    You are 'Leaf Plant Onboarding AI'. Time: {sg_now}.
    
    GOAL: Securely collect the user's NAME and NEIGHBORHOOD.
    
    RESPONSE FORMAT:
    1. Once you have both pieces of info, provide a SINGLE, clear confirmation.
       Example: "Thank you, [Name]! I've noted that you are from [Neighborhood]."
    
    2. Then, explain next steps: "Our team will assign you to a local Group Buy Leader who will contact you to finalize your registration. This system ensures fresh delivery and protects your private data."
    
    STRICT DATA EXTRACTION:
    At the very end of your message, you MUST include these exact tags for our database:
    [[NAME: Name]]
    [[ADDRESS: Neighborhood]]
    """
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        # 1. Database Extraction Logic
        address_match = re.search(r"\[\[ADDRESS:\s*(.*?)\]\]", ai_reply)
        name_match = re.search(r"\[\[NAME:\s*(.*?)\]\]", ai_reply)
        
        if address_match or name_match:
            existing_lead = WhatsAppLead.query.filter_by(phone=customer_number).first()
            if not existing_lead:
                new_lead = WhatsAppLead(
                    phone=customer_number,
                    extracted_name=name_match.group(1).strip() if name_match else "New Prospect",
                    neighborhood=address_match.group(1).strip() if address_match else "Pending",
                    status='Awaiting Assignment'
                )
                db.session.add(new_lead)
            else:
                if address_match: existing_lead.neighborhood = address_match.group(1).strip()
                if name_match: existing_lead.extracted_name = name_match.group(1).strip()
                existing_lead.status = 'Awaiting Assignment'
            db.session.commit()

        # 2. CLEANING LOGIC: Cut off technical tags before sending to user
        clean_reply = ai_reply.split('[[')[0].strip()
        return clean_reply

    except Exception as e:
        db.session.rollback()
        return "Welcome! May I have your name and neighborhood to link you with a local leader?"

# ==============================================================================
# 5. AI Sales Engine (FIXED: Live Data Supremacy)
# ==============================================================================
def get_openai_response(customer_message, customer_number, customer_obj):
    if not client: return "AI Offline."
    
    # CRITICAL: Force session refresh before checking stock
    db.session.expire_all() 
    stock_list = get_inventory_string()
    
    # 1. Retrieve Leader & Format Phone (Existing Logic)
    leader_name = customer_obj.leader.name if customer_obj.leader else "your local leader"
    raw_phone = customer_obj.leader.phone if customer_obj.leader else "our main line"
    clean_phone = str(raw_phone).split('.')[0] 
    formatted_phone = f"+65 {clean_phone[2:]}" if clean_phone.startswith('65') else clean_phone
    
    # 2. CONTEXTUAL MEMORY CHECK (Existing Logic)
    recent_history = conversation_history.get(customer_number, [])
    last_ai_msg = recent_history[-1]['content'] if recent_history and recent_history[-1]['role'] == 'assistant' else ""
    
    restock_context = ""
    is_restock_flow = False
    
    if "back in stock" in last_ai_msg.lower():
        match = re.search(r"back in stock: (.*?) \(", last_ai_msg)
        if match:
            restocked_item = match.group(1)
            restock_context = f"STRICT MODE: The user is responding to a restock alert for {restocked_item}. Focus ONLY on {restocked_item}. DO NOT suggest alternatives."
            is_restock_flow = True

    # 3. ENHANCED STOCK ALERT CAPTURE (Existing Logic)
    if not is_restock_flow:
        products = Product.query.all()
        for p in products:
            if p.available_qty == 0:
                if p.name.lower() in customer_message.lower():
                    existing_alert = StockAlert.query.filter_by(
                        customer_phone=customer_number, 
                        product_name=p.name, 
                        is_notified=False
                    ).first()
                    if not existing_alert:
                        new_alert = StockAlert(customer_phone=customer_number, product_name=p.name)
                        db.session.add(new_alert)
                        db.session.commit()

    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%A, %d %B %Y")

    # 4. REFINED SYSTEM PROMPT (FIXED: Force LIVE STOCK priority)
    system_prompt = f"""
    You are 'Farm Sales AI'. Today is {sg_now}. 
    Customer: {customer_obj.name}. Leader: {leader_name}.
    
    LIVE DATA SUPREMACY:
    - ALWAYS prioritize the CURRENT STOCK list below over any previous messages in this chat.
    - If CURRENT STOCK shows an item is "AVAILABLE" or has units > 0, you MUST ignore any previous "sold out" mentions.
    - If an item is back in stock, process the order immediately.
    
    RULES:
    - CURRENT STOCK: {stock_list}
    - MEMORY CONTEXT: {restock_context}
    - RESTOCK FLOW: If MEMORY CONTEXT is active, immediately ask for quantity of THAT item.
    - NO ALTERNATIVES: Do NOT suggest other products if the user is replying to a restock alert.
    - SOLD OUT LOGIC: If an item is "SOLD OUT" (and NOT in a restock flow), only ask: "Would you like me to alert you when it's back in stock?"
    - DELIVERY: Managed by {leader_name} ({formatted_phone}). NEXT-DAY delivery.
    - CONFIRMATION: Wait for "Yes" -> Tag [[DATA: Item | Qty | Total]].
    """

    if customer_number not in conversation_history: conversation_history[customer_number] = []
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[customer_number][-5:])
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        # 5. GHOST MESSAGE CLEANING (Existing Logic)
        clean_reply = ai_reply.split('[[')[0].strip()
        ghost_phrases = ["How can I assist", "How can I help", "Is there anything else"]
        for phrase in ghost_phrases:
            if phrase in clean_reply:
                clean_reply = clean_reply.split(phrase)[0].strip()

        # 6. ORDER PROCESSING (Existing Logic)
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
                    
                    return (f"{clean_reply}\n\n✅ *ORDER SECURED*\n"
                            f"{qty}x {item_name} confirmed for next-day delivery!\n\n"
                            f"🚜 *Logistics Note*: Your Group Buy Leader, *{leader_name}*, will prepare your delivery. "
                            f"Contact them at *{formatted_phone}*.")

        return clean_reply
        
    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        return "I'm having trouble connecting. Try again later!"
    
# ==============================================================================
# 6. Webhook Handling (The Gatekeeper)
# ==============================================================================
@app.route('/webhook', methods=['POST'])
def handle_message():
    data = request.get_json()
    value = data.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {})
    
    if 'messages' not in value:
        return jsonify({"status": "ignored"}), 200

    try:
        msg = value['messages'][0]
        customer_number, msg_id = msg['from'], msg['id']
        if msg.get('type') != 'text': return jsonify({"status": "non_text"}), 200
        customer_message = msg['text']['body']

        if msg_id in processed_messages: return jsonify({"status": "duplicate"}), 200
        processed_messages.add(msg_id) 

        customer = Customer.query.filter_by(phone=customer_number).first()
        reply = get_openai_response(customer_message, customer_number, customer) if customer else handle_new_prospect(customer_number, customer_message, conversation_history.get(customer_number, [])[-4:])

        if customer_number not in conversation_history: conversation_history[customer_number] = []
        conversation_history[customer_number].append({"role": "user", "content": customer_message})
        conversation_history[customer_number].append({"role": "assistant", "content": reply})

        requests.post(f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages", 
                     headers={"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}"},
                     json={"messaging_product": "whatsapp", "to": customer_number, "type": "text", "text": {"body": reply}})
        
        return jsonify({"status": "ok"}), 200 
    except Exception as e:
        print(f"WEBHOOK ERROR: {e}")
        return jsonify({"status": "error_handled"}), 200

# ==============================================================================
# 7. MAIN EXECUTION BLOCK
# ==============================================================================
if __name__ == '__main__':
    with app.app_context():
        print("🔧 Initializing Database and Tables...")
        db.create_all() 
    
    print("🚀 Farm WhatsApp Bot is starting on Port 5000...")
    print("📡 Press CTRL+C to stop the server.")
    app.run(port=5000, debug=True)