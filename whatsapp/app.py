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
pending_alerts_dict = {}  # Global dictionary for OOS memory

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
# 4. Outgoing Message Helper
# ==============================================================================
def send_whatsapp_message(to_phone, message_text):
    url = f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": str(to_phone),
        "type": "text",
        "text": {"body": message_text}
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error sending WhatsApp: {e}")
        return False

# ==============================================================================
# 5. New Prospect Handling
# ==============================================================================
def handle_new_prospect(customer_number, customer_message, history):
    sg_now = datetime.now(pytz.timezone('Asia/Singapore')).strftime("%Y-%m-%d %H:%M:%S")
    leader = GroupLeader.query.first()
    leader_info = f"{leader.name} (+{str(leader.phone).split('.')[0]})" if leader else "a local delivery representative"

    system_prompt = f"""
    You are 'Leaf Plant Onboarding AI'. Time: {sg_now}. 
    GOAL: Collect NAME and NEIGHBORHOOD. 
    INSTRUCTIONS:
    1. Ask for name and neighborhood.
    2. Inform them their Leader ({leader_info}) will verify them.
    3. State: "Orders can only be placed after registration."
    [[NAME: user_name]] [[ADDRESS: neighborhood]]
    """
    messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": customer_message}]
    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        name_match = re.search(r"\[\[NAME:\s*(.*?)\]\]", ai_reply)
        addr_match = re.search(r"\[\[ADDRESS:\s*(.*?)\]\]", ai_reply)
        lead = WhatsAppLead.query.filter_by(phone=customer_number).first()
        if not lead:
            lead = WhatsAppLead(phone=customer_number, extracted_name="New Prospect", neighborhood="Pending")
            db.session.add(lead)
        if name_match: lead.extracted_name = name_match.group(1).strip()
        if addr_match: lead.neighborhood = addr_match.group(1).strip()
        db.session.commit()
        return ai_reply.split('[[')[0].strip()
    except Exception:
        db.session.rollback()
        return "Welcome! May I have your name and neighborhood to register you?"

