from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.utils import timezone
from datetime import date, datetime, time
from .models import Inventory, StockHistory, MonthlyInventory, DailyInventory
from .middleware import get_current_branch, get_current_user

def trigger_google_sheets_sync(history_record):
    from .models import SheetSyncLog
    from .google_sheets import export_to_google_sheets
    
    branch = history_record.branch
    if not branch or not branch.google_sheet_id:
        return
        
    sync_log, created = SheetSyncLog.objects.get_or_create(
        branch=branch,
        history_record=history_record,
        defaults={
            'status': 'PENDING',
            'attempt_count': 0
        }
    )
    
    sync_log.attempt_count += 1
    sync_log.last_attempt = timezone.now()
    
    class MockRecord:
        def __init__(self, date_val, product, base_stock, closing_stock, remaining_percentage, status_val):
            self.date = date_val
            self.product = product
            self.base_stock = base_stock
            self.closing_stock = closing_stock
            self.remaining_percentage = remaining_percentage
            self.status = status_val
            
    inv = history_record.product.inventory
    if inv.base_stock > 0:
        rem_pct = (inv.current_stock / inv.base_stock) * 100
    else:
        rem_pct = None
        
    mock_rec = MockRecord(
        date_val=history_record.created_at.date(),
        product=history_record.product,
        base_stock=inv.base_stock,
        closing_stock=inv.current_stock,
        remaining_percentage=rem_pct,
        status_val=inv.alert_status
    )
    
    category = 'supplies' if history_record.product.category == 'Laundry Supplies' else 'accessories'
    
    try:
        export_to_google_sheets(
            category, [mock_rec], spreadsheet_id=branch.google_sheet_id,
            branch_code=branch.branch_code, branch_name=branch.branch_name,
        )
        sync_log.status = 'SUCCESS'
        sync_log.error_message = None
        sync_log.synced_at = timezone.now()
        sync_log.save()
    except Exception as e:
        sync_log.status = 'FAILED'
        sync_log.error_message = str(e)
        sync_log.save()

def _run_sync_in_background(history_record_id):
    import threading
    from django.db import connections
    from .models import StockHistory
    try:
        try:
            history_record = StockHistory.objects.get(id=history_record_id)
            trigger_google_sheets_sync(history_record)
        except StockHistory.DoesNotExist:
            pass
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to sync google sheet in background: {e}")
    finally:
        connections.close_all()

def trigger_google_sheets_sync_flow(sh):
    from django.conf import settings
    import sys
    is_testing = 'test' in sys.argv or getattr(settings, 'TESTING', False)
    if is_testing:
        trigger_google_sheets_sync(sh)
    else:
        def start_bg_sync():
            import threading
            threading.Thread(
                target=_run_sync_in_background,
                args=(sh.id,),
                daemon=True
            ).start()
        transaction.on_commit(start_bg_sync)



def update_daily_summary(product, date_val, branch=None):
    if not branch:
        branch = get_current_branch()
        
    inv = Inventory.objects.filter(product=product, branch=branch).first()
    closing_stock = inv.current_stock if inv else Decimal('0.00')
    base_stock = inv.base_stock if inv else Decimal('0.00')
    
    summary, created = DailyInventory.objects.update_or_create(
        product=product,
        branch=branch,
        date=date_val,
        defaults={
            'base_stock': base_stock,
            'closing_stock': closing_stock
        }
    )
    return summary

