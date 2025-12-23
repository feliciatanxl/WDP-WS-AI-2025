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
# 3. Database Helper Logic
# ==============================================================================
def get_inventory_string():
    products = Product.query.all()
    if not products: return "No stock data available."
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
# 4. New Prospect Handling (UPDATED: Data Summary & Leader Assignment) FIXED
# ==============================================================================
def handle_new_prospect(customer_number, customer_message, history):
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%Y-%m-%d %H:%M:%S")

    # REFINED PROMPT: Removes redundant instructions to prevent duplicate text
    system_prompt = f"""
    You are 'Leaf Plant Onboarding AI'. Time: {sg_now}.
    
    GOAL: Securely collect the user's NAME and NEIGHBORHOOD.
    
    RESPONSE FORMAT:
    1. Once you have both pieces of info, provide a SINGLE, clear confirmation.
       Example: "Thank you, [Name]! I've noted that you are from [Neighborhood]."
    
    2. Then, explain the next steps: "Our team will assign you to a local Group Buy Leader who will contact you to finalize your registration. This system ensures fresh delivery and protects your private data."
    
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
                    status='Awaiting Info'
                )
                db.session.add(new_lead)
            else:
                if address_match: existing_lead.neighborhood = address_match.group(1).strip()
                if name_match: existing_lead.extracted_name = name_match.group(1).strip()
                if existing_lead.neighborhood != "Pending" and existing_lead.extracted_name != "New Prospect":
                    existing_lead.status = 'Awaiting Assignment'
            db.session.commit()

        # 2. CLEANING LOGIC: This stops the customer from seeing the "Tags" or duplicate info
        # We strip out everything starting from the first double bracket [[
        clean_reply = ai_reply.split('[[')[0].strip()
        
        # Final safety check: if the AI added bullet points like in your screenshot, remove them
        clean_reply = clean_reply.replace('· Tag:', '').replace('• Tag:', '').strip()
        
        return clean_reply

    except Exception as e:
        db.session.rollback()
        return "Welcome! May I have your name and neighborhood to link you with a local leader?"

# ==============================================================================
# 5. AI Sales Engine 
# ==============================================================================
def get_openai_response(customer_message, customer_number, customer_obj):
    if not client: return "AI Offline."
    stock_list = get_inventory_string()
    
    # Retrieve Leader details from the database
    leader_name = customer_obj.leader.name if customer_obj.leader else "your local leader"
    leader_phone = customer_obj.leader.phone if customer_obj.leader else "our main line"
    
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%A, %d %B %Y")

    system_prompt = f"""
    You are 'Farm Sales AI'. Today is {sg_now}. 
    Customer: {customer_obj.name}. Leader: {leader_name}.
    
    DELIVERY PROTOCOL:
    - You MUST inform the customer that their delivery is managed by their Group Buy Leader, {leader_name}.
    - Provide the Leader's contact number: {leader_phone} for any questions.
    - Explain that the farm only sees bulk order totals to protect customer privacy.

    RULES:
    1. LANGUAGE: Match the user's language exactly.
    2. CONTEXT: If they say "Yes" to a restock alert, assume they mean that item.
    3. NO GENERIC TERMS: Always use specific names (e.g., "Mizuna").
    4. DELIVERY: All confirmed orders are for NEXT-DAY delivery.
    5. INVENTORY: {stock_list}. Member gets 10% discount.
    6. CONFIRMATION: Ask for quantity -> Show Total -> Wait for "Yes" -> Tag [[DATA: Item | Qty | Total]].
    """

    if customer_number not in conversation_history: conversation_history[customer_number] = []
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history[customer_number][-5:])
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        # --- ORDER PROCESSING (Safety Guard) ---
        data_match = re.search(r"\[\[DATA:\s*(.*?)\s*\]\]", ai_reply)
        if data_match:
            parts = [p.strip() for p in data_match.group(1).split('|')]
            if len(parts) == 3:
                item_name = parts[0]
                qty_str = re.sub(r'[^\d]', '', parts[1])
                
                if not qty_str:
                    return re.sub(r"\[\[DATA:.*?\]\]", "", ai_reply).strip()

                qty = int(qty_str)
                total_cost = float(re.sub(r'[^\d.]', '', parts[2]))
                
                if deduct_stock_db(item_name, qty):
                    new_order = WhatsAppOrder(
                        customer_id=customer_obj.id, 
                        leader_id=customer_obj.leader_id,
                        customer_phone=customer_number, 
                        product_name=item_name,
                        quantity=qty, 
                        total_price=total_cost,
                        commission_earned=total_cost * 0.111, 
                        order_status='Confirmed'
                    )
                    db.session.add(new_order)
                    db.session.commit()
                    
                    # Updated Secured message with Leader Contact
                    clean_reply = re.sub(r"\[\[DATA:.*?\]\]", "", ai_reply).strip()
                    return (f"{clean_reply}\n\n"
                            f"✅ *ORDER SECURED*\n"
                            f"{qty}x {item_name} confirmed for next-day delivery!\n\n"
                            f"🚜 *Logistics Note*: Your Group Buy Leader, *{leader_name}*, will prepare your delivery. "
                            f"Contact them at *{leader_phone}* if you have questions.")

        return re.sub(r"\[\[DATA:.*?\]\]", "", ai_reply).strip()
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