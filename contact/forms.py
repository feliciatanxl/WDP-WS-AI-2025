from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional

class ContactForm(FlaskForm):
    # Name: Required, 2-100 characters
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
    
    # Email: Required, Valid Format
    email = StringField('Email', validators=[DataRequired(), Email()])
    
    # Phone: Optional, Max 20 characters
    phone = StringField('Phone', validators=[Optional(), Length(max=20)])
    
    # Message: Required, Min 10 characters
    message = TextAreaField('Message', validators=[DataRequired(), Length(min=10)])
    
    submit = SubmitField('Send')