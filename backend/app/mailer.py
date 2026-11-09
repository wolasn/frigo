"""Envoi d'e-mails par Gmail (mot de passe d'application), pour les alertes du super-administrateur.

Adresse d'envoi, mot de passe et adresse du super-administrateur sont des secrets Docker,
lus hors de la base pour que l'alerte parte même quand la base est bloquée.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.secrets import read_secret

logger = logging.getLogger("frigo.mailer")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class MailNotConfigured(RuntimeError):
    pass


class MailError(RuntimeError):
    pass


def send_admin_email(subject: str, body: str) -> None:
    sender = read_secret("smtp_sender")
    password = read_secret("smtp_password")
    recipient = read_secret("admin_email")
    if not (sender and password and recipient):
        raise MailNotConfigured("Secrets smtp_sender, smtp_password ou admin_email manquants.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"[Frigo & Repas] {subject}"
    message.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            # PLAIN en premier : Gmail le propose toujours (Google affiche le mot de passe par blocs).
            smtp.user, smtp.password = sender, password.replace(" ", "")
            smtp.auth("PLAIN", smtp.auth_plain, initial_response_ok=True)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise MailError(
            "Gmail refuse l'identifiant ou le mot de passe : vérifie que smtp_password est un mot de passe "
            "d'application créé sur le même compte que smtp_sender."
        ) from None
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(f"Envoi impossible ({type(error).__name__}).") from None
    logger.info("E-mail envoyé au super-administrateur : %s", subject)  # jamais l'adresse dans les journaux
