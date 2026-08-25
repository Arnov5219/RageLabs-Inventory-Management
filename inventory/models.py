from django.db import models
from decimal import Decimal
from datetime import date
from django.utils import timezone
from django.contrib.auth.models import User

class Branch(models.Model):
    branch_code = models.CharField(max_length=50, unique=True)
    branch_name = models.CharField(max_length=255)
    google_sheet_id = models.CharField(max_length=255, null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Branches"

    def __str__(self):
        return f"{self.branch_name} ({self.branch_code})"

class EmployeeProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee_profile')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')

    def __str__(self):
        return f"{self.user.username}'s Profile ({self.branch})"

class Product(models.Model):
    CATEGORY_CHOICES = [
        ('Laundry Supplies', 'Laundry Supplies'),
        ('Accessories', 'Accessories'),
    ]
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    unit = models.CharField(max_length=50, help_text="e.g., L, bottles, pcs")
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    supplier = models.CharField(max_length=255)
    product_size = models.CharField(max_length=50, blank=True, default='', help_text="e.g., 750 ml, 1 L, 500 g")
    image = models.ImageField(upload_to='products/', blank=True, null=True, verbose_name='Product Image')
    
    is_active = models.BooleanField(default=True, help_text="Soft-deletion state")

    def __str__(self):
        return self.name

    @property
    def current_monthly_inventory(self):
        from .middleware import get_current_branch
        branch = get_current_branch()
        
        now = timezone.now()
        month_start = date(now.year, now.month, 1)
        
        if branch:
            monthly_inv, _ = MonthlyInventory.objects.get_or_create(
                branch=branch,
                product=self,
                month=month_start,
                defaults={
                    'base_stock': Decimal('0.00'),
                    'current_stock': Decimal('0.00'),
                    'total_added': Decimal('0.00'),
                    'total_used': Decimal('0.00')
                }
            )
            return monthly_inv
            
        monthly_inv, _ = MonthlyInventory.objects.get_or_create(
            product=self,
            month=month_start,
            branch=None,
            defaults={
                'base_stock': Decimal('0.00'),
                'current_stock': Decimal('0.00'),
                'total_added': Decimal('0.00'),
                'total_used': Decimal('0.00')
            }
        )
        return monthly_inv

    @property
    def inventory(self):
        from .middleware import get_current_branch
        branch = get_current_branch()
            
        if branch:
            inv, _ = Inventory.objects.get_or_create(
                branch=branch,
                product=self,
                defaults={
                    'current_stock': Decimal('0.00'),
                    'base_stock': Decimal('0.00'),
                    'yellow_threshold': Decimal('0.00'),
                    'red_threshold': Decimal('0.00'),
                    'current_quantity': Decimal('0.00'),
                    'low_stock_threshold': Decimal('0.00')
                }
            )
            return inv
            
        inv, _ = Inventory.objects.get_or_create(
            product=self,
            branch=None,
            defaults={
                'current_stock': Decimal('0.00'),
                'base_stock': Decimal('0.00'),
                'yellow_threshold': Decimal('0.00'),
                'red_threshold': Decimal('0.00'),
                'current_quantity': Decimal('0.00'),
                'low_stock_threshold': Decimal('0.00')
            }
        )
        return inv

    @property
    def remaining_percentage(self):
        inv = self.inventory
        if inv and inv.base_stock > 0:
            return (inv.current_stock / inv.base_stock) * 100
        return None

    @property
    def stock_status(self):
        from .middleware import get_current_branch
        branch = get_current_branch()
        if not branch:
            monthly = self.current_monthly_inventory
            if monthly:
                return monthly.status
            return "No Base Stock"
            
        inv = self.inventory
        if inv:
            if inv.alert_status == 'OUT_OF_STOCK':
                return 'RED'
            elif inv.alert_status == 'RED':
                return 'RED'
            elif inv.alert_status == 'YELLOW':
                return 'YELLOW'
            else:
                return 'GREEN'
        return "No Base Stock"

