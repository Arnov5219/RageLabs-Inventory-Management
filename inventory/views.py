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
from django.utils.safestring import mark_safe
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm

from .models import Product, Inventory, StockHistory, DailyInventory, Branch
from .helpers import add_stock, use_stock, edit_stock, set_base_stock
from .google_sheets import export_to_google_sheets

def history_spreadsheet_id(branch):
    """Return the approved spreadsheet for the active branch only."""
    if not branch:
        return None
    return branch.google_sheet_id


def login_view(request):
    if request.user.is_authenticated:
        return redirect('inventory:dashboard')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                auth_login(request, user)
                
                if user.is_superuser or user.is_staff:
                    messages.success(request, f"Welcome back, Admin {username}!")
                    first_branch = Branch.objects.filter(active=True).first()
                    if first_branch and 'selected_branch_id' not in request.session:
                        request.session['selected_branch_id'] = first_branch.id
                else:
                    profile = getattr(user, 'employee_profile', None)
                    if profile and profile.branch:
                        messages.success(request, f"Welcome back, {username}! Logged into branch {profile.branch.branch_name}.")
                    else:
                        messages.warning(request, f"Welcome back, {username}! Note: No branch is currently assigned to you.")
                
                return redirect('inventory:dashboard')
            else:
                messages.error(request, "Invalid username or password.")
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
        
    return render(request, 'login.html', {'form': form})

def logout_view(request):
    auth_logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('inventory:login')

def switch_branch_view(request):
    if not (request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff)):
        messages.error(request, "Access denied. Only administrators can switch branches.")
        return redirect('inventory:dashboard')
        
    branch_id = request.GET.get('branch_id')
    if branch_id == 'all':
        if 'selected_branch_id' in request.session:
            del request.session['selected_branch_id']
        messages.success(request, "Switched view to All Branches.")
    elif branch_id:
        branch = get_object_or_404(Branch, id=branch_id, active=True)
        request.session['selected_branch_id'] = branch.id
        messages.success(request, f"Switched view to branch: {branch.branch_name}.")
        
    referrer = request.META.get('HTTP_REFERER')
    if referrer:
        return redirect(referrer)
    return redirect('inventory:dashboard')


