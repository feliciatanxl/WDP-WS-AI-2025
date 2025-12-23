from flask import Blueprint, render_template, request, session, redirect, url_for
from models import db, GroupLeader, WhatsAppOrder, Customer, WhatsAppLead
from datetime import datetime
import pytz

leader_bp = Blueprint('leader', __name__)

@leader_bp.route('/leader/dashboard')
def dashboard():
    # --- AUTHENTICATION CHECK ---
    # In a production app, you'd get the ID from the login session
    # For testing, we will grab the first leader in the database
    leader = GroupLeader.query.first()
    
    if not leader:
        return "No leader found in database. Please add one in Admin first."

    # --- 1. SYNC ORDERS ---
    # Fetch orders specifically for this leader's ID
    orders = WhatsAppOrder.query.filter_by(leader_id=leader.id)\
        .order_by(WhatsAppOrder.timestamp.desc()).all()

    # --- 2. SYNC NEIGHBORS (CUSTOMERS) ---
    # Fetch all customers assigned to this leader
    neighbors = Customer.query.filter_by(leader_id=leader.id).all()

    # --- 3. SYNC PENDING LEADS ---
    # If your AI hasn't converted them to customers yet, they are leads
    # We look for leads in the same neighborhood/area
    pending_leads = WhatsAppLead.query.filter(
        WhatsAppLead.neighborhood.ilike(f"%{leader.area}%"),
        WhatsAppLead.status == 'Awaiting Assignment'
    ).all()

    # --- 4. DYNAMIC CALCULATIONS ---
    # Total confirmed sales for this leader
    total_sales = sum(order.total_price for order in orders if order.order_status == 'Confirmed')
    
    # Calculate commission (11.1%)
    pending_commission = total_sales * 0.111
    
    # Today's order count (Singapore Time)
    sgt = pytz.timezone('Asia/Singapore')
    today_date = datetime.now(sgt).date()
    today_orders_count = sum(1 for order in orders if order.timestamp.date() == today_date)

    return render_template('leader.html', 
                           leader=leader, 
                           orders=orders, 
                           neighbors=neighbors, 
                           pending_leads=pending_leads,
                           total_sales=total_sales,
                           pending_commission=pending_commission,
                           today_orders_count=today_orders_count)