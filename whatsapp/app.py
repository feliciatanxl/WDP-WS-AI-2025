import pandas as pd
import requests 
import os 
from flask import Flask, request, jsonify
from openai import OpenAI 
import time 

# ==============================================================================
# 1. Configuration
# ==============================================================================

YOUR_ACCESS_TOKEN = "EAAQUEA9objwBQOfM8zyMMTjYwlMP0sA5tCPcAcYP8I1occ5InZCNIKeunjDtUUpTm6zPtReWqX3fXkWyRZAF51eCYNuF5tRRELZC9H3fn6m40H6QzOPSFv2E2ZBcffTZCZBfnL4fcYIf6rzOYl8PBU1b7zjag48Tohzp4BYghZB3CkZBMml8N189VorClnjintEzfgZDZD"
PHONE_NUMBER_ID = "943273875531695" 
YOUR_VERIFY_TOKEN = "leaf_plant_secret_key" 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 

inventory_df = None
customer_df = None
leader_df = None
processed_messages = set()

app = Flask(__name__)

try:
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
    else:
        print("WARNING: No OpenAI API Key found in environment variables!")
        client = None
except Exception as e:
    print(f"FATAL ERROR: Could not initialize OpenAI Client. Error: {e}")
    client = None

# ==============================================================================
# 2. Data Loading
# ==============================================================================
def load_excel_data():
    global inventory_df, customer_df, leader_df
    try:
        inventory_df = pd.read_excel('Inventory and Stock Status.xlsx') 
        customer_df = pd.read_excel('Customer and Group Leader Mapping.xlsx') 
        leader_df = pd.read_excel('Group Leader Summary.xlsx') 
        customer_df['WA Phone Number'] = customer_df['WA Phone Number'].astype(str)
        print("\n--- Data Loading Success ---\n")
    except Exception as e:
        print(f"FATAL ERROR loading data: {e}")

load_excel_data()

# ==============================================================================
# 3. Message Sending
# ==============================================================================
def send_whatsapp_message(to_number, message_body):
    API_URL = f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {YOUR_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": { "body": message_body }
    }
    try:
        response = requests.post(API_URL, headers=headers, json=payload)
        return response.json()
    except Exception as err:
        print(f"Error sending message: {err}")
        return None

# ==============================================================================
# 4. Generative AI Processing Function (UPDATED FOR FULL INVENTORY)
# ==============================================================================

def get_openai_response(customer_message, customer_name, leader_name, leader_contact):
    """Generates a response by providing the full inventory to OpenAI."""
    if not client:
        return "AI is offline. Please check the API key environment variable."

    # NEW: Convert the entire inventory into a text format for the AI to read
    # We only send Product Name and Stock Status to keep it clean
    stock_list = inventory_df[['Product Name', 'Stock Status']].to_string(index=False)
    
    # Updated System Instruction
    system_prompt = f"""
    You are 'Leaf Plant AI', a friendly customer agent for a group buying service. 
    Customer: {customer_name}
    Leader: {leader_name} ({leader_contact})

    CURRENT INVENTORY STATUS:
    {stock_list}

    RULES:
    1. Always address customer by name.
    2. Use the 'CURRENT INVENTORY STATUS' list above to answer stock questions.
    3. If they ask for a specific item (e.g., 'Cherry Tomatoes') but you only see a similar item 
       (e.g., 'Heirloom Tomatoes'), explain what is available.
    4. If an item is 'OUT OF STOCK', suggest they contact their Leader, {leader_name}, for restock dates.
    5. Keep responses concise and professional.
    """
    
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": customer_message}
            ],
            max_tokens=250
        )
        ai_reply = completion.choices[0].message.content
        print(f"--- AI REPLY: {ai_reply} ---")
        return ai_reply
        
    except Exception as e:
        print(f"OpenAI API Error: {e}")
        return "Oops! My AI brain hit a snag. Please try again."

# ==============================================================================
# 5. Webhook Endpoints (No Change)
# ==============================================================================

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    if request.args.get("hub.verify_token") == YOUR_VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403

@app.route('/webhook', methods=['POST'])
def handle_message():
    global processed_messages
    data = request.get_json()
    
    try:
        val = data['entry'][0]['changes'][0]['value']
        if 'messages' not in val: return jsonify({"status": "no message"}), 200
        msg = val['messages'][0]
        customer_number = msg['from']
        msg_id = msg['id']
        customer_message = msg['text']['body'] if msg['type'] == 'text' else "NOT_TEXT_MESSAGE"
    except:
        return jsonify({"status": "error"}), 200

    if msg_id in processed_messages: return jsonify({"status": "duplicate"}), 200
    processed_messages.add(msg_id) 
    
    print(f"--- INBOUND: {customer_message} ---")

    try:
        customer_info = customer_df[customer_df['WA Phone Number'] == customer_number]
        if not customer_info.empty:
            customer_name = customer_info['Customer ID'].iloc[0] 
            leader_id = customer_info['Group Leader ID'].iloc[0]
            leader_info = leader_df[leader_df['Group Leader ID'] == leader_id]
            
            leader_name = leader_info['Leader Name'].iloc[0] if not leader_info.empty else leader_id
            leader_contact = leader_info['Contact Number'].iloc[0] if not leader_info.empty else "N/A"

            if customer_message.lower() == "hello":
                response_text = f"Hi {customer_name}! I'm Leaf Plant AI. I can check stock or connect you to your Leader, **{leader_name}** ({leader_contact})."
            else:
                response_text = get_openai_response(customer_message, customer_name, leader_name, leader_contact)
            
            send_whatsapp_message(customer_number, response_text)
        else:
            send_whatsapp_message(customer_number, "Welcome! Please contact a Group Leader to join.")
    except Exception as e:
        print(f"Processing Error: {e}")

    time.sleep(1) 
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(port=5000, debug=True)