class Inventory(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='inventories', null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='branch_inventories')
    
    # Old fields preserved for compatibility
    current_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # New fields
    base_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    current_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    yellow_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    red_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    alert_status = models.CharField(max_length=50, default='NORMAL')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_low_stock(self):
        # Compatibility property
        return self.current_stock <= self.red_threshold

    @property
    def required_refill(self):
        if self.base_stock > self.current_stock:
            return self.base_stock - self.current_stock
        return Decimal('0.00')

    class Meta:
        unique_together = ('branch', 'product')
        verbose_name_plural = "Inventories"

    def save(self, *args, **kwargs):
        # Track status transition
        previous_status = 'NORMAL'
        if self.pk:
            try:
                orig = Inventory.objects.get(pk=self.pk)
                previous_status = orig.alert_status
            except Inventory.DoesNotExist:
                pass

        # Smart sync for backwards compatibility
        if self.pk is None:
            if self.current_stock == Decimal('0.00') and self.current_quantity != Decimal('0.00'):
                self.current_stock = self.current_quantity
            elif self.current_quantity == Decimal('0.00') and self.current_stock != Decimal('0.00'):
                self.current_quantity = self.current_stock

            if self.red_threshold == Decimal('0.00') and self.low_stock_threshold != Decimal('0.00'):
                self.red_threshold = self.low_stock_threshold
            elif self.low_stock_threshold == Decimal('0.00') and self.red_threshold != Decimal('0.00'):
                self.low_stock_threshold = self.red_threshold
        else:
            if self.current_stock != self.current_quantity:
                self.current_quantity = self.current_stock
            if self.red_threshold != self.low_stock_threshold:
                self.low_stock_threshold = self.red_threshold

        # Recalculate Alert Status
        if self.current_stock == Decimal('0.00'):
            self.alert_status = 'OUT_OF_STOCK'
        elif self.current_stock <= self.red_threshold:
            self.alert_status = 'RED'
        elif self.current_stock <= self.yellow_threshold:
            self.alert_status = 'YELLOW'
        else:
            self.alert_status = 'NORMAL'

        super().save(*args, **kwargs)

        # Trigger transition alerts / recovery
        RED_STATUSES = ('RED', 'OUT_OF_STOCK')
        prev_is_red = previous_status in RED_STATUSES
        curr_is_red = self.alert_status in RED_STATUSES

        if prev_is_red != curr_is_red:
            # Transition occurred!
            alert = InventoryAlert.objects.create(
                product=self.product,
                branch=self.branch,
                category=self.product.category,
                previous_status=previous_status,
                current_status=self.alert_status,
                current_stock=self.current_stock,
                base_stock=self.base_stock,
                refill_required=(self.base_stock - self.current_stock) if self.base_stock > self.current_stock else Decimal('0.00')
            )
            def start_bg_alert_sync(alert_id, entering_red):
                import threading
                from django.db import connections
                from .models import InventoryAlert
                from .google_sheets import export_alert_to_google_sheets, send_alert_email

                def bg_target():
                    try:
                        try:
                            a = InventoryAlert.objects.get(id=alert_id)
                            # Export to Red Alerts Google Sheet (all transitions)
                            try:
                                export_alert_to_google_sheets(a)
                            except Exception as e:
                                import logging
                                logging.getLogger(__name__).error(
                                    f"Failed to export RED alert to Google Sheets: {e}"
                                )
                            # Send email only when entering RED/OUT_OF_STOCK, not on recovery
                            if entering_red:
                                try:
                                    send_alert_email(a)
                                except Exception as e:
                                    import logging
                                    logging.getLogger(__name__).error(
                                        f"Failed to send RED alert email: {e}"
                                    )
                        except InventoryAlert.DoesNotExist:
                            pass
                    finally:
                        connections.close_all()

                threading.Thread(target=bg_target, daemon=True).start()

            # entering_red = True when transitioning INTO red (not recovery)
            entering_red = curr_is_red and not prev_is_red
            from django.db import transaction
            transaction.on_commit(lambda: start_bg_alert_sync(alert.id, entering_red))

    def __str__(self):
        branch_name = self.branch.branch_code if self.branch else "Global"
        return f"{self.product.name} ({branch_name}) Inventory"

