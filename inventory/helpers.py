from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.utils import timezone
from datetime import date, datetime, time
from .models import Inventory, StockHistory, MonthlyInventory, DailyInventory

def update_daily_summary(product, date_val):
    month_start = date(date_val.year, date_val.month, 1)
    monthly_inv = MonthlyInventory.objects.filter(product=product, month=month_start).first()
    base_stock = monthly_inv.base_stock if monthly_inv else Decimal('0.00')
    
    inventory = Inventory.objects.filter(product=product).first()
    closing_stock = inventory.current_quantity if inventory else Decimal('0.00')
    
    summary, created = DailyInventory.objects.get_or_create(
        product=product,
        date=date_val,
        defaults={
            'base_stock': base_stock,
            'closing_stock': closing_stock
        }
    )
    if not created:
        summary.base_stock = base_stock
        summary.closing_stock = closing_stock
        summary.save()
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
        date_val = timezone.now().date()
        
    month_start = date(date_val.year, date_val.month, 1)
    
    with transaction.atomic():
        inventory, created_inv = Inventory.objects.select_for_update().get_or_create(product=product)
        previous_quantity = inventory.current_quantity
        
        monthly_inv, created = MonthlyInventory.objects.select_for_update().get_or_create(
            product=product,
            month=month_start,
            defaults={
                'base_stock': quantity,
                'current_stock': quantity,
                'total_added': Decimal('0.00'),
                'total_used': Decimal('0.00')
            }
        )
        if created:
            inventory.current_quantity = quantity
            inventory.save()
            new_qty = quantity
        else:
            monthly_inv.base_stock = quantity
            monthly_inv.save()
            new_qty = inventory.current_quantity
            
        now_time = timezone.now().time()
        history_created_at = timezone.make_aware(
            datetime.combine(date_val, now_time)
        )
            
        StockHistory.objects.create(
            product=product,
            change_type='SET_BASE',
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=new_qty,
            notes="Established monthly base stock",
            base_stock=quantity,
            remaining_percentage=monthly_inv.remaining_percentage,
            created_at=history_created_at
        )
        
        update_daily_summary(product, date_val)
        
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
        date_val = timezone.now().date()
        
    month_start = date(date_val.year, date_val.month, 1)
        
    with transaction.atomic():
        # Select for update to prevent race conditions during updates
        inventory, created = Inventory.objects.select_for_update().get_or_create(product=product)
        previous_quantity = inventory.current_quantity
        new_quantity = previous_quantity + quantity
        
        inventory.current_quantity = new_quantity
        inventory.save()
        
        # Monthly inventory update
        monthly_exists = MonthlyInventory.objects.filter(product=product, month=month_start).exists()
        
        if not monthly_exists:
            # First action of the month does NOT establish the base stock. It initializes it to 0.00
            monthly_inv = MonthlyInventory.objects.create(
                product=product,
                month=month_start,
                base_stock=Decimal('0.00'),
                current_stock=new_quantity,
                total_added=quantity,
                total_used=Decimal('0.00')
            )
        else:
            monthly_inv = MonthlyInventory.objects.select_for_update().get(product=product, month=month_start)
            monthly_inv.current_stock = new_quantity
            monthly_inv.total_added += quantity
            monthly_inv.save()
        
        now_time = timezone.now().time()
        history_created_at = timezone.make_aware(
            datetime.combine(date_val, now_time)
        )
        
        StockHistory.objects.create(
            product=product,
            change_type='ADD',
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            notes=notes,
            base_stock=monthly_inv.base_stock,
            remaining_percentage=monthly_inv.remaining_percentage,
            created_at=history_created_at
        )
        
        update_daily_summary(product, date_val)
        
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
        date_val = timezone.now().date()
        
    month_start = date(date_val.year, date_val.month, 1)
        
    with transaction.atomic():
        # Select for update to prevent race conditions during updates
        inventory, created = Inventory.objects.select_for_update().get_or_create(product=product)
        previous_quantity = inventory.current_quantity
        
        if previous_quantity < quantity:
            raise ValidationError(f"Insufficient stock. Cannot use {quantity} when only {previous_quantity} is available.")
            
        new_quantity = previous_quantity - quantity
        inventory.current_quantity = new_quantity
        inventory.save()
        
        # Monthly inventory update
        monthly_exists = MonthlyInventory.objects.filter(product=product, month=month_start).exists()
        
        if not monthly_exists:
            # First action of the month does NOT establish base stock. It initializes it to 0.00
            monthly_inv = MonthlyInventory.objects.create(
                product=product,
                month=month_start,
                base_stock=Decimal('0.00'),
                current_stock=new_quantity,
                total_added=Decimal('0.00'),
                total_used=quantity
            )
        else:
            monthly_inv = MonthlyInventory.objects.select_for_update().get(product=product, month=month_start)
            monthly_inv.current_stock = new_quantity
            monthly_inv.total_used += quantity
            if monthly_inv.current_stock < 0:
                monthly_inv.current_stock = Decimal('0.00')
            monthly_inv.save()
        
        now_time = timezone.now().time()
        history_created_at = timezone.make_aware(
            datetime.combine(date_val, now_time)
        )
        
        StockHistory.objects.create(
            product=product,
            change_type='USE',
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            notes=notes,
            base_stock=monthly_inv.base_stock,
            remaining_percentage=monthly_inv.remaining_percentage,
            created_at=history_created_at
        )
        
        update_daily_summary(product, date_val)
        
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
        date_val = timezone.now().date()
        
    month_start = date(date_val.year, date_val.month, 1)
        
    with transaction.atomic():
        # Select for update to prevent race conditions during updates
        inventory, created = Inventory.objects.select_for_update().get_or_create(product=product)
        previous_quantity = inventory.current_quantity
        
        # Ensure monthly inventory exists
        monthly_exists = MonthlyInventory.objects.filter(product=product, month=month_start).exists()
        
        if not monthly_exists:
            # First edit of the month does NOT establish base stock. It initializes it to 0.00
            monthly_inv = MonthlyInventory.objects.create(
                product=product,
                month=month_start,
                base_stock=Decimal('0.00'),
                current_stock=new_quantity,
                total_added=Decimal('0.00'),
                total_used=Decimal('0.00')
            )
            inventory.current_quantity = new_quantity
            inventory.save()
            
            now_time = timezone.now().time()
            history_created_at = timezone.make_aware(
                datetime.combine(date_val, now_time)
            )
            
            StockHistory.objects.create(
                product=product,
                change_type='ADD' if new_quantity >= previous_quantity else 'USE',
                quantity=abs(new_quantity - previous_quantity),
                previous_quantity=previous_quantity,
                new_quantity=new_quantity,
                notes=notes or "Stock quantity edited",
                base_stock=monthly_inv.base_stock,
                remaining_percentage=monthly_inv.remaining_percentage,
                created_at=history_created_at
            )
            
            update_daily_summary(product, date_val)
            
            return inventory
            
        if new_quantity > previous_quantity:
            diff = new_quantity - previous_quantity
            return add_stock(product, diff, notes=notes or "Stock quantity edited", date_val=date_val)
        elif new_quantity < previous_quantity:
            diff = previous_quantity - new_quantity
            return use_stock(product, diff, notes=notes or "Stock quantity edited", date_val=date_val)
        else:
            update_daily_summary(product, date_val)
            return inventory