def set_base_stock(product, quantity, date_val=None):
    if not isinstance(quantity, Decimal):
        try:
            quantity = Decimal(str(quantity))
        except Exception:
            raise ValidationError("Quantity must be a valid decimal number.")
            
    if quantity < 0:
        raise ValidationError("Base stock cannot be negative.")
        
    if date_val is None:
        date_val = timezone.localdate()
        
    month_start = date(date_val.year, date_val.month, 1)
    branch = get_current_branch()
    user = get_current_user()
    
    with transaction.atomic():
        inventory, created_inv = Inventory.objects.select_for_update().get_or_create(
            product=product,
            branch=branch
        )
        previous_quantity = inventory.current_stock
        
        inventory.base_stock = quantity
        # Set basic default thresholds if not defined
        if created_inv or (inventory.yellow_threshold == 0 and inventory.red_threshold == 0):
            inventory.yellow_threshold = Decimal(str(float(quantity) * 0.40))
            inventory.red_threshold = Decimal(str(float(quantity) * 0.10))
            
        inventory.save()
        
        monthly_inv, created = MonthlyInventory.objects.select_for_update().get_or_create(
            product=product,
            branch=branch,
            month=month_start,
            defaults={
                'base_stock': quantity,
                'current_stock': quantity,
                'total_added': Decimal('0.00'),
                'total_used': Decimal('0.00')
            }
        )
        if created:
            inventory.current_stock = quantity
            inventory.save()
            new_qty = quantity
        else:
            monthly_inv.base_stock = quantity
            monthly_inv.save()
            new_qty = inventory.current_stock
            
        now_time = timezone.now().time()
        history_created_at = timezone.make_aware(
            datetime.combine(date_val, now_time),
            timezone.get_current_timezone()
        )
        sh = StockHistory.objects.create(
            product=product,
            branch=branch,
            user=user,
            change_type='SET_BASE',
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=new_qty,
            notes="Established monthly base stock",
            base_stock=quantity,
            remaining_percentage=monthly_inv.remaining_percentage,
            created_at=history_created_at
        )
        
        update_daily_summary(product, date_val, branch=branch)
        trigger_google_sheets_sync_flow(sh)
        return monthly_inv

def add_stock(product, quantity, notes=None, date_val=None):
    if not isinstance(quantity, Decimal):
        try:
            quantity = Decimal(str(quantity))
        except Exception:
            raise ValidationError("Quantity must be a valid decimal number.")
            
    if quantity <= 0:
        raise ValidationError("Quantity to add must be greater than zero.")
        
    if date_val is None:
        date_val = timezone.localdate()
        
    month_start = date(date_val.year, date_val.month, 1)
    branch = get_current_branch()
    user = get_current_user()
        
    with transaction.atomic():
        inventory, created = Inventory.objects.select_for_update().get_or_create(
            product=product,
            branch=branch
        )
        previous_quantity = inventory.current_stock
        new_quantity = previous_quantity + quantity
        
        inventory.current_stock = new_quantity
        inventory.save()
        
        monthly_exists = MonthlyInventory.objects.filter(product=product, month=month_start, branch=branch).exists()
        
        if not monthly_exists:
            monthly_inv = MonthlyInventory.objects.create(
                product=product,
                branch=branch,
                month=month_start,
                base_stock=inventory.base_stock,
                current_stock=new_quantity,
                total_added=quantity,
                total_used=Decimal('0.00')
            )
        else:
            monthly_inv = MonthlyInventory.objects.select_for_update().get(product=product, month=month_start, branch=branch)
            monthly_inv.current_stock = new_quantity
            monthly_inv.total_added += quantity
            monthly_inv.save()
        
        now_time = timezone.now().time()
        history_created_at = timezone.make_aware(
            datetime.combine(date_val, now_time),
            timezone.get_current_timezone()
        )
        sh = StockHistory.objects.create(
            product=product,
            branch=branch,
            user=user,
            change_type='ADD',
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            notes=notes,
            base_stock=monthly_inv.base_stock,
            remaining_percentage=monthly_inv.remaining_percentage,
            created_at=history_created_at
        )
        
        update_daily_summary(product, date_val, branch=branch)
        trigger_google_sheets_sync_flow(sh)
        return inventory

