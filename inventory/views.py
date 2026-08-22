import json
import calendar
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from .models import Product, Inventory, StockHistory, DailyInventory
from .helpers import add_stock, use_stock, edit_stock, set_base_stock
from .google_sheets import export_to_google_sheets


def dashboard_view(request):
    active_products = Product.objects.filter(is_active=True).select_related('inventory').prefetch_related('monthly_inventories')
    
    low_supplies = []
    low_accessories = []
    
    mod_supplies = []
    mod_accessories = []
    
    suff_supplies = []
    suff_accessories = []
    
    for product in active_products:
        monthly_inv = product.current_monthly_inventory
        if monthly_inv and monthly_inv.base_stock > Decimal('0.00'):
            status = monthly_inv.status
            pct = monthly_inv.remaining_percentage
            
            product_info = {
                'product': product,
                'current_stock': monthly_inv.current_stock,
                'base_stock': monthly_inv.base_stock,
                'remaining_percentage': pct,
                'status': status,
            }
            
            is_supplies = (product.category == 'Laundry Supplies')
            
            if status == "RED":
                if is_supplies:
                    low_supplies.append(product_info)
                else:
                    low_accessories.append(product_info)
            elif status == "YELLOW":
                if is_supplies:
                    mod_supplies.append(product_info)
                else:
                    mod_accessories.append(product_info)
            elif status == "GREEN":
                if is_supplies:
                    suff_supplies.append(product_info)
                else:
                    suff_accessories.append(product_info)
                    
    low_count = len(low_supplies) + len(low_accessories)
    mod_count = len(mod_supplies) + len(mod_accessories)
    suff_count = len(suff_supplies) + len(suff_accessories)
    
    context = {
        'low_count': low_count,
        'mod_count': mod_count,
        'suff_count': suff_count,
        
        'low_supplies': low_supplies,
        'low_accessories': low_accessories,
        
        'mod_supplies': mod_supplies,
        'mod_accessories': mod_accessories,
        
        'suff_supplies': suff_supplies,
        'suff_accessories': suff_accessories,
    }
    return render(request, 'dashboard/dashboard.html', context)

def supplies_view(request):
    products = Product.objects.filter(is_active=True, category='Laundry Supplies').select_related('inventory')
    for p in products:
        Inventory.objects.get_or_create(product=p)
    context = {
        'title': 'Laundry Supplies',
        'category': 'supplies',
        'products': products,
        'fallback_emoji': '🧴',
    }
    return render(request, 'inventory/laundry_supplies.html', context)

def accessories_view(request):
    products = Product.objects.filter(is_active=True, category='Accessories').select_related('inventory')
    for p in products:
        Inventory.objects.get_or_create(product=p)
    context = {
        'title': 'Laundry Accessories',
        'category': 'accessories',
        'products': products,
        'fallback_emoji': '🧺',
    }
    return render(request, 'inventory/laundry_accessories.html', context)

