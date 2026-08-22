import os
import requests

def export_to_google_sheets(category, records):
    """
    Exports the provided DailyInventory records to the Google Apps Script Web App.
    - category: 'supplies' or 'accessories'
    - records: QuerySet of DailyInventory records
    """
    url = os.environ.get('GOOGLE_APPS_SCRIPT_URL')
    if url:
        url = url.strip().strip('"').strip("'")
    
    # 1. Google endpoint being called (without exposing credentials)
    masked_url = "None"
    if url:
        parts = url.split('/s/')
        if len(parts) > 1:
            deployment_id = parts[1].split('/')[0]
            masked_id = deployment_id[:10] + "..." if len(deployment_id) > 10 else "..."
            masked_url = f"{parts[0]}/s/{masked_id}/exec"
        else:
            masked_url = url
            
    # 2. Selected date/month range
    dates = [r.date.strftime('%Y-%m-%d') for r in records]
    date_range = f"{min(dates)} to {max(dates)}" if dates else "None"
    
    # 3. Target sheet/tab
    target_tab = "Supplies" if category == "supplies" else "Accessories"
    
    print(f"[GOOGLE SHEETS EXPORT] Endpoint: {masked_url}", flush=True)
    print(f"[GOOGLE SHEETS EXPORT] Target Tab: {target_tab}", flush=True)
    print(f"[GOOGLE SHEETS EXPORT] Selected Date Range: {date_range}", flush=True)
    
    if not url:
        raise ValueError("GOOGLE_APPS_SCRIPT_URL environment variable is not set")
        
    status_map = {
        'RED': 'LOW',
        'YELLOW': 'MODERATE',
        'GREEN': 'SUFFICIENT',
        'No Base Stock': 'NO BASE'
    }
    
    formatted_records = []
    for record in records:
        date_str = record.date.strftime('%Y-%m-%d')
        prod_name = record.product.name
        
        # Base Stock (format to number)
        base_stock_val = float(record.base_stock)
        base_stock_num = int(base_stock_val) if base_stock_val.is_integer() else base_stock_val
        
        # Closing Stock
        closing_stock_val = float(record.closing_stock)
        closing_stock_num = int(closing_stock_val) if closing_stock_val.is_integer() else closing_stock_val
        
        # Remaining %
        if record.remaining_percentage is not None:
            rem_pct_val = float(record.remaining_percentage)
            rem_pct_str = f"{rem_pct_val:.0f}%"
        else:
            rem_pct_str = '—'
            
        # Status
        status_str = status_map.get(record.status, record.status)
        
        formatted_records.append({
            "date": date_str,
            "product": prod_name,
            "base_stock": base_stock_num,
            "closing_stock": closing_stock_num,
            "remaining_percentage": rem_pct_str,
            "status": status_str
        })
        
    payload = {
        "category": category,
        "records": formatted_records
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        # Log HTTP status code on success
        print(f"[GOOGLE SHEETS EXPORT] HTTP Status Code: {response.status_code}", flush=True)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        # Log HTTP status code on failure
        status_code = getattr(e.response, 'status_code', 'N/A') if getattr(e, 'response', None) is not None else 'N/A'
        print(f"[GOOGLE SHEETS EXPORT] Failed - HTTP Status Code: {status_code}", flush=True)
        print(f"[GOOGLE SHEETS EXPORT] Error: {e}", flush=True)
        raise e
