import os
import sys

import requests
from django.conf import settings
from django.utils import timezone


def _get_secret():
    """Read APPS_SCRIPT_SECRET from the environment, stripping surrounding quotes."""
    secret = os.environ.get("APPS_SCRIPT_SECRET", "")
    if secret:
        secret = secret.strip().strip('"').strip("'")
    return secret


def export_to_google_sheets(category, records, spreadsheet_id=None, branch_code=None,
                            branch_name=None):
    """Export exactly one filtered history category to the Apps Script web app."""
    if category not in {"supplies", "accessories"}:
        raise ValueError("History exports must be supplies or accessories.")

    records = list(records)
    if ("test" in sys.argv or "test_coverage" in sys.argv) and not hasattr(requests.post, "mock_calls"):
        print("[GOOGLE SHEETS EXPORT] Mocking export for test run (not patched)", flush=True)
        return {"success": True}

    url = (os.environ.get("GOOGLE_SHEETS_EXPORT_URL") or os.environ.get("GOOGLE_APPS_SCRIPT_URL")
           or getattr(settings, "GOOGLE_SHEETS_EXPORT_URL", None))
    if url:
        url = url.strip().strip('"').strip("'")
    if not url:
        raise ValueError("GOOGLE_APPS_SCRIPT_URL environment variable is not set")

    status_map = {
        "RED": "LOW", "OUT_OF_STOCK": "LOW", "YELLOW": "MODERATE",
        "GREEN": "SUFFICIENT", "NORMAL": "SUFFICIENT", "No Base Stock": "NO BASE",
    }
    formatted_records = []
    for record in records:
        record_date = getattr(record, "date", None)
        if record_date is None and getattr(record, "created_at", None):
            record_date = record.created_at.date()
        date_str = record_date.strftime("%Y-%m-%d") if record_date else timezone.now().strftime("%Y-%m-%d")
        base_stock = float(record.base_stock or 0)
        closing_stock = float(
            record.closing_stock if hasattr(record, "closing_stock") else record.new_quantity
        )
        remaining = record.remaining_percentage
        status = getattr(record, "status", None)
        if status is None:
            if remaining is None:
                status = "No Base Stock"
            elif remaining >= 80:
                status = "GREEN"
            elif remaining > 10:
                status = "YELLOW"
            else:
                status = "RED"
        formatted_records.append({
            "date": date_str,
            "product": record.product.name,
            "base_stock": int(base_stock) if base_stock.is_integer() else base_stock,
            "closing_stock": int(closing_stock) if closing_stock.is_integer() else closing_stock,
            "remaining_percentage": f"{float(remaining):.0f}%" if remaining is not None else "—",
            "status": status_map.get(status, status),
        })

    if not branch_code and records:
        branch = getattr(records[0], "branch", None)
        branch_code = branch.branch_code if branch else None
        branch_name = branch_name or (branch.branch_name if branch else None)
    if not branch_code:
        raise ValueError("A branch ID is required for a history export.")
    if not spreadsheet_id:
        raise ValueError("A branch spreadsheet ID is required for a history export.")

    secret = _get_secret()
    if not secret:
        raise ValueError("APPS_SCRIPT_SECRET environment variable is not set")

    payload = {
        "secret_token": secret,
        "branch": branch_name or branch_code,
        "branch_id": branch_code,
        # Compatibility with the red-alert flow and already deployed scripts.
        "branch_code": branch_code,
        "category": category,
        "spreadsheet_id": spreadsheet_id,
        "records": formatted_records,
    }
    print(
        "[GOOGLE SHEETS EXPORT] "
        f"branch={branch_code} category={category} records={len(formatted_records)} spreadsheet={spreadsheet_id}",
        flush=True,
    )
    response = requests.post(url, json=payload, timeout=10)
    print(f"[GOOGLE SHEETS EXPORT] HTTP Status Code: {response.status_code}", flush=True)
    response.raise_for_status()
    response_data = response.json()
    if not isinstance(response_data, dict) or not response_data.get("success"):
        error = response_data.get("error") if isinstance(response_data, dict) else "Invalid Apps Script response"
        raise ValueError(error or "Apps Script returned success=false")
    return response_data


