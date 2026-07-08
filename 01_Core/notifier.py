"""
notifier.py
-----------
Envío de emails de alerta vía SMTP (Gmail por defecto).
Agrupa en un solo correo por alerta: novedades, BAJADAS y SUBIDAS de precio.
Los anuncios retirados/vendidos NO se notifican.
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


def build_html(alert_name, new_items, price_drops=None, price_rises=None):
    price_drops = price_drops or []
    price_rises = price_rises or []
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

    if price_rises:
        parts.append("<h3>⬆️ Subida de precio</h3>")
        for it in price_rises:
            badge = _badge(it.get("category", ""))
            old, new = it.get("old_price"), it.get("price")
            old_html = (f"<span style='color:#2a9d8f;text-decoration:line-through;"
                        f"font-size:14px'>{_format_price(old)}</span> → "
                        if isinstance(old, (int, float)) else "")
            parts.append(
                f"<div style='border:1px solid #f3c7c7;background:#fdf4f4;"
                f"border-radius:8px;padding:12px;margin-bottom:10px'>"
                f"{badge}<a href='{it['url']}' "
                f"style='font-size:16px;color:#222;text-decoration:none;"
                f"font-weight:bold'>{it['title']}</a><br>"
                f"{old_html}<span style='color:#b00;font-size:18px;"
                f"font-weight:bold'>{_format_price(new)}</span><br>"
                f"<a href='{it['url']}' style='color:#888;font-size:13px'>"
                f"Ver en Wallapop →</a></div>"
            )

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
            # La variable de entorno (GitHub Secret) es la fuente real; el
            # YAML de usuario ya no lleva contraseña (ver _schema_problems).
            srv.login(em["sender"],
                      os.getenv("GMAIL_APP_PASSWORD") or em.get("app_password"))
            srv.sendmail(em["sender"], [em["recipient"]], msg.as_string())
        log.info("Email enviado: %s", subject)
        return True
    except Exception as e:
        log.error("No se pudo enviar el email: %s", e)
        return False


def _count_bits(n_new, n_drop, n_rise):
    """Trozos legibles para el asunto: '2 nuevos, 1 bajada de precio'."""
    bits = []
    if n_new:
        bits.append(f"{n_new} nuevo{'s' if n_new != 1 else ''}")
    if n_drop:
        bits.append(f"{n_drop} bajada{'s' if n_drop != 1 else ''} de precio")
    if n_rise:
        bits.append(f"{n_rise} subida{'s' if n_rise != 1 else ''} de precio")
    return bits


def notify(config, alert_name, new_items, price_drops=None, price_rises=None):
    """Construye y envía un email por alerta si hay algo que reportar."""
    price_drops = price_drops or []
    price_rises = price_rises or []
    if not new_items and not price_drops and not price_rises:
        return
    bits = _count_bits(len(new_items), len(price_drops), len(price_rises))
    subject = f"[Wallapop] {alert_name}: {', '.join(bits)}"
    html = build_html(alert_name, new_items, price_drops, price_rises)
    send_email(config, subject, html)


def notify_digest(config, sections):
    """Un solo email con todas las alertas del usuario que tienen novedades.

    `sections`: lista de dicts {name, new, drops, rises}. Solo se envía si al
    menos una alerta tiene contenido. El cuerpo concatena el bloque HTML de
    cada alerta (reutiliza build_html); el asunto agrega los totales.
    """
    active = [s for s in sections if s.get("new") or s.get("drops") or s.get("rises")]
    if not active:
        return
    n_new = sum(len(s.get("new") or []) for s in active)
    n_drop = sum(len(s.get("drops") or []) for s in active)
    n_rise = sum(len(s.get("rises") or []) for s in active)
    bits = _count_bits(n_new, n_drop, n_rise)
    n_alerts = len(active)
    subject = (f"[Wallapop] Resumen: {', '.join(bits)} — "
               f"{n_alerts} alerta{'s' if n_alerts != 1 else ''}")
    blocks = [
        build_html(s["name"], s.get("new") or [],
                   s.get("drops") or [], s.get("rises") or [])
        for s in active
    ]
    html = ("<div style='font-family:Arial,sans-serif;max-width:600px'>"
            "<h1 style='color:#13c1ac;font-size:20px'>Resumen de tus alertas</h1>"
            + "<hr style='border:none;border-top:1px solid #eee;margin:16px 0'>".join(blocks)
            + "</div>")
    send_email(config, subject, html)
