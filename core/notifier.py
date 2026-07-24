"""Notification e-mail du brief — utilise notifications.email de config.yaml.

Désactivé par défaut (enabled: false). Supporte SSL implicite (port 465)
et STARTTLS (587). Le corps est le brief converti en HTML minimal.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import yaml


def _load_email_cfg(config_path: str) -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return (raw.get("notifications") or {}).get("email") or {}
    except Exception:
        return {}


def send_brief(brief_path: str, config_path: str = "config.yaml",
               subject_prefix: str = "📡 Brief de veille") -> Optional[str]:
    """Envoie le brief par e-mail si notifications.email.enabled est vrai.
    Retourne un message d'erreur, ou None si envoyé/désactivé."""
    cfg = _load_email_cfg(config_path)
    if not cfg.get("enabled"):
        return None

    host = cfg.get("smtp_host", "")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "") or os.getenv("SMTP_USER", "")
    password = cfg.get("smtp_password", "") or os.getenv("SMTP_PASSWORD", "")
    sender = cfg.get("from", user)
    to = cfg.get("to", "")
    if not (host and user and password and to):
        return "config e-mail incomplète (smtp_host/smtp_user/smtp_password/to)"

    try:
        with open(brief_path, "r", encoding="utf-8") as f:
            md = f.read()
        try:
            import markdown
            body_html = markdown.markdown(md, extensions=["extra", "nl2br"])
        except ImportError:
            body_html = f"<pre>{md}</pre>"

        name = os.path.basename(brief_path)
        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = f"{subject_prefix} — {name.replace('brief_veille_', '').replace('.md', '')}"
        msg.attach(MIMEText(md, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as srv:
                srv.login(user, password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as srv:
                srv.starttls()
                srv.login(user, password)
                srv.send_message(msg)

        print(f"   📧 Brief envoyé à {to}")
        return None
    except Exception as e:
        err = f"envoi e-mail échoué : {e}"
        print(f"   ⚠️  [Notifier] {err}")
        return err