def supplies_history_view(request):
    selected_months = request.GET.getlist('months')
    is_filter_active = 'months' in request.GET
    category = 'Laundry Supplies'
    
    daily_records = DailyInventory.objects.filter(
        product__is_active=True,
        product__category=category
    ).select_related('product')
    
    # Get distinct months/years available in database for this category
    dates = DailyInventory.objects.filter(
        product__is_active=True,
        product__category=category
    ).values_list('date', flat=True).distinct()
    
    month_pairs = set()
    for d in dates:
        month_pairs.add((d.year, d.month))
    sorted_pairs = sorted(list(month_pairs), key=lambda p: (p[0], p[1]), reverse=True)
    
    month_options = []
    for yr, mo in sorted_pairs:
        val = f"{yr}-{mo:02d}"
        label = f"{calendar.month_name[mo]} {yr}"
        if not is_filter_active:
            checked = True
        else:
            checked = val in selected_months
        month_options.append({
            'value': val,
            'label': label,
            'checked': checked
        })
        
    # Apply filtering
    if is_filter_active:
        if selected_months:
            q_obj = Q()
            for m in selected_months:
                try:
                    yr, mo = map(int, m.split('-'))
                    q_obj |= Q(date__year=yr, date__month=mo)
                except ValueError:
                    pass
            daily_records = daily_records.filter(q_obj)
        else:
            daily_records = daily_records.none()
            
    # Check for export parameter
    if request.GET.get('export') == 'google_sheets':
        if not selected_months:
            messages.error(request, "Please select at least one month to export.")
        elif not daily_records.exists():
            messages.error(request, "No history records found for the selected months.")
        else:
            try:
                export_to_google_sheets('supplies', daily_records)
                messages.success(request, f"Successfully exported {daily_records.count()} records to Google Sheets.")
            except Exception as e:
                import requests
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    err_msg = f"Unable to connect to Google Sheets: HTTP {e.response.status_code} - {e.response.text[:250]}"
                elif isinstance(e, requests.exceptions.RequestException):
                    err_msg = f"Unable to connect to Google Sheets: Connection/Timeout error ({str(e)})"
                else:
                    err_msg = f"Unable to connect to Google Sheets: {str(e)}"
                messages.error(request, err_msg)
            
    rows = []
    seen_products = set()
    for record in daily_records:
        rows.append({
            'product': record.product,
            'date': record.date,
            'base_stock': record.base_stock,
            'closing_stock': record.closing_stock,
            'remaining_percentage': record.remaining_percentage,
            'status': record.status,
        })
        seen_products.add(record.product.id)
        
    if not is_filter_active:
        all_products = Product.objects.filter(
            is_active=True,
            category=category
        ).select_related('inventory').prefetch_related('monthly_inventories')
        
        for product in all_products:
            if product.id not in seen_products:
                monthly_inv = product.current_monthly_inventory
                base_stock = monthly_inv.base_stock if monthly_inv else Decimal('0.00')
                closing_stock = product.inventory.current_quantity if hasattr(product, 'inventory') else Decimal('0.00')
                date_val = product.inventory.updated_at.date() if hasattr(product, 'inventory') else timezone.now().date()
                rows.append({
                    'product': product,
                    'date': date_val,
                    'base_stock': base_stock,
                    'closing_stock': closing_stock,
                    'remaining_percentage': monthly_inv.remaining_percentage if monthly_inv else None,
                    'status': monthly_inv.status if monthly_inv else "No Base Stock",
                })
        
    rows.sort(key=lambda r: r['product'].name)
    rows.sort(key=lambda r: r['date'], reverse=True)
    
    context = {
        'title': 'History of Laundry Supplies',
        'rows': rows,
        'is_supplies': True,
        'month_options': month_options,
    }
    return render(request, 'history/laundry_supplies.html', context)