def send_alert_email(alert):
    """Send a low-stock RED/OUT_OF_STOCK alert email from Django.

    Uses ADMIN_ALERT_EMAIL from settings (set via .env).
    If no email host is configured the email will be printed to the console.
    """
    import logging
    logger = logging.getLogger(__name__)

    if ("test" in sys.argv or "test_coverage" in sys.argv) and not hasattr(requests.post, "mock_calls"):
        logger.debug("[ALERT EMAIL] Skipping email send in test run (not patched)")
        return

    recipient = getattr(settings, "ADMIN_ALERT_EMAIL", None) or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not recipient:
        logger.warning("[ALERT EMAIL] ADMIN_ALERT_EMAIL is not configured — skipping email.")
        return

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "alerts@laundryrage.com")
    branch_name = alert.branch.branch_name if alert.branch else "Global"
    branch_code = alert.branch.branch_code if alert.branch else "N/A"
    now_str = timezone.localtime(alert.created_at).strftime("%Y-%m-%d %H:%M")

    status_label = "OUT OF STOCK" if alert.current_status == "OUT_OF_STOCK" else alert.current_status
    emoji = "🚨" if alert.current_status == "OUT_OF_STOCK" else "🔴"

    subject = f"{emoji} LOW STOCK ALERT: {alert.product.name} at {branch_name}"

    message = (
        f"{emoji} LOW STOCK ALERT\n"
        f"{'=' * 50}\n"
        f"Branch         : {branch_name} ({branch_code})\n"
        f"Product        : {alert.product.name}\n"
        f"Category       : {alert.category}\n"
        f"Current Stock  : {alert.current_stock:.0f}\n"
        f"Base Stock     : {alert.base_stock:.0f}\n"
        f"Refill Required: {alert.refill_required:.0f}\n"
        f"Status         : {status_label}\n"
        f"Date / Time    : {now_str}\n"
        f"{'=' * 50}\n\n"
        f"Please arrange restocking immediately.\n"
    )

    html_message = f"""
<div style="font-family: Arial, sans-serif; color: #333; max-width: 580px; margin: 0 auto;
            padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
  <h2 style="color: #d9534f; margin-top: 0;">{emoji} Low Stock Alert</h2>
  <table style="width:100%; border-collapse:collapse; font-size:14px; margin-top:12px;">
    <tr style="background:#fafafa;">
      <td style="padding:8px; font-weight:bold; width:40%; border-bottom:1px solid #eee;">Branch</td>
      <td style="padding:8px; border-bottom:1px solid #eee;">{branch_name} <span style="color:#999;font-size:12px;">({branch_code})</span></td>
    </tr>
    <tr>
      <td style="padding:8px; font-weight:bold; border-bottom:1px solid #eee;">Product</td>
      <td style="padding:8px; border-bottom:1px solid #eee;">{alert.product.name}</td>
    </tr>
    <tr style="background:#fafafa;">
      <td style="padding:8px; font-weight:bold; border-bottom:1px solid #eee;">Category</td>
      <td style="padding:8px; border-bottom:1px solid #eee;">{alert.category}</td>
    </tr>
    <tr>
      <td style="padding:8px; font-weight:bold; border-bottom:1px solid #eee;">Current Stock</td>
      <td style="padding:8px; border-bottom:1px solid #eee; color:#d9534f; font-weight:bold;">{alert.current_stock:.0f}</td>
    </tr>
    <tr style="background:#fafafa;">
      <td style="padding:8px; font-weight:bold; border-bottom:1px solid #eee;">Base Stock</td>
      <td style="padding:8px; border-bottom:1px solid #eee;">{alert.base_stock:.0f}</td>
    </tr>
    <tr>
      <td style="padding:8px; font-weight:bold; border-bottom:1px solid #eee;">Refill Required</td>
      <td style="padding:8px; border-bottom:1px solid #eee; font-weight:bold;">{alert.refill_required:.0f}</td>
    </tr>
    <tr style="background:#fafafa;">
      <td style="padding:8px; font-weight:bold; border-bottom:1px solid #eee;">Status</td>
      <td style="padding:8px; border-bottom:1px solid #eee; color:#d9534f; font-weight:bold;">{status_label}</td>
    </tr>
    <tr>
      <td style="padding:8px; font-weight:bold;">Date / Time</td>
      <td style="padding:8px;">{now_str}</td>
    </tr>
  </table>
  <p style="margin-top:20px; font-size:13px; color:#777;">
    Please review and arrange replenishment immediately.
  </p>
</div>
"""

    try:
        from django.core.mail import EmailMultiAlternatives
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=from_email,
            to=[recipient],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        logger.info(f"[ALERT EMAIL] Sent low-stock alert for {alert.product.name} @ {branch_code} to {recipient}")

        # Mark email as sent on the alert record
        from .models import InventoryAlert
        InventoryAlert.objects.filter(pk=alert.pk).update(
            email_sent=True,
            email_sent_at=timezone.now(),
        )
    except Exception as exc:
        logger.error(f"[ALERT EMAIL] Failed to send alert email for {alert.product.name}: {exc}")
        raise


def export_alert_to_google_sheets(alert):
    """Export a single inventory alert to the Google Apps Script web app.

    Red alerts always go to the Red Alerts workbook, identified by
    RED_ALERTS_SPREADSHEET_ID in .env (falls back to the branch sheet if unset).
    """
    if ("test" in sys.argv or "test_coverage" in sys.argv) and not hasattr(requests.post, "mock_calls"):
        print("[GOOGLE SHEETS EXPORT] Mocking export for test run (not patched)", flush=True)
        return

    url = os.environ.get("GOOGLE_APPS_SCRIPT_URL")
    if url:
        url = url.strip().strip('"').strip("'")
    if not url:
        raise ValueError("GOOGLE_APPS_SCRIPT_URL environment variable is not set")

    secret = _get_secret()
    if not secret:
        raise ValueError("APPS_SCRIPT_SECRET environment variable is not set")

    # Prefer the dedicated Red Alerts spreadsheet; fall back to branch sheet
    red_alerts_sheet_id = (
        os.environ.get("RED_ALERTS_SPREADSHEET_ID", "").strip()
        or (alert.branch.google_sheet_id if alert.branch else None)
    )

    payload = {
        "secret_token": secret,
        "category": "red_alerts",
        "records": [{
            "alert_id": alert.id, "date": alert.created_at.strftime("%Y-%m-%d"),
            "time": alert.created_at.strftime("%H:%M"),
            "branch": alert.branch.branch_name if alert.branch else "Global",
            "branch_code": alert.branch.branch_code if alert.branch else "Global",
            "category": alert.category, "product": alert.product.name,
            "current_stock": float(alert.current_stock), "base_stock": float(alert.base_stock),
            "refill_required": float(alert.refill_required), "status": alert.current_status,
            "email_sent": "NO",
        }],
    }
    if red_alerts_sheet_id:
        payload["spreadsheet_id"] = red_alerts_sheet_id

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()

