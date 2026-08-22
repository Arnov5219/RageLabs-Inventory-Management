from django.db import models
from decimal import Decimal
from datetime import date
from django.utils import timezone

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
        now = timezone.now()
        month_start = date(now.year, now.month, 1)
        return self.monthly_inventories.filter(month=month_start).first()

    @property
    def remaining_percentage(self):
        monthly = self.current_monthly_inventory
        if monthly:
            return monthly.remaining_percentage
        return None

    @property
    def stock_status(self):
        monthly = self.current_monthly_inventory
        if monthly:
            return monthly.status
        return "No Base Stock"

class Inventory(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='inventory')
    current_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_low_stock(self):
        return self.current_quantity < self.low_stock_threshold

    def __str__(self):
        return f"{self.product.name} Inventory"

class MonthlyInventory(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='monthly_inventories')
    month = models.DateField(help_text="First day of the month")
    base_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    current_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_added = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_used = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'month')
        verbose_name_plural = "Monthly Inventories"

    def __str__(self):
        return f"{self.product.name} - {self.month.strftime('%B %Y')}"

    @property
    def remaining_percentage(self):
        if self.base_stock <= 0:
            return None
        return (self.current_stock / self.base_stock) * 100

    @property
    def status(self):
        pct = self.remaining_percentage
        if pct is None:
            return "No Base Stock"
        if pct >= 80:
            return "GREEN"
        elif pct > 10:
            return "YELLOW"
        else:
            return "RED"

class StockHistory(models.Model):
    CHANGE_TYPE_CHOICES = [
        ('ADD', 'ADD'),
        ('USE', 'USE'),
        ('SET_BASE', 'SET_BASE'),
    ]
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_history')
    change_type = models.CharField(max_length=10, choices=CHANGE_TYPE_CHOICES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    previous_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    new_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    # Snapshot fields for Monthly Base Stock system
    base_stock = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    remaining_percentage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.change_type} {self.quantity} for {self.product.name}"


class DailyInventory(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='daily_inventories')
    date = models.DateField()
    base_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    closing_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'date')
        verbose_name_plural = "Daily Inventories"

    def __str__(self):
        return f"{self.product.name} - {self.date}"

    @property
    def remaining_percentage(self):
        if self.base_stock <= 0:
            return None
        return (self.closing_stock / self.base_stock) * 100

    @property
    def status(self):
        pct = self.remaining_percentage
        if pct is None:
            return "No Base Stock"
        if pct >= 80:
            return "GREEN"
        elif pct > 10:
            return "YELLOW"
        else:
            return "RED"

