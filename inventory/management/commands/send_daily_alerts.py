from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
from inventory.models import Branch, Product, DailyInventory, Inventory

class Command(BaseCommand):
    help = 'Sends the daily consolidated email alert for low stock products.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        yesterday = today - timezone.timedelta(days=1)
        
        branches = Branch.objects.filter(active=True)
        products = Product.objects.filter(is_active=True)
        
        email_body = []
        email_body.append(f"Daily Consolidated Stock Alert - {today.strftime('%B %d, %Y')}\n")
        email_body.append("=" * 60 + "\n")
        
        overall_red_count = 0
        overall_yellow_count = 0
        overall_total_refill = Decimal('0.00')
        branches_requiring_attention = 0
        
        for branch in branches:
            branch_alerts = []
            branch_red_count = 0
            branch_yellow_count = 0
            branch_total_refill = Decimal('0.00')
            
            for product in products:
                # Get current inventory
                inv, _ = Inventory.objects.get_or_create(
                    branch=branch,
                    product=product,
                    defaults={
                        'current_stock': Decimal('0.00'),
                        'base_stock': Decimal('0.00'),
                        'yellow_threshold': Decimal('0.00'),
                        'red_threshold': Decimal('0.00'),
                    }
                )
                
                # Get yesterday's closing daily inventory
                yesterday_daily = DailyInventory.objects.filter(
                    branch=branch,
                    product=product,
                    date=yesterday
                ).first()
                
                # Determine yesterday's status
                if yesterday_daily:
                    y_stock = yesterday_daily.closing_stock
                    if y_stock == Decimal('0.00'):
                        y_status = 'OUT_OF_STOCK'
                    elif y_stock <= inv.red_threshold:
                        y_status = 'RED'
                    elif y_stock <= inv.yellow_threshold:
                        y_status = 'YELLOW'
                    else:
                        y_status = 'NORMAL'
                else:
                    y_status = 'NORMAL'
                
                # Today's status
                t_status = inv.alert_status
                
                # Determine alert tracking state
                state_label = None
                if t_status in ['RED', 'OUT_OF_STOCK']:
                    if y_status in ['RED', 'OUT_OF_STOCK']:
                        state_label = 'Still RED'
                    else:
                        state_label = 'Newly RED'
                    branch_red_count += 1
                elif t_status == 'YELLOW':
                    if y_status == 'YELLOW':
                        state_label = 'Still YELLOW'
                    else:
                        state_label = 'Newly YELLOW'
                    branch_yellow_count += 1
                elif t_status == 'NORMAL' and y_status in ['RED', 'OUT_OF_STOCK', 'YELLOW']:
                    state_label = 'Returned to NORMAL'
                
                if state_label:
                    refill = max(Decimal('0.00'), inv.base_stock - inv.current_stock)
                    branch_total_refill += refill
                    
                    branch_alerts.append({
                        'product': product.name,
                        'current_stock': inv.current_stock,
                        'base_stock': inv.base_stock,
                        'status': t_status,
                        'state_label': state_label,
                        'refill': refill,
                        'unit': product.unit
                    })
            
            if branch_alerts:
                branches_requiring_attention += 1
                overall_red_count += branch_red_count
                overall_yellow_count += branch_yellow_count
                overall_total_refill += branch_total_refill
                
                email_body.append(f"Branch: {branch.branch_name} ({branch.branch_code})")
                email_body.append("-" * 40)
                for alert in branch_alerts:
                    email_body.append(
                        f"  * {alert['product']}: {alert['current_stock']:.0f} / {alert['base_stock']:.0f} {alert['unit']} remaining ({alert['state_label']}) - Required Refill: {alert['refill']:.0f} {alert['unit']}"
                    )
                email_body.append(f"  --> RED count: {branch_red_count} | YELLOW count: {branch_yellow_count} | Total units required: {branch_total_refill:.0f}\n")
        
        email_body.append("=" * 60)
        email_body.append("OVERALL SUMMARY")
        email_body.append(f"  * Branches requiring attention: {branches_requiring_attention}")
        email_body.append(f"  * Total RED alerts: {overall_red_count}")
        email_body.append(f"  * Total YELLOW alerts: {overall_yellow_count}")
        email_body.append(f"  * Total units required across all branches: {overall_total_refill:.0f}\n")
        
        email_content = "\n".join(email_body)
        
        # Send Email
        admin_emails = [addr for name, addr in getattr(settings, 'ADMINS', [])]
        if not admin_emails:
            admin_emails = ['admin@laundryrage.com']
            
        send_mail(
            subject=f"Daily Consolidated Stock Alert: {today.strftime('%Y-%m-%d')} - {overall_red_count} RED / {overall_yellow_count} YELLOW Alerts",
            message=email_content,
            from_email='alerts@laundryrage.com',
            recipient_list=admin_emails,
            fail_silently=False,
        )
        
        self.stdout.write(self.style.SUCCESS("Successfully compiled and sent daily consolidated email alert."))
        self.stdout.write(email_content)