def dashboard_view(request):
    active_products = Product.objects.filter(is_active=True)
    active_branches = Branch.objects.filter(active=True)
    
    is_all_branches = False
    if request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
        if 'selected_branch_id' not in request.session:
            is_all_branches = True
            
    branch = request.current_branch if not is_all_branches else None
    
    from datetime import date
    now_dt = timezone.now()
    month_start = date(now_dt.year, now_dt.month, 1)
    from .models import MonthlyInventory

    # Synchronize and clean database records to ensure compatibility across all updates
    for b in active_branches:
        for p in active_products:
            inv, created_inv = Inventory.objects.get_or_create(
                product=p,
                branch=b,
                defaults={
                    'current_stock': Decimal('0.00'),
                    'base_stock': Decimal('0.00'),
                    'yellow_threshold': Decimal('0.00'),
                    'red_threshold': Decimal('0.00'),
                }
            )
            mi, created_mi = MonthlyInventory.objects.get_or_create(
                product=p,
                branch=b,
                month=month_start,
                defaults={
                    'current_stock': inv.current_stock,
                    'base_stock': inv.base_stock,
                    'total_added': Decimal('0.00'),
                    'total_used': Decimal('0.00'),
                }
            )
            
            changed = False
            # Sync legacy fields to current fields in Inventory
            if inv.current_stock == Decimal('0.00') and inv.current_quantity != Decimal('0.00'):
                inv.current_stock = inv.current_quantity
                changed = True
            elif inv.current_quantity == Decimal('0.00') and inv.current_stock != Decimal('0.00'):
                inv.current_quantity = inv.current_stock
                changed = True
                
            if inv.red_threshold == Decimal('0.00') and inv.low_stock_threshold != Decimal('0.00'):
                inv.red_threshold = inv.low_stock_threshold
                changed = True
            elif inv.low_stock_threshold == Decimal('0.00') and inv.red_threshold != Decimal('0.00'):
                inv.low_stock_threshold = inv.red_threshold
                changed = True
                
            # Sync base stock between MonthlyInventory and Inventory
            if mi.base_stock > 0 and inv.base_stock == 0:
                inv.base_stock = mi.base_stock
                changed = True
            elif inv.base_stock > 0 and mi.base_stock == 0:
                mi.base_stock = inv.base_stock
                mi.save()
                
            # Sync current stock between MonthlyInventory and Inventory
            if mi.current_stock > 0 and inv.current_stock == 0:
                inv.current_stock = mi.current_stock
                changed = True
            elif inv.current_stock > 0 and mi.current_stock == 0:
                mi.current_stock = inv.current_stock
                mi.save()
                
            # Set default thresholds if they are 0 and base stock is set
            if inv.base_stock > 0 and inv.yellow_threshold == 0 and inv.red_threshold == 0:
                inv.yellow_threshold = inv.base_stock * Decimal('0.40')
                inv.red_threshold = inv.base_stock * Decimal('0.10')
                changed = True
                
            if changed:
                inv.save()

    if is_all_branches:
        inventories = Inventory.objects.filter(product__is_active=True, branch__active=True).select_related('product', 'branch')
    else:
        inventories = Inventory.objects.filter(product__is_active=True, branch=branch).select_related('product', 'branch')

    all_inventories = Inventory.objects.filter(product__is_active=True, branch__active=True).select_related('product', 'branch')

    low_supplies = []
    low_accessories = []
    mod_supplies = []
    mod_accessories = []
    suff_supplies = []
    suff_accessories = []
    
    total_stock = Decimal('0.00')
    refill_required = Decimal('0.00')
    
    for inv in inventories:
        product = inv.product
        b = inv.branch
        status = 'GREEN' if inv.alert_status == 'NORMAL' else ('RED' if inv.alert_status == 'OUT_OF_STOCK' else inv.alert_status)
        
        total_stock += inv.current_stock
        req_refill = (inv.base_stock - inv.current_stock) if inv.base_stock > inv.current_stock else Decimal('0.00')
        refill_required += req_refill
        
        is_supplies = (product.category == 'Laundry Supplies')
        product_info = {
            'product': product,
            'branch': b,
            'current_stock': inv.current_stock,
            'base_stock': inv.base_stock,
            'remaining_percentage': (inv.current_stock / inv.base_stock * 100) if inv.base_stock > 0 else None,
            'status': status,
            'required_refill': req_refill,
        }
        
        if status == 'RED':
            if is_supplies:
                low_supplies.append(product_info)
            else:
                low_accessories.append(product_info)
        elif status == 'YELLOW':
            if is_supplies:
                mod_supplies.append(product_info)
            else:
                mod_accessories.append(product_info)
        else: # GREEN
            if inv.base_stock > 0:
                if is_supplies:
                    suff_supplies.append(product_info)
                else:
                    suff_accessories.append(product_info)
                
    low_count = len(low_supplies) + len(low_accessories)
    mod_count = len(mod_supplies) + len(mod_accessories)
    suff_count = len(suff_supplies) + len(suff_accessories)
    
    low_branches = len(set(item['branch'].id for item in low_supplies + low_accessories if item.get('branch')))
    mod_branches = len(set(item['branch'].id for item in mod_supplies + mod_accessories if item.get('branch')))
    suff_branches = len(set(item['branch'].id for item in suff_supplies + suff_accessories if item.get('branch')))
    
    branch_rows = []
    total_red = 0
    total_yellow = 0
    total_green = 0
    total_refill_overall = Decimal('0.00')
    
    for b in active_branches:
        b_red = 0
        b_yellow = 0
        b_green = 0
        b_refill = Decimal('0.00')
        
        for inv in all_inventories:
            if inv.branch == b:
                status = 'GREEN' if inv.alert_status == 'NORMAL' else ('RED' if inv.alert_status == 'OUT_OF_STOCK' else inv.alert_status)
                if status == 'RED':
                    b_red += 1
                elif status == 'YELLOW':
                    b_yellow += 1
                else:
                    b_green += 1
                
                if inv.base_stock > inv.current_stock:
                    b_refill += (inv.base_stock - inv.current_stock)
                    
        branch_rows.append({
            'branch': b,
            'red': b_red,
            'yellow': b_yellow,
            'green': b_green,
            'refill': b_refill
        })
        
        total_red += b_red
        total_yellow += b_yellow
        total_green += b_green
        total_refill_overall += b_refill
        
    attention_items = sorted(low_supplies + low_accessories, key=lambda x: x['required_refill'], reverse=True)
    attention_display = attention_items[:5]
    has_attention = len(attention_items) > 0
    
    if is_all_branches:
        latest_update = Inventory.objects.filter(branch__active=True).order_by('-updated_at').first()
    else:
        latest_update = Inventory.objects.filter(branch=branch).order_by('-updated_at').first()
        
    if latest_update and latest_update.updated_at:
        latest_time = timezone.localtime(latest_update.updated_at).strftime('%I:%M %p')
    else:
        latest_time = "Just now"
        
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
        
        'low_branches': low_branches,
        'mod_branches': mod_branches,
        'suff_branches': suff_branches,
        
        'branch_rows': branch_rows,
        'total_red': total_red,
        'total_yellow': total_yellow,
        'total_green': total_green,
        'total_refill_overall': total_refill_overall,
        
        'attention_display': attention_display,
        'has_attention': has_attention,
        'attention_count': len(attention_items),
        
        'total_products': active_products.count() if is_all_branches else len(inventories),
        'total_stock': total_stock,
        'refill_required': refill_required,
        'active_branches_count': active_branches.count(),
        
        'latest_time': latest_time,
        
        'all_branches': active_branches,
        'is_all_branches': is_all_branches,
        'active_branch': branch,
    }
    return render(request, 'dashboard/dashboard.html', context)

