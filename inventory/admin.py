from django.contrib import admin
from .models import Product, Inventory, MonthlyInventory, StockHistory

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    fields = ('name', 'category', 'unit', 'product_size', 'image', 'is_active')
    list_display = ('name', 'category', 'product_size', 'unit', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    ordering = ('name',)



@admin.register(StockHistory)
class StockHistoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'change_type', 'quantity', 'previous_quantity', 'new_quantity', 'created_at')
    list_filter = ('change_type',)
    search_fields = ('product__name',)
