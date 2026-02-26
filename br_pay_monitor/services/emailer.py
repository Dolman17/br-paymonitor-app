# br_pay_monitor/services/emailer.py

from typing import List, Optional, Tuple

from flask import current_app
from flask_mail import Message

from ..extensions import mail, db
from ..models import EmailLog, Brand


def send_html_email(
    subject: str,
    recipients: List[str],
    html_body: str,
    brand: Optional[Brand] = None,
) -> Tuple[bool, Optional[EmailLog]]:
    """
    Send a single HTML email to a list of recipients and record an EmailLog.

    Returns (success, EmailLog or None).
    """
    if not recipients:
        current_app.logger.warning("send_html_email called with no recipients.")
        return False, None

    if brand is None:
        from ..models import Brand as _Brand

        brand = _Brand.get_default_brand()

    sender = current_app.config.get("MAIL_DEFAULT_SENDER")
    if not sender:
        current_app.logger.error("MAIL_DEFAULT_SENDER is not configured.")
        return False, None

    log = EmailLog(
        brand=brand,
        subject=subject,
        to_count=len(recipients),
        html_size=len(html_body or ""),
        success=False,
    )
    db.session.add(log)
    db.session.flush()

    try:
        msg = Message(
            subject=subject,
            recipients=recipients,
            html=html_body,
            sender=sender,
        )
        mail.send(msg)
        log.success = True
        db.session.commit()
        return True, log
    except Exception as exc:  # broad catch is OK here; we log details
        current_app.logger.exception("Error sending email: %s", exc)
        log.success = False
        log.error_message = str(exc)
        db.session.commit()
        return False, log