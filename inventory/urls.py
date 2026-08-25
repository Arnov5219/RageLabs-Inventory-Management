from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    
    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('branch/switch/', views.switch_branch_view, name='switch_branch'),
    
    # Category Browsing
    path('laundry-supplies/', views.supplies_view, name='laundry_supplies'),
    path('laundry-accessories/', views.accessories_view, name='laundry_accessories'),
    
    # Audit Trail History
    path('history/laundry-supplies/', views.supplies_history_view, name='history_laundry_supplies'),
    path('history/laundry-accessories/', views.accessories_history_view, name='history_laundry_accessories'),
    path('product/<int:product_id>/history/', views.product_history_detail_view, name='product_history_detail'),
    
    # Real-time AJAX adjustments
    path('stock/adjust-ajax/', views.adjust_stock_ajax, name='adjust_stock_ajax'),
    path('refill/request-ajax/', views.request_refill_ajax, name='request_refill_ajax'),
]
