"""
notifier.py
-----------
Envío de emails de alerta vía SMTP (Gmail por defecto).
Agrupa en un solo correo por alerta: novedades, BAJADAS DE PRECIO y bajas.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger("notifier")


def _format_price(p):
    return f"{p:.0f} €" if isinstance(p, (int, float)) else "Precio n/d"


def _badge(cat):
    """Etiqueta de color para LOTE / EXPANSIÓN (vacío para el resto)."""
    if cat == "lote":
        return ("<span style='background:#ffb703;color:#222;padding:2px 8px;"
                "border-radius:10px;font-size:12px'>LOTE</span> ")
    if cat == "expansion":
        return ("<span style='background:#8ecae6;color:#222;padding:2px 8px;"
                "border-radius:10px;font-size:12px'>EXPANSIÓN</span> ")
    return ""


def build_html(alert_name, new_items, sold_items, price_drops=None):
    price_drops = price_drops or []
    parts = [
        "<div style='font-family:Arial,sans-serif;max-width:600px'>",
        f"<h2 style='color:#13c1ac'>Alerta: {alert_name}</h2>",
    ]

    if new_items:
        parts.append("<h3>🆕 Nuevos anuncios</h3>")
        for it in new_items:
            badge = _badge(it.get("category", ""))
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

    if price_drops:
        parts.append("<h3>⬇️ Bajada de precio</h3>")
        for it in price_drops:
            badge = _badge(it.get("category", ""))
            old, new = it.get("old_price"), it.get("price")
            extra = (" <span style='color:#2a9d8f;font-size:12px'>"
                     "(ahora dentro de tu presupuesto)</span>"
                     if it.get("recovered") else "")
            old_html = (f"<span style='color:#b00;text-decoration:line-through;"
                        f"font-size:14px'>{_format_price(old)}</span> → "
                        if isinstance(old, (int, float)) else "")
            parts.append(
                f"<div style='border:1px solid #ffe0b2;background:#fff8f0;"
                f"border-radius:8px;padding:12px;margin-bottom:10px'>"
                f"{badge}<a href='{it['url']}' "
                f"style='font-size:16px;color:#222;text-decoration:none;"
                f"font-weight:bold'>{it['title']}</a>{extra}<br>"
                f"{old_html}<span style='color:#13c1ac;font-size:18px;"
                f"font-weight:bold'>{_format_price(new)}</span><br>"
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


def notify(config, alert_name, new_items, sold_items, price_drops=None):
    """Construye y envía el email si hay algo que reportar."""
    price_drops = price_drops or []
    if not new_items and not sold_items and not price_drops:
        return
    n_new, n_drop, n_sold = len(new_items), len(price_drops), len(sold_items)
    bits = []
    if n_new:
        bits.append(f"{n_new} nuevo{'s' if n_new != 1 else ''}")
    if n_drop:
        bits.append(f"{n_drop} bajada{'s' if n_drop != 1 else ''} de precio")
    if n_sold:
        bits.append(f"{n_sold} vendido{'s' if n_sold != 1 else ''}")
    subject = f"[Wallapop] {alert_name}: {', '.join(bits)}"
    html = build_html(alert_name, new_items, sold_items, price_drops)
    send_email(config, subject, html)
