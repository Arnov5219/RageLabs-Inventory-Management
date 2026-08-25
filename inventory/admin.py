from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Product, Inventory, MonthlyInventory, StockHistory, Branch, EmployeeProfile, SheetSyncLog

class EmployeeProfileInline(admin.StackedInline):
    model = EmployeeProfile
    can_delete = False
    verbose_name_plural = 'Employee Profile'

class UserAdmin(BaseUserAdmin):
    inlines = (EmployeeProfileInline,)

admin.site.unregister(User)
admin.site.register(User, UserAdmin)

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('branch_code', 'branch_name', 'google_sheet_id', 'active', 'created_at')
    list_filter = ('active',)
    search_fields = ('branch_code', 'branch_name')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    fields = ('name', 'category', 'unit', 'product_size', 'image', 'is_active')
    list_display = ('name', 'category', 'product_size', 'unit', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    ordering = ('name',)

@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'base_stock', 'current_stock', 'yellow_threshold', 'red_threshold', 'alert_status', 'updated_at')
    list_filter = ('branch', 'alert_status')
    search_fields = ('product__name', 'branch__branch_name')

@admin.register(StockHistory)
class StockHistoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'user', 'transaction_type', 'quantity', 'opening_stock', 'closing_stock', 'created_at')
    list_filter = ('transaction_type', 'branch')
    search_fields = ('product__name', 'user__username')

@admin.register(SheetSyncLog)
class SheetSyncLogAdmin(admin.ModelAdmin):
    list_display = ('branch', 'history_record', 'status', 'attempt_count', 'last_attempt', 'synced_at')
    list_filter = ('status', 'branch')
    search_fields = ('branch__branch_name', 'error_message')