def use_stock(product, quantity, notes=None, date_val=None):
    if not isinstance(quantity, Decimal):
        try:
            quantity = Decimal(str(quantity))
        except Exception:
            raise ValidationError("Quantity must be a valid decimal number.")
            
    if quantity <= 0:
        raise ValidationError("Quantity to use must be greater than zero.")
        
    if date_val is None:
        date_val = timezone.localdate()
        
    month_start = date(date_val.year, date_val.month, 1)
    branch = get_current_branch()
    user = get_current_user()
        
    with transaction.atomic():
        inventory, created = Inventory.objects.select_for_update().get_or_create(
            product=product,
            branch=branch
        )
        previous_quantity = inventory.current_stock
        
        if previous_quantity < quantity:
            raise ValidationError(f"Insufficient stock. Cannot use {quantity} when only {previous_quantity} is available.")
            
        new_quantity = previous_quantity - quantity
        inventory.current_stock = new_quantity
        inventory.save()
        
        monthly_exists = MonthlyInventory.objects.filter(product=product, month=month_start, branch=branch).exists()
        
        if not monthly_exists:
            monthly_inv = MonthlyInventory.objects.create(
                product=product,
                branch=branch,
                month=month_start,
                base_stock=inventory.base_stock,
                current_stock=new_quantity,
                total_added=Decimal('0.00'),
                total_used=quantity
            )
        else:
            monthly_inv = MonthlyInventory.objects.select_for_update().get(product=product, month=month_start, branch=branch)
            monthly_inv.current_stock = new_quantity
            monthly_inv.total_used += quantity
            if monthly_inv.current_stock < 0:
                monthly_inv.current_stock = Decimal('0.00')
            monthly_inv.save()
        
        now_time = timezone.now().time()
        history_created_at = timezone.make_aware(
            datetime.combine(date_val, now_time),
            timezone.get_current_timezone()
        )
        sh = StockHistory.objects.create(
            product=product,
            branch=branch,
            user=user,
            change_type='USE',
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            notes=notes,
            base_stock=monthly_inv.base_stock,
            remaining_percentage=monthly_inv.remaining_percentage,
            created_at=history_created_at
        )
        
        update_daily_summary(product, date_val, branch=branch)
        trigger_google_sheets_sync_flow(sh)
        return inventory

def edit_stock(product, new_quantity, notes=None, date_val=None):
    if not isinstance(new_quantity, Decimal):
        try:
            new_quantity = Decimal(str(new_quantity))
        except Exception:
            raise ValidationError("Quantity must be a valid decimal number.")
            
    if new_quantity < 0:
        raise ValidationError("Quantity cannot be negative.")
        
    if new_quantity % 1 != 0:
        raise ValidationError("Quantity must be a whole number.")
        
    if date_val is None:
        date_val = timezone.localdate()
        
    month_start = date(date_val.year, date_val.month, 1)
    branch = get_current_branch()
    user = get_current_user()
        
    with transaction.atomic():
        inventory, created = Inventory.objects.select_for_update().get_or_create(
            product=product,
            branch=branch
        )
        previous_quantity = inventory.current_stock
        
        monthly_exists = MonthlyInventory.objects.filter(product=product, month=month_start, branch=branch).exists()
        
        if not monthly_exists:
            monthly_inv = MonthlyInventory.objects.create(
                product=product,
                branch=branch,
                month=month_start,
                base_stock=inventory.base_stock,
                current_stock=new_quantity,
                total_added=Decimal('0.00'),
                total_used=Decimal('0.00')
            )
            inventory.current_stock = new_quantity
            inventory.save()
            
            now_time = timezone.now().time()
            history_created_at = timezone.make_aware(
                datetime.combine(date_val, now_time),
                timezone.get_current_timezone()
            )
            sh = StockHistory.objects.create(
                product=product,
                branch=branch,
                user=user,
                change_type='ADD' if new_quantity >= previous_quantity else 'USE',
                quantity=abs(new_quantity - previous_quantity),
                previous_quantity=previous_quantity,
                new_quantity=new_quantity,
                notes=notes or "Stock quantity edited",
                base_stock=monthly_inv.base_stock,
                remaining_percentage=monthly_inv.remaining_percentage,
                created_at=history_created_at
            )
            
            update_daily_summary(product, date_val, branch=branch)
            trigger_google_sheets_sync_flow(sh)
            return inventory
            
        if new_quantity > previous_quantity:
            diff = new_quantity - previous_quantity
            return add_stock(product, diff, notes=notes or "Stock quantity edited", date_val=date_val)
        elif new_quantity < previous_quantity:
            diff = previous_quantity - new_quantity
            return use_stock(product, diff, notes=notes or "Stock quantity edited", date_val=date_val)
        else:
            update_daily_summary(product, date_val, branch=branch)
            return inventory
