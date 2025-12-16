import pandas as pd
import requests 
from flask import Flask, request, jsonify

# ==============================================================================
# 1. Configuration (CRITICAL: Fill in your specific values here)
# ==============================================================================

# 1.1. Your Permanent System User Access Token (PASTE YOUR LATEST TOKEN HERE)
YOUR_ACCESS_TOKEN = "EAAQUEA9objwBQOfM8zyMMTjYwlMP0sA5tCPcAcYP8I1occ5InZCNIKeunjDtUUpTm6zPtReWqX3fXkWyRZAF51eCYNuF5tRRELZC9H3fn6m40H6QzOPSFv2E2ZBcffTZCZBfnL4fcYIf6rzOYl8PBU1b7zjag48Tohzp4BYghZB3CkZBMml8N189VorClnjintEzfgZDZD"

# 1.2. Your Business Phone Number ID 
# (This is the 15-17 digit ID from Meta)
# !!! CORRECTED ID: THIS IS THE ID THAT WORKED IN YOUR CURL COMMAND !!!
PHONE_NUMBER_ID = "943273875531695" 

# 1.3. Webhook Verification Token 
# (MUST match the token you use in the Meta Developer Dashboard)
YOUR_VERIFY_TOKEN = "leaf_plant_secret_key" 

# Global variables to hold your dataframes (initialized to None)
inventory_df = None
customer_df = None
leader_df = None

# --- Application Setup ---
app = Flask(__name__)

# ==============================================================================
# 2. Data Loading Function
# ==============================================================================

def load_excel_data():
    """Loads data from three separate .xlsx files into pandas DataFrames."""
    global inventory_df, customer_df, leader_df
    
    # NOTE: These file paths MUST EXACTLY match the names of the 3 .xlsx files 
    # in your project folder.
    INVENTORY_FILE = 'Inventory and Stock Status.xlsx' 
    CUSTOMER_FILE = 'Customer and Group Leader Mapping.xlsx' 
    LEADER_FILE = 'Group Leader Summary.xlsx' 

    try:
        # pd.read_excel is used for reading .xlsx files
        inventory_df = pd.read_excel(INVENTORY_FILE)
        customer_df = pd.read_excel(CUSTOMER_FILE)
        leader_df = pd.read_excel(LEADER_FILE)
        
        # Ensure the WA Phone Number column is treated as a string for accurate lookup
        customer_df['WA Phone Number'] = customer_df['WA Phone Number'].astype(str)
        
        print("\n--- Data Loading Success ---")
        print(f"Inventory Rows: {len(inventory_df)}")
        print(f"Customer Rows: {len(leader_df)}") # Corrected: Prints number of rows for leader_df
        print(f"Leader Rows: {len(leader_df)}")
        print("----------------------------\n")
        
    except FileNotFoundError as e:
        print(f"FATAL ERROR: A data file was not found. Please check your filenames and ensure all 3 .xlsx files are in the same folder as app.py. Error: {e}")
    except Exception as e:
        print(f"FATAL ERROR loading data. Check Excel format or column names: {e}")

# Execute data loading when the script starts
load_excel_data()


# ==============================================================================
# 3. Message Sending Function (Handles API POST Request)
# ==============================================================================

def send_whatsapp_message(to_number, message_body):
    """Sends a free-form text message to a customer using the Meta Cloud API."""
    
    # API_URL now uses the CORRECTED PHONE_NUMBER_ID
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
        response.raise_for_status() # Raise exception for 4xx/5xx status codes
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
# 4. Webhook Endpoints (GET and POST) - FINAL CORRECTED LOGIC
# ==============================================================================

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """Handles the Meta GET request for verification."""
    # Check if the hub.verify_token matches your secret
    if request.args.get("hub.verify_token") == YOUR_VERIFY_TOKEN:
        print("Webhook verified by Meta!")
        # Respond with the hub.challenge to complete verification
        return request.args.get("hub.challenge"), 200
    
    return "Verification token mismatch", 403

