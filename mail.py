from flask_mail import Mail, Message
from flask import current_app

mail = Mail()

def send_email(to, subject, template, cc=None, signature=None):
    """
    A helper function to send emails, with optional CC and signature.
    """
    app = current_app._get_current_object()
    msg = Message(
        subject,
        recipients=[to],
        html=template + (f"<br><br>{signature}" if signature else ""),
        sender=app.config['MAIL_DEFAULT_SENDER']
    )
    if cc:
        if isinstance(cc, str):
            msg.cc = [cc]
        elif isinstance(cc, list):
            msg.cc = cc
    mail.send(msg)

def send_otp_email(email, otp_code):
    subject = "Your OTP Code for Login"
    body = f"Your OTP code is: {otp_code}. It is valid for 10 minutes.\nIf you did not request this, please ignore this email."
    send_email(email, subject, body) 