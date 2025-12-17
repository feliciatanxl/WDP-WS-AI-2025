import pandas as pd
import requests 
from flask import Flask, request, jsonify
from google import genai
from google.genai import types 
import time # Added for potential debugging

# ==============================================================================
# 1. Configuration (CRITICAL: Fill in your specific values here)
# ==============================================================================

# 1.1. Your Permanent System User Access Token (PASTE YOUR LATEST TOKEN HERE)
YOUR_ACCESS_TOKEN = "EAAQUEA9objwBQOfM8zyMMTjYwlMP0sA5tCPcAcYP8I1occ5InZCNIKeunjDtUUpTm6zPtReWqX3fXkWyRZAF51eCYNuF5tRRELZC9H3fn6m40H6QzOPSFv2E2ZBcffTZCZBfnL4fcYIf6rzOYl8PBU1b7zjag48Tohzp4BYghZB3CkZBMml8N189VorClnjintEzfgZDZD"

# 1.2. Your Business Phone Number ID 
PHONE_NUMBER_ID = "943273875531695" 

# 1.3. Webhook Verification Token 
YOUR_VERIFY_TOKEN = "leaf_plant_secret_key" 

# 1.4. Gemini AI Configuration (PASTE YOUR KEY HERE!)
GEMINI_API_KEY = "#" 

# Global variables to hold your dataframes (initialized to None)
inventory_df = None
customer_df = None
leader_df = None

# Set to store IDs of messages that have already been processed
processed_messages = set()

# --- Application Setup ---
app = Flask(__name__)

# Initialize the Gemini Client
try:
    # Use the key you pasted in 1.4
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"FATAL ERROR: Could not initialize Gemini Client. Check GEMINI_API_KEY. Error: {e}")
    gemini_client = None


# ==============================================================================
# 2. Data Loading Function (No Change)
# ==============================================================================

def load_excel_data():
    """Loads data from three separate .xlsx files into pandas DataFrames."""
    global inventory_df, customer_df, leader_df
    
    INVENTORY_FILE = 'Inventory and Stock Status.xlsx' 
    CUSTOMER_FILE = 'Customer and Group Leader Mapping.xlsx' 
    LEADER_FILE = 'Group Leader Summary.xlsx' 

    try:
        inventory_df = pd.read_excel(INVENTORY_FILE)
        customer_df = pd.read_excel(CUSTOMER_FILE)
        leader_df = pd.read_excel(LEADER_FILE)
        
        customer_df['WA Phone Number'] = customer_df['WA Phone Number'].astype(str)
        
        print("\n--- Data Loading Success ---")
        print(f"Inventory Rows: {len(inventory_df)}")
        print(f"Customer Rows: {len(customer_df)}")
        print(f"Leader Rows: {len(leader_df)}")
        print("----------------------------\n")
        
    except FileNotFoundError as e:
        print(f"FATAL ERROR: A data file was not found. Please check your filenames and ensure all 3 .xlsx files are in the same folder as app.py. Error: {e}")
    except Exception as e:
        print(f"FATAL ERROR loading data. Check Excel format or column names: {e}")

# Execute data loading when the script starts
load_excel_data()


# ==============================================================================
# 3. Message Sending Function (No Change)
# ==============================================================================

def send_whatsapp_message(to_number, message_body):
    """Sends a free-form text message to a customer using the Meta Cloud API."""
    
    API_URL = f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {YOUR_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": { "body": message_body }
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload)
        response.raise_for_status() 
        print(f"Message sent successfully to {to_number}. Status: {response.status_code}")
        return response.json()
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error sending message: {err}")
        print(f"Response Body: {response.text}")
        return None
    except Exception as err:
        print(f"An unexpected error occurred during message send: {err}")
        return None


# ==============================================================================
# 4. Generative AI Processing Function (Only called for complex requests)
# ==============================================================================

def get_gemini_response(customer_message, customer_name, leader_name, leader_contact):
    """Generates an intelligent response using the Gemini API based on customer context."""
    
    # Check if client initialized (key is present)
    if not gemini_client:
        return "AI is offline. Please check the console for the Gemini API key error."

    # 1. Gather relevant data from the inventory (focused on 'Tomato' for now)
    stock_result = inventory_df[inventory_df['Product Name'].str.contains('Tomato', case=False, na=False)]
    stock_status = stock_result['Stock Status'].iloc[0] if not stock_result.empty else "Out of Stock"
    
    # 2. Construct the detailed prompt (the 'context' for the AI)
    system_prompt = f"""
    You are 'Leaf Plant AI', a friendly and professional customer service agent for a group buying service. 
    Your primary goal is to answer questions, check stock, and direct customers to their Group Leader for ordering.
    
    Use the following customer and stock data to generate a helpful, conversational response:
    - Customer Name: {customer_name}
    - Group Leader Name: {leader_name}
    - Group Leader Contact: {leader_contact}
    - Inventory Data (Heirloom Tomato): {stock_status}

    RULES:
    1. Always address the customer by name.
    2. If the customer asks about stock for 'tomato' or a similar keyword, provide the stock status and clearly state that the Leader handles orders.
    3. If the stock is 'In Stock', phrase the answer positively.
    4. If the stock is 'Out of Stock', suggest they contact the Leader for the next shipment estimate.
    5. For generic messages (like 'hello' or greetings), use the fallback response format below.
    6. For non-text messages, use the NOT_TEXT_MESSAGE response.

    FALLBACK RESPONSE: "Hi {customer_name}! I am the Leaf Plant AI. I can check stock (e.g., 'Do you have tomato?') or connect you to your Group Leader, {leader_name} ({leader_contact}). How can I help?"
    NOT_TEXT_MESSAGE RESPONSE: "I'm sorry, I can only process text messages right now. Please type your request."
    """
    
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=customer_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt
            )
        )
        return response.text
        
    except Exception as e:
        print(f"Gemini API Error: {e}")
        # Send a response that indicates the AI failed, but the system is alive
        return "Oops! My AI brain hit a snag (rate limit exceeded). Please try a different message in a minute."