@app.route('/webhook', methods=['POST'])
def handle_message():
    """Handles all incoming customer messages and processes the AI logic."""
    data = request.get_json()
    
    # --- JSON Parsing (Safety Checks) ---
    try:
        entry = data['entry'][0]
        change = entry['changes'][0]
        value = change['value']
        
        # Check if the event is an incoming message
        if 'messages' not in value:
            return jsonify({"status": "no message event"}), 200

        message_data = value['messages'][0]
        customer_number = message_data['from']
        
        if message_data['type'] == 'text':
            customer_message = message_data['text']['body']
        else:
            customer_message = "NOT_TEXT_MESSAGE"

    except (KeyError, IndexError):
        print("Received malformed webhook data.")
        return jsonify({"status": "malformed data"}), 200
        
    print(f"\n--- INBOUND MESSAGE ---")
    print(f"From: {customer_number}")
    print(f"Message: {customer_message}")

    # --- AI Logic & Data Lookup (CORRECTED) ---
    try:
        # 1. Find the customer in the Customer DF
        customer_info = customer_df[customer_df['WA Phone Number'] == customer_number]

        if not customer_info.empty:
            # Customer found: retrieve customer name and leader ID
            customer_name = customer_info['Customer ID'].iloc[0] 
            leader_id = customer_info['Group Leader ID'].iloc[0]
            
            # --- STEP 2. Find Group Leader Info using the leader_id ---
            leader_info = leader_df[leader_df['Group Leader ID'] == leader_id]
            
            # --- ERROR FIX SECTION: Assumes 'Leader Name' and 'Contact Number' ---
            if not leader_info.empty:
                
                # *** FINAL FIX FOR COLUMN NAME: Assuming 'Leader Name' or falling back ***
                try:
                    # Attempt 1: Try the most likely correct name 'Leader Name'
                    leader_name = leader_info['Leader Name'].iloc[0] 
                except KeyError:
                    # Attempt 2: Fallback to the ID if 'Leader Name' is incorrect
                    print(f"WARNING: Column 'Leader Name' not found in Summary. Falling back to Leader ID: {leader_id}")
                    leader_name = leader_id 
                
                # Check for Contact Number
                try:
                    leader_contact = leader_info['Contact Number'].iloc[0]
                except KeyError:
                    print(f"WARNING: Column 'Contact Number' not found in Summary. Using N/A.")
                    leader_contact = "N/A"
            else:
                # If the Leader ID isn't found at all in the Summary file
                leader_name = "N/A (Leader Not Found)"
                leader_contact = "N/A"
            
            # 1. Stock Inquiry Logic (e.g., 'tomato')
            if "tomato" in customer_message.lower():
                
                # Check Inventory (Sheet 1)
                stock_result = inventory_df[inventory_df['Product Name'].str.contains('Tomato', case=False, na=False)]
                
                if not stock_result.empty:
                    stock_status = stock_result['Stock Status'].iloc[0]
                    # Update response with full leader name and contact
                    response_text = f"Hello {customer_name}, thanks for asking! The Heirloom Tomato is currently **{stock_status}**. Your Group Leader, **{leader_name}** ({leader_contact}), can assist with ordering."
                else:
                    response_text = f"Hello {customer_name}, I can't find Tomato in the current inventory list. Can you try a different product?"

            # 2. Handle non-text messages
            elif customer_message == "NOT_TEXT_MESSAGE":
                response_text = "I'm sorry, I can only process text messages right now. Please type your request."

            # 3. Fallback Response (e.g., 'hello')
            else:
                # Update fallback response with full leader name and contact
                response_text = f"Hi {customer_name}! I am the Leaf Plant AI. I can check stock (e.g., 'Do you have tomato?') or connect you to your Group Leader, **{leader_name}** ({leader_contact}). How can I help?"

            # Send the AI response back to the customer
            send_whatsapp_message(customer_number, response_text)

        else:
            # Handle new, unrecognized customers
            send_whatsapp_message(customer_number, "Welcome to Leaf Plant! I see you are a new customer. To start an order, please contact one of our Group Leaders first.")

    except Exception as e:
        print(f"Logic Error during message processing: {e}")
        # Send a generic error message
        send_whatsapp_message(customer_number, "Oops! My AI brain hit a snag. Please try again in a moment.")

    # --- MANDATORY: Must return 200 OK to prevent Meta from retrying ---
    return jsonify({"status": "ok"}), 200

# ==============================================================================
# 5. Running the Application
# ==============================================================================

if __name__ == '__main__':
    # Run the app locally on port 5000 
    app.run(port=5000, debug=True)