from flask import Blueprint, render_template, redirect, url_for, request, session
from models import db, ContactInquiry

# 1. Create the Blueprint
admin_bp = Blueprint('admin', __name__)

# 2. Define the Dashboard Route (FIXED LOGIC)
@admin_bp.route('/admin/dashboard')
def dashboard():
    # Fetch all messages from the database, newest first
    inquiries = ContactInquiry.query.order_by(ContactInquiry.created_at.desc()).all()
    
    # Get the ID of the newest message (or 0 if empty)
    current_max_id = inquiries[0].id if inquiries else 0
    
    # --- INTELLIGENT HIGHLIGHT LOGIC ---
    
    # Check if the URL has '?refresh=true' (This only happens if you click the button)
    is_explicit_refresh = request.args.get('refresh') == 'true'
    
    if is_explicit_refresh:
        # CASE A: You clicked "Refresh List"
        # We want to highlight items that are newer than what you saw last time.
        threshold_id = session.get('last_seen_id', 0)
        
        # Now update the session so if you refresh AGAIN, they stop being yellow
        session['last_seen_id'] = current_max_id
    else:
        # CASE B: First login, tab switch, or normal page load
        # Assume you see everything currently on screen. No highlights.
        threshold_id = current_max_id
        session['last_seen_id'] = current_max_id
        
    # Send inquiries AND the threshold ID to the template
    return render_template('admin.html', inquiries=inquiries, last_seen_id=threshold_id)

# 3. Define the Delete Route
@admin_bp.route('/admin/delete/<int:id>', methods=['POST'])
def delete_inquiry(id):
    inquiry = ContactInquiry.query.get_or_404(id)
    try:
        db.session.delete(inquiry)
        db.session.commit()
        print(f"Deleted inquiry #{id}")
    except Exception as e:
        print(f"Error deleting inquiry: {e}")
        db.session.rollback()
    
    # Redirect back to the dashboard tab
    return redirect(url_for('admin.dashboard') + '#customer-service')