# ==============================================================================
# 6. AI Sales Engine (STABLE DB UPDATES + STRICT CONFIRMATION LOGIC)
# ==============================================================================
def get_openai_response(customer_message, customer_number, customer_obj):
    if not client: return "AI Offline."

    # --- 1. FORCE LIVE DB SYNC ---
    db.session.expire_all() 
    stock_list = get_inventory_string()
    user_input_low = customer_message.lower().strip()

    # --- 2. RESTOCK CONTEXT OVERRIDE ---
    recent_notif = StockAlert.query.filter_by(
        customer_phone=str(customer_number), 
        is_notified=True
    ).order_by(StockAlert.id.desc()).first()

    restock_override = ""
    if recent_notif:
        p_check = Product.query.filter_by(name=recent_notif.product_name).first()
        if p_check and p_check.available_qty > 0:
            restock_override = f"🚨 SYSTEM ALERT: {p_check.name} is NOW IN STOCK. Ignore history saying OOS."

    # --- 3. HUMAN THANKS ---
    thanks_words = ["thank you", "thanks", "thx", "received", "noted"]
    if user_input_low in thanks_words:
        return f"You're so welcome, {customer_obj.name}! 😊 Have a wonderful day ahead! 🌿"

    # --- 4. DETECT MENTIONED PRODUCT ---
    all_products = Product.query.all()
    mentioned_product = None
    for p in all_products:
        if p.name.lower() in user_input_low:
            mentioned_product = p
            break

    # --- 5. OOS GATE (STOCK ALERT FIRST) ---
    if mentioned_product:
        if mentioned_product.available_qty <= 0 or mentioned_product.status == "Out of Stock":
            pending_alerts_dict[customer_number] = mentioned_product.name
            return (
                f"Oh, I'm so sorry, {customer_obj.name}! 🌱 *{mentioned_product.name}* is sold out. 😕 "
                "Would you like me to notify you the second it's back? Just say *YES*! 🌿"
            )

    # --- 6. STOCK ALERT CONFIRMATION ---
    affirmative_words = ["yes", "ok", "alert", "notify", "sure", "want", "yep", "please", "confirm"]
    if any(word == user_input_low for word in affirmative_words):
        product_name = pending_alerts_dict.get(customer_number)
        if product_name:
            try:
                db.session.add(StockAlert(customer_phone=str(customer_number), product_name=product_name, is_notified=False))
                db.session.commit()
                pending_alerts_dict.pop(customer_number, None)
                return (f"Done! ✅ I've added you to the list for *{product_name}*. 🌿\n\n"
                        "In the meantime, would you like to see what else is available? 😊")
            except Exception: db.session.rollback()

    history = conversation_history.get(customer_number, [])
    is_already_finalized = any("ORDER SECURED" in m["content"] for m in history[-2:])
    
    leader_name = customer_obj.leader.name if customer_obj.leader else "Test Leader"
    leader_phone = str(customer_obj.leader.phone).split(".")[0] if customer_obj.leader else "6500000000"
    sg_now = datetime.now(pytz.timezone("Asia/Singapore")).strftime("%A, %d %B %Y")

    # --- 7. SYSTEM PROMPT (STRICT SEPARATION OF CONFIRMATION & SUGGESTIONS) ---
    system_prompt = f"""
    You are 'Leaf Plant Sales AI'. Today: {sg_now}. Customer: {customer_obj.name}.
    LIVE INVENTORY: {stock_list}
    {restock_override}

    TONE: Neighborly farm assistant. Use emojis 🌿, 😊.

    SALES FLOW RULES:
    1. INQUIRY: Ask for quantity before summarizing.
    2. PRE-ORDER SUMMARY & CROSS-SELL: 
       - Show the subtotal for currently selected items.
       - Suggest ONE related available item (e.g., "Would you like to add some Mao Bai too?").
       - Ask: "Shall I proceed with this order for you?"
    3. THE "YES" RULE: If a user says "Yes", "Ok", or "Confirm" without mentioning the cross-sell item, interpret this ONLY as confirming the current summary. DO NOT add the suggested item to the data tags unless they explicitly say "Add [Qty] of [Item]".
    4. CONFIRMATION: Once they agree to a summary, add [[STATUS: CONFIRMED]].
    5. DATA: Output [[DATA: Item | Qty | TotalPrice]] only for confirmed items.
    """

    messages = [{"role": "system", "content": system_prompt}, *history[-6:], {"role": "user", "content": customer_message}]

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        is_ai_confirmed = "[[STATUS: CONFIRMED]]" in ai_reply
        clean_reply = re.sub(r"\[\[DATA:.*?\]\]", "", ai_reply)
        clean_reply = re.sub(r"\[\[STATUS:.*?\]\]", "", clean_reply).strip()

        # --- 8. DATA EXTRACTION ---
        order_matches = re.findall(r"\[\[DATA:\s*(.*?)\s*\]\]", ai_reply)
        if not order_matches: 
            for h in reversed(history[-2:]):
                order_matches = re.findall(r"\[\[DATA:\s*(.*?)\s*\]\]", h.get("content", ""))
                if order_matches: break

        # --- 9. DATABASE UPDATES ---
        if order_matches and is_ai_confirmed and not is_already_finalized:
            order_summary_text, grand_total = "", 0.0
            pending_db_entries = []

            for match in order_matches:
                parts = [p.strip() for p in match.split("|")]
                if len(parts) != 3: continue 
                item_name, qty_str, total_str = parts[0], re.sub(r"[^\d]", "", parts[1]), re.sub(r"[^\d.]", "", parts[2])

                if qty_str and total_str:
                    qty, item_total = int(qty_str), float(total_str)
                    if qty > 0 and deduct_stock_db(item_name, qty):
                        pending_db_entries.append(WhatsAppOrder(
                            customer_id=customer_obj.id, leader_id=customer_obj.leader_id,
                            customer_phone=str(customer_number), product_name=item_name,
                            quantity=qty, total_price=item_total,
                            commission_earned=item_total * 0.111, order_status="Confirmed"
                        ))
                        order_summary_text += f"• {item_name}: {qty} units = ${item_total:.2f}\n"
                        grand_total += item_total

            if pending_db_entries:
                for o in pending_db_entries: db.session.add(o)
                db.session.commit()
                return (f"✨ *ORDER SECURED* 🌿\n\nThank you, {customer_obj.name}! 🌟 Your order is confirmed!\n\n"
                        f"{order_summary_text}*Total Price:* ${grand_total:.2f}\n\n"
                        f"Delivery via {leader_name} (+{leader_phone}). 😊🌱")

        return clean_reply
    except Exception as e:
        db.session.rollback()
        return "I'm just refreshing my notes, one moment! 😊"

# ==============================================================================
# 7. Webhook Handling
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
        send_whatsapp_message(customer_number, reply)
        return jsonify({"status": "ok"}), 200 
    except Exception: return jsonify({"status": "error"}), 200

if __name__ == '__main__':
    with app.app_context():
        event.listen(db.engine, "connect", set_sqlite_pragma)
        db.create_all() 
    app.run(port=5000, debug=True)