# ==============================================================================
# 5. Webhook Endpoints (GET and POST) - FINAL LOGIC WITH FALLBACK
# ==============================================================================

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """Handles the Meta GET request for verification."""
    if request.args.get("hub.verify_token") == YOUR_VERIFY_TOKEN:
        print("Webhook verified by Meta!")
        return request.args.get("hub.challenge"), 200
    
    return "Verification token mismatch", 403

@app.route('/webhook', methods=['POST'])
def handle_message():
    """Handles all incoming customer messages and processes the AI logic."""
    global processed_messages
    data = request.get_json()
    
    # --- JSON Parsing (Safety Checks) ---
    try:
        entry = data['entry'][0]
        change = entry['changes'][0]
        value = change['value']
        
        if 'messages' not in value:
            return jsonify({"status": "no message event"}), 200

        message_data = value['messages'][0]
        customer_number = message_data['from']
        message_id = message_data['id']
        
        if message_data['type'] == 'text':
            customer_message = message_data['text']['body']
        else:
            customer_message = "NOT_TEXT_MESSAGE"

    except (KeyError, IndexError):
        print("Received malformed webhook data.")
        return jsonify({"status": "malformed data"}), 200
        
    
    # --- DE-DUPLICATION CHECK ---
    if message_id in processed_messages:
        print(f"--- IGNORED DUPLICATE MESSAGE --- ID: {message_id}")
        return jsonify({"status": "duplicate message ignored"}), 200
    
    processed_messages.add(message_id) 
    
    
    print(f"\n--- INBOUND MESSAGE ---")
    print(f"From: {customer_number}")
    print(f"Message: {customer_message}")

    # --- AI Logic & Data Lookup ---
    try:
        customer_info = customer_df[customer_df['WA Phone Number'] == customer_number]

        if not customer_info.empty:
            customer_name = customer_info['Customer ID'].iloc[0] 
            leader_id = customer_info['Group Leader ID'].iloc[0]
            
            leader_info = leader_df[leader_df['Group Leader ID'] == leader_id]
            
            # --- Leader Lookup Logic (Get personalized data) ---
            if not leader_info.empty:
                try:
                    leader_name = leader_info['Leader Name'].iloc[0] 
                except KeyError:
                    leader_name = leader_id 
                
                try:
                    leader_contact = leader_info['Contact Number'].iloc[0]
                except KeyError:
                    leader_contact = "N/A"
            else:
                leader_name = "N/A (Leader Not Found)"
                leader_contact = "N/A"

            # --- CHECK FOR SIMPLE GREETING (BYPASS GEMINI TO PREVENT 429) ---
            if customer_message.lower() == "hello":
                 response_text = f"Hi {customer_name}! I am the Leaf Plant AI. I can check stock (e.g., 'Do you have tomato?') or connect you to your Group Leader, **{leader_name}** ({leader_contact}). How can I help?"
                 
            # --- FULL GEMINI LOGIC FOR ALL OTHER MESSAGES ---
            else:
                # Send the message and all personalized data to Gemini for intelligent processing
                response_text = get_gemini_response(customer_message, customer_name, leader_name, leader_contact)
            
            # Send the response back to the customer
            send_whatsapp_message(customer_number, response_text)

        else:
            # Handle new, unrecognized customers
            send_whatsapp_message(customer_number, "Welcome to Leaf Plant! I see you are a new customer. To start an order, please contact one of our Group Leaders first.")

    except Exception as e:
        print(f"Logic Error during message processing: {e}")
        send_whatsapp_message(customer_number, "Oops! A system error occurred during processing.")

    # --- MANDATORY: Must return 200 OK to prevent Meta from retrying ---
    # ADDED a short delay to maximize chance of 200 being received before Meta retries.
    time.sleep(1) 
    return jsonify({"status": "ok"}), 200

# ==============================================================================
# 6. Running the Application
# ==============================================================================

if __name__ == '__main__':
    # Run the app locally on port 5000 
    app.run(port=5000, debug=True)