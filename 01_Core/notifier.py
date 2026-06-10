"""
notifier.py
-----------
Envío de emails de alerta vía SMTP (Gmail por defecto).
Agrupa novedades y bajas en un solo correo por alerta.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger("notifier")


def _format_price(p):
    return f"{p:.0f} €" if isinstance(p, (int, float)) else "Precio n/d"


def build_html(alert_name, new_items, sold_items):
    parts = [
        "<div style='font-family:Arial,sans-serif;max-width:600px'>",
        f"<h2 style='color:#13c1ac'>Alerta: {alert_name}</h2>",
    ]

    if new_items:
        parts.append("<h3>🆕 Nuevos anuncios</h3>")
        for it in new_items:
            cat = it.get("category", "")
            badge = ""
            if cat == "lote":
                badge = ("<span style='background:#ffb703;color:#222;"
                         "padding:2px 8px;border-radius:10px;font-size:12px'>"
                         "LOTE</span> ")
            elif cat == "expansion":
                badge = ("<span style='background:#8ecae6;color:#222;"
                         "padding:2px 8px;border-radius:10px;font-size:12px'>"
                         "EXPANSIÓN</span> ")
            parts.append(
                f"<div style='border:1px solid #eee;border-radius:8px;"
                f"padding:12px;margin-bottom:10px'>"
                f"{badge}<a href='{it['url']}' "
                f"style='font-size:16px;color:#222;text-decoration:none;"
                f"font-weight:bold'>{it['title']}</a><br>"
                f"<span style='color:#13c1ac;font-size:18px'>"
                f"{_format_price(it['price'])}</span><br>"
                f"<a href='{it['url']}' style='color:#888;font-size:13px'>"
                f"Ver en Wallapop →</a></div>"
            )

    if sold_items:
        parts.append("<h3>✅ Ya no disponibles (vendidos/retirados)</h3>")
        parts.append("<ul>")
        for it in sold_items:
            parts.append(
                f"<li>{it.get('title','(sin título)')} "
                f"— {_format_price(it.get('price'))}</li>"
            )
        parts.append("</ul>")

    parts.append("</div>")
    return "".join(parts)


def send_email(config, subject, html_body):
    em = config["email"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = em["sender"]
    msg["To"] = em["recipient"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(em["smtp_host"], em["smtp_port"], timeout=30) as srv:
            srv.starttls()
            # La variable de entorno (cloud) tiene prioridad sobre el YAML.
            srv.login(em["sender"],
                      os.getenv("GMAIL_APP_PASSWORD") or em["app_password"])
            srv.sendmail(em["sender"], [em["recipient"]], msg.as_string())
        log.info("Email enviado: %s", subject)
        return True
    except Exception as e:
        log.error("No se pudo enviar el email: %s", e)
        return False


def notify(config, alert_name, new_items, sold_items):
    """Construye y envía el email si hay algo que reportar."""
    if not new_items and not sold_items:
        return
    n_new = len(new_items)
    n_sold = len(sold_items)
    bits = []
    if n_new:
        bits.append(f"{n_new} nuevo{'s' if n_new != 1 else ''}")
    if n_sold:
        bits.append(f"{n_sold} vendido{'s' if n_sold != 1 else ''}")
    subject = f"[Wallapop] {alert_name}: {', '.join(bits)}"
    html = build_html(alert_name, new_items, sold_items)
    send_email(config, subject, html)