def supplies_view(request):
    products = Product.objects.filter(is_active=True, category='Laundry Supplies')
    branch = request.current_branch
    for p in products:
        Inventory.objects.get_or_create(product=p, branch=branch)
    context = {
        'title': 'Laundry Supplies',
        'category': 'supplies',
        'products': products,
        'fallback_emoji': '🧴',
        'active_branch': branch,
    }
    return render(request, 'inventory/laundry_supplies.html', context)

def accessories_view(request):
    products = Product.objects.filter(is_active=True, category='Accessories')
    branch = request.current_branch
    for p in products:
        Inventory.objects.get_or_create(product=p, branch=branch)
    context = {
        'title': 'Laundry Accessories',
        'category': 'accessories',
        'products': products,
        'fallback_emoji': '🧺',
        'active_branch': branch,
    }
    return render(request, 'inventory/laundry_accessories.html', context)

def _history_view(request, *, category, export_category, title, template_name, is_supplies):
    """Render history using the DailyInventory model.
    """
    selected_months = request.GET.getlist('months')
    is_filter_active = 'months' in request.GET
    branch = request.current_branch

    # Query DailyInventory instead of StockHistory
    history_records = DailyInventory.objects.filter(
        product__is_active=True,
        product__category=category,
        branch=branch
    ).select_related('product').order_by('-date', '-id')

    dates = history_records.values_list('date', flat=True).distinct()
    
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
        
    if is_filter_active:
        if selected_months:
            q_obj = Q()
            for m in selected_months:
                try:
                    yr, mo = map(int, m.split('-'))
                    q_obj |= Q(date__year=yr, date__month=mo)
                except ValueError:
                    pass
            history_records = history_records.filter(q_obj)
        else:
            history_records = history_records.none()
            
    is_all_branches = False
    if request.user.is_superuser or request.user.is_staff:
        if 'selected_branch_id' not in request.session:
            is_all_branches = True

    open_sheet_url = None
    if request.GET.get('export') == 'google_sheets':
        if is_all_branches:
            messages.error(request, "Please select a specific branch on the dashboard before exporting history.")
        elif not selected_months:
            messages.error(request, "Please select at least one month to export.")
        elif not history_records.exists():
            messages.error(request, "No history records found for the selected months.")
        else:
            try:
                sheet_id = history_spreadsheet_id(branch)

                # Build the same month filter as the displayed records use
                export_qs = DailyInventory.objects.filter(
                    branch=branch,
                    product__is_active=True
                ).select_related('product')

                if is_filter_active and selected_months:
                    month_q = Q()
                    for m in selected_months:
                        try:
                            yr, mo = map(int, m.split('-'))
                            month_q |= Q(date__year=yr, date__month=mo)
                        except ValueError:
                            pass
                    export_qs = export_qs.filter(month_q)

                # Split by category and export both sheets for this branch
                supplies_records = export_qs.filter(product__category='Laundry Supplies')
                accessories_records = export_qs.filter(product__category='Accessories')

                res_supplies = export_to_google_sheets(
                    'supplies', supplies_records, spreadsheet_id=sheet_id,
                    branch_code=branch.branch_code if branch else None,
                    branch_name=branch.branch_name if branch else None,
                )

                res_accessories = export_to_google_sheets(
                    'accessories', accessories_records, spreadsheet_id=sheet_id,
                    branch_code=branch.branch_code if branch else None,
                    branch_name=branch.branch_name if branch else None,
                )

                month_labels = [m['label'] for m in month_options if m['checked']]
                months_str = ", ".join(month_labels)
                if branch:
                    sheet_url = res_supplies.get('spreadsheet_url') or f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
                    messages.success(request, mark_safe(f"Successfully exported {months_str} history to {branch.branch_name} Google Sheets. <a href='{sheet_url}' target='_blank' style='text-decoration: underline; font-weight: bold; margin-left: 0.5rem;'>Open Google Sheet &rarr;</a>"))
                else:
                    messages.success(request, f"Successfully exported history to Google Sheets.")
                if res_supplies and res_supplies.get('spreadsheet_url'):
                    open_sheet_url = res_supplies.get('spreadsheet_url')
                elif sheet_id:
                    open_sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Google Sheets export failed: {e}")
                
                import requests as reqs
                if isinstance(e, reqs.exceptions.HTTPError) and e.response is not None:
                    err_msg = f"Unable to connect to Google Sheets: HTTP {e.response.status_code} - {e.response.text[:250]}"
                elif isinstance(e, reqs.exceptions.RequestException):
                    err_msg = f"Unable to connect to Google Sheets: Connection/Timeout error ({str(e)})"
                else:
                    err_msg = f"Unable to connect to Google Sheets: {str(e)}"
                
                messages.error(request, "Google Sheets export failed. Your inventory data was not affected.")
                from django.conf import settings
                import sys
                if 'test' in sys.argv or getattr(settings, 'TESTING', False):
                    messages.error(request, err_msg)
            
    rows = []
    for record in history_records:
        remaining_percentage = record.remaining_percentage
        if remaining_percentage is None:
            status = "No Base Stock"
        elif remaining_percentage >= 80:
            status = "GREEN"
        elif remaining_percentage > 10:
            status = "YELLOW"
        else:
            status = "RED"
        rows.append({
            'product': record.product,
            'date': record.date,
            'base_stock': record.base_stock,
            'closing_stock': record.closing_stock,
            'remaining_percentage': remaining_percentage,
            'status': status,
        })
 
    context = {
        'title': title,
        'rows': rows,
        'is_supplies': is_supplies,
        'month_options': month_options,
        'open_sheet_url': open_sheet_url,
    }
    return render(request, template_name, context)


