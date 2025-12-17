import pandas as pd
import requests 
import os 
from flask import Flask, request, jsonify
from openai import OpenAI 
import time 
import datetime
import re

# ==============================================================================
# 1. Configuration
# ==============================================================================
YOUR_ACCESS_TOKEN = "EAAQUEA9objwBQOfM8zyMMTjYwlMP0sA5tCPcAcYP8I1occ5InZCNIKeunjDtUUpTm6zPtReWqX3fXkWyRZAF51eCYNuF5tRRELZC9H3fn6m40H6QzOPSFv2E2ZBcffTZCZBfnL4fcYIf6rzOYl8PBU1b7zjag48Tohzp4BYghZB3CkZBMml8N189VorClnjintEzfgZDZD"
PHONE_NUMBER_ID = "943273875531695" 
YOUR_VERIFY_TOKEN = "leaf_plant_secret_key" 
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
# 3. New Prospect Handling (Clean Address Extraction)
# ==============================================================================
def handle_new_prospect(customer_number, customer_message):
    system_prompt = """
    You are Leaf Plant AI. A NEW user is messaging the farm.
    1. Reply warmly and explain we need their neighborhood to find a local Leader.
    2. PRIVACY: Explain that this neighborhood check helps protect their identity.
    3. EXTRACTION: Add hidden tag: [[ADDRESS: Exact Neighborhood/Area]].
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": customer_message}]
        )
        ai_reply = completion.choices[0].message.content
        address_match = re.search(r"\[\[ADDRESS: (.*?)\]\]", ai_reply)
        extracted_address = address_match.group(1) if address_match else "Unknown"

        leads_file = 'New_Leads_Waiting_List.xlsx'
        new_lead = pd.DataFrame([{'Timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 'Phone': customer_number, 'Extracted Address': extracted_address, 'Status': 'Awaiting Leader Assignment'}])

        if not os.path.exists(leads_file): new_lead.to_excel(leads_file, index=False)
        else: pd.concat([pd.read_excel(leads_file), new_lead], ignore_index=True).to_excel(leads_file, index=False)
            
        return re.sub(r"\[\[ADDRESS: .*?\]\]", "", ai_reply).strip()
    except Exception as e:
        # API FAIL-SAFE
        print(f"\n[!!! API ERROR !!!] New Lead {customer_number} needs manual onboarding.")
        return "Welcome to the farm! Our system is a bit slow right now, but a human salesperson will assist you with leader registration shortly."

# ==============================================================================
# 4. AI Sales Engine (Existing Customers + Fail-Safe)
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
        
        # Save to memory
        conversation_history[customer_id].append({"role": "user", "content": customer_message})
        conversation_history[customer_id].append({"role": "assistant", "content": ai_reply})

        # ERP extraction
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
        # API FAIL-SAFE ALERT
        print(f"\n[!!! CRITICAL API FAILURE !!!]")
        print(f"Customer: {customer_id} | Message: {customer_message}")
        print(f"Error: {e}")
        print(f"ACTION: Jump in manually on WhatsApp to secure the order!")
        return "I'm having a slight connection issue with the farm database. Hang tight, a real salesperson will jump in to help you finish your order!"

# ==============================================================================
# 5. Webhook Handling
# ==============================================================================
@app.route('/webhook', methods=['POST'])
def handle_message():
    data = request.get_json()
    inventory_df, customer_df, leader_df = load_excel_data() # Continuous link
    
    try:
        msg = data['entry'][0]['changes'][0]['value']['messages'][0]
        customer_number, msg_id, customer_message = msg['from'], msg['id'], msg['text']['body']
    except: return jsonify({"status": "error"}), 200

    if msg_id in processed_messages: return jsonify({"status": "duplicate"}), 200
    processed_messages.add(msg_id) 

    cust_row = customer_df[customer_df['WA Phone Number'] == customer_number]
    
    if not cust_row.empty:
        cust_id = cust_row['Customer ID'].iloc[0]
        l_name = leader_df[leader_df['Group Leader ID'] == cust_row['Group Leader ID'].iloc[0]]['Leader Name'].iloc[0]
        reply = get_openai_response(customer_message, cust_id, l_name, inventory_df)
    else:
        reply = handle_new_prospect(customer_number, customer_message)

    requests.post(f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages", 
                 headers={"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}"},
                 json={"messaging_product": "whatsapp", "to": customer_number, "type": "text", "text": {"body": reply}})
        
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(port=5000, debug=True)