class MonthlyInventory(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='monthly_inventories', null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='monthly_inventories')
    month = models.DateField(help_text="First day of the month")
    base_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    current_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_added = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_used = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'product', 'month')
        verbose_name_plural = "Monthly Inventories"

    def __str__(self):
        branch_name = self.branch.branch_code if self.branch else "Global"
        return f"{self.product.name} ({branch_name}) - {self.month.strftime('%B %Y')}"

    @property
    def remaining_percentage(self):
        if self.base_stock <= 0:
            return None
        return (self.current_stock / self.base_stock) * 100

    @property
    def required_refill(self):
        if self.base_stock > self.current_stock:
            return self.base_stock - self.current_stock
        return Decimal('0.00')

    @property
    def status(self):
        if not self.branch:
            pct = self.remaining_percentage
            if pct is None:
                return "No Base Stock"
            if pct >= 80:
                return "GREEN"
            elif pct > 10:
                return "YELLOW"
            else:
                return "RED"

        inv = Inventory.objects.filter(product=self.product, branch=self.branch).first()
        if inv:
            if inv.alert_status == 'OUT_OF_STOCK':
                return 'RED'
            elif inv.alert_status == 'RED':
                return 'RED'
            elif inv.alert_status == 'YELLOW':
                return 'YELLOW'
            else:
                return 'GREEN'
        return 'GREEN'

class StockHistory(models.Model):
    CHANGE_TYPE_CHOICES = [
        ('ADD', 'ADD'),
        ('USE', 'USE'),
        ('SET_BASE', 'SET_BASE'),
    ]
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='stock_history', null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_history')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_history')
    
    # Old fields preserved
    change_type = models.CharField(max_length=10, choices=CHANGE_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    previous_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    new_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    base_stock = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    remaining_percentage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # New fields
    opening_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    added_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    removed_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    closing_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    transaction_type = models.CharField(max_length=20, default='EDIT')

    def save(self, *args, **kwargs):
        # Sync old and new fields
        if self.transaction_type == 'EDIT':
            self.transaction_type = self.change_type

        if self.previous_quantity != self.opening_stock:
            self.opening_stock = self.previous_quantity
        elif self.opening_stock != Decimal('0.00'):
            self.previous_quantity = self.opening_stock

        if self.new_quantity != self.closing_stock:
            self.closing_stock = self.new_quantity
        elif self.closing_stock != Decimal('0.00'):
            self.new_quantity = self.closing_stock

        if self.change_type != self.transaction_type:
            self.transaction_type = self.change_type

        if self.transaction_type == 'ADD':
            self.added_quantity = self.quantity
            self.removed_quantity = Decimal('0.00')
        elif self.transaction_type == 'USE':
            self.removed_quantity = self.quantity
            self.added_quantity = Decimal('0.00')

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_type} {self.quantity} for {self.product.name}"

class DailyInventory(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='daily_inventories', null=True, blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='daily_inventories')
    date = models.DateField()
    base_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    closing_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'product', 'date')
        verbose_name_plural = "Daily Inventories"

    def __str__(self):
        branch_name = self.branch.branch_code if self.branch else "Global"
        return f"{self.product.name} ({branch_name}) - {self.date}"

    @property
    def remaining_percentage(self):
        if self.base_stock <= 0:
            return None
        return (self.closing_stock / self.base_stock) * 100

    @property
    def status(self):
        if not self.branch:
            pct = self.remaining_percentage
            if pct is None:
                return "No Base Stock"
            if pct >= 80:
                return "GREEN"
            elif pct > 10:
                return "YELLOW"
            else:
                return "RED"

        inv = self.product.inventory
        if inv:
            if inv.alert_status == 'OUT_OF_STOCK':
                return 'RED'
            elif inv.alert_status == 'RED':
                return 'RED'
            elif inv.alert_status == 'YELLOW':
                return 'YELLOW'
            else:
                return 'GREEN'
        return 'GREEN'

class SheetSyncLog(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'PENDING'),
        ('SUCCESS', 'SUCCESS'),
        ('FAILED', 'FAILED'),
    ]
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='sync_logs')
    history_record = models.ForeignKey(StockHistory, on_delete=models.CASCADE, related_name='sync_logs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    attempt_count = models.IntegerField(default=0)
    last_attempt = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Sync Log #{self.id} - {self.branch.branch_code} - {self.status}"


class InventoryAlert(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='alerts')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='alerts', null=True, blank=True)
    category = models.CharField(max_length=100)
    previous_status = models.CharField(max_length=50)
    current_status = models.CharField(max_length=50)
    current_stock = models.DecimalField(max_digits=10, decimal_places=2)
    base_stock = models.DecimalField(max_digits=10, decimal_places=2)
    refill_required = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        branch_code = self.branch.branch_code if self.branch else "Global"
        return f"Alert for {self.product.name} ({branch_code}) - {self.current_status} (Refill: {self.refill_required})"