def accessories_history_view(request):
    selected_months = request.GET.getlist('months')
    is_filter_active = 'months' in request.GET
    category = 'Accessories'
    
    daily_records = DailyInventory.objects.filter(
        product__is_active=True,
        product__category=category
    ).select_related('product')
    
    # Get distinct months/years available in database for this category
    dates = DailyInventory.objects.filter(
        product__is_active=True,
        product__category=category
    ).values_list('date', flat=True).distinct()
    
    month_pairs = set()
    for d in dates:
        month_pairs.add((d.year, d.month))
    sorted_pairs = sorted(list(month_pairs), key=lambda p: (p[0], p[1]), reverse=True)
    
    month_options = []
    for yr, mo in sorted_pairs:
        val = f"{yr}-{mo:02d}"
        label = f"{calendar.month_name[mo]} {yr}"
        if not is_filter_active:
            checked = True
        else:
            checked = val in selected_months
        month_options.append({
            'value': val,
            'label': label,
            'checked': checked
        })
        
    # Apply filtering
    if is_filter_active:
        if selected_months:
            q_obj = Q()
            for m in selected_months:
                try:
                    yr, mo = map(int, m.split('-'))
                    q_obj |= Q(date__year=yr, date__month=mo)
                except ValueError:
                    pass
            daily_records = daily_records.filter(q_obj)
        else:
            daily_records = daily_records.none()
            
    # Check for export parameter
    if request.GET.get('export') == 'google_sheets':
        if not selected_months:
            messages.error(request, "Please select at least one month to export.")
        elif not daily_records.exists():
            messages.error(request, "No history records found for the selected months.")
        else:
            try:
                export_to_google_sheets('accessories', daily_records)
                messages.success(request, f"Successfully exported {daily_records.count()} records to Google Sheets.")
            except Exception as e:
                import requests
                if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                    err_msg = f"Unable to connect to Google Sheets: HTTP {e.response.status_code} - {e.response.text[:250]}"
                elif isinstance(e, requests.exceptions.RequestException):
                    err_msg = f"Unable to connect to Google Sheets: Connection/Timeout error ({str(e)})"
                else:
                    err_msg = f"Unable to connect to Google Sheets: {str(e)}"
                messages.error(request, err_msg)
            
    rows = []
    seen_products = set()
    for record in daily_records:
        rows.append({
            'product': record.product,
            'date': record.date,
            'base_stock': record.base_stock,
            'closing_stock': record.closing_stock,
            'remaining_percentage': record.remaining_percentage,
            'status': record.status,
        })
        seen_products.add(record.product.id)
        
    if not is_filter_active:
        all_products = Product.objects.filter(
            is_active=True,
            category=category
        ).select_related('inventory').prefetch_related('monthly_inventories')
        
        for product in all_products:
            if product.id not in seen_products:
                monthly_inv = product.current_monthly_inventory
                base_stock = monthly_inv.base_stock if monthly_inv else Decimal('0.00')
                closing_stock = product.inventory.current_quantity if hasattr(product, 'inventory') else Decimal('0.00')
                date_val = product.inventory.updated_at.date() if hasattr(product, 'inventory') else timezone.now().date()
                rows.append({
                    'product': product,
                    'date': date_val,
                    'base_stock': base_stock,
                    'closing_stock': closing_stock,
                    'remaining_percentage': monthly_inv.remaining_percentage if monthly_inv else None,
                    'status': monthly_inv.status if monthly_inv else "No Base Stock",
                })
        
    rows.sort(key=lambda r: r['product'].name)
    rows.sort(key=lambda r: r['date'], reverse=True)
    
    context = {
        'title': 'History of Laundry Accessories',
        'rows': rows,
        'is_supplies': False,
        'month_options': month_options,
    }
    return render(request, 'history/laundry_accessories.html', context)

def product_history_detail_view(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    history_entries = product.stock_history.order_by('-created_at')
    
    date_str = request.GET.get('date')
    selected_date = None
    if date_str:
        try:
            from datetime import datetime
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            history_entries = history_entries.filter(created_at__date=selected_date)
        except ValueError:
            pass
            
    context = {
        'product': product,
        'history_entries': history_entries,
        'title': f"Detailed Transaction History: {product.name}",
        'selected_date': selected_date,
    }
    return render(request, 'history/product_detail.html', context)



@require_POST
def adjust_stock_ajax(request):
    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        quantity_str = data.get('quantity')
        action = data.get('action')
        notes = data.get('notes')
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'}, status=400)
        
    if not product_id or quantity_str is None or not action:
        return JsonResponse({'success': False, 'error': 'Missing required fields.'}, status=400)
        
    product = get_object_or_404(Product, id=product_id, is_active=True)
    
    try:
        quantity = Decimal(str(quantity_str))
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid quantity.'}, status=400)
        
    try:
        if action == 'add':
            inventory = add_stock(product, quantity, notes=notes)
        elif action == 'use':
            inventory = use_stock(product, quantity, notes=notes)
        elif action == 'edit':
            inventory = edit_stock(product, quantity, notes=notes)
        elif action == 'set_base':
            set_base_stock(product, quantity, date_val=None)
            inventory = product.inventory
        else:
            return JsonResponse({'success': False, 'error': 'Invalid action.'}, status=400)
    except ValidationError as e:
        err_msg = ", ".join(e.messages) if hasattr(e, 'messages') else str(e)
        return JsonResponse({'success': False, 'error': err_msg}, status=400)
        
    monthly_inv = product.current_monthly_inventory
    rem_pct = float(monthly_inv.remaining_percentage) if (monthly_inv and monthly_inv.remaining_percentage is not None) else None
    status = monthly_inv.status if monthly_inv else "No Base Stock"
    
    return JsonResponse({
        'success': True,
        'new_quantity': str(inventory.current_quantity),
        'remaining_percentage': rem_pct,
        'status': status,
        'base_stock': str(monthly_inv.base_stock) if monthly_inv else "0"
    })

