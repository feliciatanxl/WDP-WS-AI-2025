import pandas as pd
import requests 
import os 
from flask import Flask, request, jsonify
from openai import OpenAI 
import time 
import datetime
import re
from dotenv import load_dotenv

# ==============================================================================
# 1. Configuration & Security
# ==============================================================================
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env')) 

YOUR_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID") 
YOUR_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 

app = Flask(__name__)
processed_messages = set()
conversation_history = {} 

try:
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    client = None

# ==============================================================================
# 2. Data Logic
# ==============================================================================
def load_excel_data():
    try:
        inventory = pd.read_excel('Inventory and Stock Status.xlsx') 
        customers = pd.read_excel('Customer and Group Leader Mapping.xlsx') 
        leaders = pd.read_excel('Group Leader Summary.xlsx') 
        customers['WA Phone Number'] = customers['WA Phone Number'].astype(str)
        return inventory, customers, leaders
    except Exception as e:
        print(f"Error loading data: {e}")
        return None, None, None

def deduct_stock(product_name, qty_to_deduct):
    inv, cust, lead = load_excel_data()
    idx = inv[inv['Product Name'].str.contains(product_name, case=False)].index
    if not idx.empty:
        current_qty = inv.at[idx[0], 'Available Quantity']
        inv.at[idx[0], 'Available Quantity'] = current_qty - int(qty_to_deduct)
        inv.to_excel('Inventory and Stock Status.xlsx', index=False)
        print(f"[STOCK UPDATE] {product_name} reduced by {qty_to_deduct}")

# ==============================================================================
# 3. New Prospect Handling (WITH MEMORY)
# ==============================================================================
def handle_new_prospect(customer_number, customer_message, history):
    system_prompt = """
    You are Leaf Plant AI. A NEW user is messaging the farm.
    
    1. GREETING: If they haven't provided a location yet, reply warmly and ask which neighborhood or area they are in.
    2. PRIVACY: Explain that this neighborhood check helps protect their identity and ensures fresh delivery.
    3. EXTRACTION: ONLY if the user mentions a specific area/neighborhood, add the hidden tag: [[ADDRESS: Exact Neighborhood/Area]].
    """
    
    # Build messages with context history
    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append(h)
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        ai_reply = completion.choices[0].message.content
        
        address_match = re.search(r"\[\[ADDRESS: (.*?)\]\]", ai_reply)
        
        if address_match:
            extracted_address = address_match.group(1)
            print(f"\n--- [DATA COLLECTED] ---")
            print(f"Phone: {customer_number}")
            print(f"AI Extracted Area: {extracted_address}")
            print(f"------------------------\n")

            leads_file = 'New_Leads_Waiting_List.xlsx'
            new_lead = pd.DataFrame([{
                'Timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 
                'Phone': customer_number, 
                'Extracted Address': extracted_address, 
                'Status': 'Awaiting Leader Assignment'
            }])

            if not os.path.exists(leads_file): 
                new_lead.to_excel(leads_file, index=False)
            else: 
                pd.concat([pd.read_excel(leads_file), new_lead], ignore_index=True).to_excel(leads_file, index=False)
        else:
            print(f"[CHAT] New user {customer_number} is in greeting phase.")

        return re.sub(r"\[\[ADDRESS: .*?\]\]", "", ai_reply).strip()

    except Exception as e:
        if "Permission denied" in str(e):
            print(f"\n[!!!] PLEASE CLOSE 'New_Leads_Waiting_List.xlsx'!")
        return "Welcome to the farm! Could you let us know which neighborhood you are in?"

# ==============================================================================
# 4. AI Sales Engine
# ==============================================================================
def get_openai_response(customer_message, customer_id, leader_name, inventory_df):
    if not client: return "AI Offline."
    if customer_id not in conversation_history: conversation_history[customer_id] = []
    
    history = conversation_history[customer_id][-4:]
    stock_list = inventory_df[['Product Name', 'Stock Status', 'Price', 'Member Discount (%)', 'Available Quantity']].to_string(index=False)
    
    messages = [{"role": "system", "content": f"You are 'Leaf Plant AI'. Customer: {customer_id}. Leader: {leader_name}. Stock: {stock_list}. Tag order: [[DATA: Item | Qty | Cost]]."}]
    for h in history: messages.append(h)
    messages.append({"role": "user", "content": customer_message})

    try:
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        ai_reply = completion.choices[0].message.content
        
        conversation_history[customer_id].append({"role": "user", "content": customer_message})
        conversation_history[customer_id].append({"role": "assistant", "content": ai_reply})

        if "[[DATA:" in ai_reply:
            match = re.search(r"\[\[DATA: (.*?)\]\]", ai_reply)
            if match:
                parts = [p.strip() for p in match.group(1).split('|')]
                if len(parts) == 3:
                    item, qty, cost = parts[0], parts[1], parts[2]
                    log_file = 'Farm_Orders_Fulfillment.xlsx'
                    order = pd.DataFrame([{'Timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 'Censored Buyer ID': customer_id, 'Group Leader': leader_name, 'Item': item, 'Quantity': qty, 'Total Cost': cost, 'ERP Sync Status': 'Ready for Narration Export'}])
                    if not os.path.exists(log_file): order.to_excel(log_file, index=False)
                    else: pd.concat([pd.read_excel(log_file), order]).to_excel(log_file, index=False)
                    deduct_stock(item, qty)
                    print(f"\n[!!! ERP SUCCESS !!!] Order logged for {customer_id}")

        return re.sub(r"\[\[DATA: .*?\]\]", "", ai_reply).strip()
    except Exception as e:
        return "I'm having a connection issue. A real salesperson will help soon!"

# ==============================================================================
# 5. Webhook Handling
# ==============================================================================
@app.route('/webhook', methods=['GET'])
def verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == YOUR_VERIFY_TOKEN:
        return challenge, 200
    return 'Verification failed', 403

@app.route('/webhook', methods=['POST'])
def handle_message():
    data = request.get_json()
    inventory_df, customer_df, leader_df = load_excel_data()
    
    try:
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        customer_number, msg_id, customer_message = msg['from'], msg['id'], msg['text']['body']
        print(f"\n[INCOMING] {customer_number}: {customer_message}")
    except: return jsonify({"status": "error"}), 200

    if msg_id in processed_messages: return jsonify({"status": "duplicate"}), 200
    processed_messages.add(msg_id) 

    # Handle conversation history for both types of users
    if customer_number not in conversation_history:
        conversation_history[customer_number] = []
    
    current_history = conversation_history[customer_number][-4:]
    cust_row = customer_df[customer_df['WA Phone Number'] == customer_number]
    
    if not cust_row.empty:
        cust_id = cust_row['Customer ID'].iloc[0]
        l_name = leader_df[leader_df['Group Leader ID'] == cust_row['Group Leader ID'].iloc[0]]['Leader Name'].iloc[0]
        reply = get_openai_response(customer_message, cust_id, l_name, inventory_df)
    else:
        # Pass history to prospect handler
        reply = handle_new_prospect(customer_number, customer_message, current_history)

    # Save to memory for the next message
    conversation_history[customer_number].append({"role": "user", "content": customer_message})
    conversation_history[customer_number].append({"role": "assistant", "content": reply})

    requests.post(f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages", 
                 headers={"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}"},
                 json={"messaging_product": "whatsapp", "to": customer_number, "type": "text", "text": {"body": reply}})
        
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(port=5000, debug=True)