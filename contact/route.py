from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, ContactInquiry 

contact_bp = Blueprint('contact', __name__, template_folder='.')

@contact_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        message = request.form.get('message')

        # --- SERVER-SIDE VALIDATION
        errors = {}
        if not name or len(name) < 2:
            errors['name'] = "Full name is required."
        if not email or "@" not in email:
            errors['email'] = "A valid email is required."
        if not message or len(message) < 10:
            errors['message'] = "Message must be at least 10 characters."

        if errors:
            return render_template('contact.html', errors=errors, form_data=request.form)

        # --- CREATE (The 'C' in CRUD) --- 
        try:
            new_inquiry = ContactInquiry(name=name, email=email, phone=phone, message=message)
            db.session.add(new_inquiry)
            db.session.commit()
            # Pass the ID to the thank you page via URL 
            return redirect(url_for('contact.thankyou', inquiry_id=new_inquiry.id))
        except Exception as e:
            db.session.rollback()
            return f"Database Error: {str(e)}"

    return render_template('contact.html', errors={}, form_data={})

@contact_bp.route('/thankyou/<int:inquiry_id>')
def thankyou(inquiry_id):
    # --- RETRIEVE (The 'R' in CRUD) --- 
    inquiry = ContactInquiry.query.get_or_404(inquiry_id)
    return render_template('thankyou.html', inquiry=inquiry)