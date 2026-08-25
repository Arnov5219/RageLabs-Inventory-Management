from django.db import migrations

def create_branches(apps, schema_editor):
    Branch = apps.get_model('inventory', 'Branch')
    Inventory = apps.get_model('inventory', 'Inventory')
    MonthlyInventory = apps.get_model('inventory', 'MonthlyInventory')
    DailyInventory = apps.get_model('inventory', 'DailyInventory')
    StockHistory = apps.get_model('inventory', 'StockHistory')
    
    # Create branches
    b1, _ = Branch.objects.get_or_create(
        branch_code='OD3301LR-JGM',
        defaults={'branch_name': 'Jagamara', 'active': True}
    )
    b2, _ = Branch.objects.get_or_create(
        branch_code='OD3302LR-CSP',
        defaults={'branch_name': 'C. Spur', 'active': True}
    )
    
    # Assign existing records to JGM
    Inventory.objects.filter(branch__isnull=True).update(branch=b1)
    MonthlyInventory.objects.filter(branch__isnull=True).update(branch=b1)
    DailyInventory.objects.filter(branch__isnull=True).update(branch=b1)
    StockHistory.objects.filter(branch__isnull=True).update(branch=b1)

class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0008_branch_alter_inventory_options_and_more'),
    ]

    operations = [
        migrations.RunPython(create_branches),
    ]
