from flask import Blueprint, render_template, redirect, url_for, request, session
from models import db, ContactInquiry
from sqlalchemy import func

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/dashboard')
def dashboard():
    # 1. Get the Real-Time Newest ID (or 0)
    max_id_query = db.session.query(func.max(ContactInquiry.id)).scalar()
    current_real_max_id = int(max_id_query) if max_id_query else 0
    
    # 2. Initialize Snapshot (First Login)
    if 'visible_threshold_id' not in session:
        session['visible_threshold_id'] = current_real_max_id
        session['last_seen_id'] = current_real_max_id

    # 3. Handle Refresh Logic
    is_explicit_refresh = request.args.get('refresh') == 'true'

    if is_explicit_refresh:
        # UPDATE MEMORY:
        # 1. The items we saw *last time* (visible_threshold) are now considered "old" (last_seen).
        #    This clears the yellow highlight for items you've already looked at.
        session['last_seen_id'] = int(session['visible_threshold_id'])
        
        # 2. Update the snapshot to include the BRAND NEW items (Real Max).
        #    These will appear yellow because they are > the new last_seen_id.
        session['visible_threshold_id'] = current_real_max_id
    
    # 4. Filter the Database Query
    # Only show items allowed by the snapshot.
    visible_threshold = int(session['visible_threshold_id'])
    
    inquiries = ContactInquiry.query\
        .filter(ContactInquiry.id <= visible_threshold)\
        .order_by(ContactInquiry.created_at.desc())\
        .all()
        
    # Get the "old" memory to decide what to highlight yellow
    last_seen_id = int(session.get('last_seen_id', 0))

    return render_template('admin.html', inquiries=inquiries, last_seen_id=last_seen_id)

@admin_bp.route('/admin/delete/<int:id>', methods=['POST'])
def delete_inquiry(id):
    inquiry = ContactInquiry.query.get_or_404(id)
    try:
        db.session.delete(inquiry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
    return redirect(url_for('admin.dashboard') + '#customer-service')