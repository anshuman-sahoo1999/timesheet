from flask_mail import Mail, Message
from flask import current_app

mail = Mail()


def send_email(to, subject, template, cc=None, signature=None, step_key=None):
    """
    A helper function to send emails, with optional CC, signature, and IT Admin
    global / per-step email gating.
    Returns True if dispatched, False if blocked by IT Admin toggles or invalid recipient.
    """
    if not to or '@' not in str(to):
        return False

    try:
        from app import is_email_communication_allowed
        allowed, reason = is_email_communication_allowed(step_key)
        if not allowed:
            print(f"[MAIL_SKIPPED] ({reason}) to={to}, subject={subject}")
            return False
    except Exception as gate_err:
        # Fail-open only if helper isn't initialized yet; log warning
        print(f"[MAIL_GATE_WARN] {gate_err}")

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
    return True


def send_otp_email(email, otp_code):
    subject = "Your OTP Code for Login"
    body = f"Your OTP code is: {otp_code}. It is valid for 10 minutes.\nIf you did not request this, please ignore this email."
    return send_email(email, subject, body, step_key='otp_login')