def supplies_history_view(request):
    return _history_view(
        request,
        category='Laundry Supplies',
        export_category='supplies',
        title='History of Laundry Supplies',
        template_name='history/laundry_supplies.html',
        is_supplies=True,
    )

def accessories_history_view(request):
    return _history_view(
        request,
        category='Accessories',
        export_category='accessories',
        title='History of Laundry Accessories',
        template_name='history/laundry_accessories.html',
        is_supplies=False,
    )

def product_history_detail_view(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    history_entries = product.stock_history.filter(branch=request.current_branch).order_by('-created_at')
    
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
        'new_quantity': str(inventory.current_stock),
        'remaining_percentage': rem_pct,
        'status': status,
        'base_stock': str(monthly_inv.base_stock) if monthly_inv else "0"
    })


@require_POST
def request_refill_ajax(request):
    import os
    import requests
    from django.http import JsonResponse
    
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required.'}, status=401)
        
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        
    url = os.environ.get('GOOGLE_APPS_SCRIPT_URL')
    secret = os.environ.get('APPS_SCRIPT_SECRET')
    
    if url:
        url = url.strip().strip('"').strip("'")
    if secret:
        secret = secret.strip().strip('"').strip("'")
        
    if not url:
        return JsonResponse({'success': False, 'error': 'GOOGLE_APPS_SCRIPT_URL is not configured.'}, status=500)
    if not secret:
        return JsonResponse({'success': False, 'error': 'APPS_SCRIPT_SECRET is not configured.'}, status=500)
        
    payload = {
        "action": "request_refill",
        "secret_token": secret
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        res_data = response.json()
        if res_data.get('success'):
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'error': res_data.get('error', 'Unknown Apps Script error')})
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to request refill from Apps Script Web App: {e}")
        return JsonResponse({'success': False, 'error': f"Failed to connect to Google Apps Script: {str(e)}"}, status=500)
