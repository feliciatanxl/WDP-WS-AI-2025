from flask import Blueprint, render_template, request, jsonify
from models import db, ContactInquiry 

# FIX: Remove template_folder='.' so it looks in the global templates folder
contact_bp = Blueprint('contact', __name__)

@contact_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    # Initialize empty dictionaries to prevent "UndefinedError" in the HTML
    errors = {}
    form_data = {}

    if request.method == 'POST':
        # Get data from the form
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        message = request.form.get('message')
        
        # Store current data to send back if there is an error (sticky form)
        form_data = request.form

        # --- SERVER-SIDE VALIDATION ---
        if not name or len(name.strip()) < 2:
            errors['name'] = "Full name is required."
        if not email or "@" not in email:
            errors['email'] = "A valid email is required."
        if not message or len(message.strip()) < 10:
            errors['message'] = "Message must be at least 10 characters."

        # If there are validation errors, re-render the form
        if errors:
            # Looks in /templates/contact.html
            return render_template('contact.html', errors=errors, form_data=form_data)

        # --- DATABASE LOGIC (The 'C' in CRUD) ---
        try:
            new_inquiry = ContactInquiry(name=name, email=email, phone=phone, message=message)
            db.session.add(new_inquiry)
            db.session.commit()
            
            return "Success", 200
            
        except Exception as e:
            db.session.rollback()
            return f"Database Error: {str(e)}", 500

    # GET request: loads the page
    return render_template('contact.html', errors=errors, form_data=form_data)