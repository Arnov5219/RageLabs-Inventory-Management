from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from inventory.models import Product, Inventory, StockHistory
from django.utils import timezone
import datetime

class Command(BaseCommand):
    help = 'Seeds the database with initial laundry products, inventory, and stock history.'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database data...')
        
        # Clear existing data
        StockHistory.objects.all().delete()
        Inventory.objects.all().delete()
        Product.objects.all().delete()
        
        # Define seed products
        supplies_data = [
            {
                'name': 'Premium Detergent Pods',
                'unit': 'pcs',
                
                'supplier': 'FreshCorp Industries',
                'current': Decimal('120.00'),
                'threshold': Decimal('20.00'),
                'history': [
                    ('ADD', Decimal('150.00'), 'Initial stock delivery', 10),
                    ('USE', Decimal('30.00'), 'Daily wash usage', 5),
                ]
            },
            {
                'name': 'Fabric Softener Lavender',
                'unit': 'bottles',
                
                'supplier': 'FloraCare Co',
                'current': Decimal('8.00'),
                'threshold': Decimal('12.00'),
                'history': [
                    ('ADD', Decimal('10.00'), 'Delivery from FloraCare', 8),
                    ('USE', Decimal('2.00'), 'Spill damage and usage', 2),
                ]
            },
            {
                'name': 'Oxi-Bleach Powder',
                'unit': 'kg',
                
                'supplier': 'OxiCleaners Ltd',
                'current': Decimal('15.00'),
                'threshold': Decimal('10.00'),
                'history': [
                    ('ADD', Decimal('20.00'), 'Standard warehouse order', 12),
                    ('USE', Decimal('5.00'), 'Heavy stain service usage', 4),
                ]
            },
            {
                'name': 'Scent Booster Beads',
                'unit': 'pcs',
                
                'supplier': 'ScentMagic',
                'current': Decimal('2.00'),
                'threshold': Decimal('6.00'),
                'history': [
                    ('ADD', Decimal('10.00'), 'Direct purchase', 6),
                    ('USE', Decimal('8.00'), 'Hotel order execution', 1),
                ]
            }
        ]
        
        accessories_data = [
            {
                'name': 'Heavy Duty Laundry Basket',
                'unit': 'pcs',
                
                'supplier': 'RagePlast',
                'current': Decimal('25.00'),
                'threshold': Decimal('5.00'),
                'history': [
                    ('ADD', Decimal('30.00'), 'Store opening stock', 15),
                    ('USE', Decimal('5.00'), 'Replacement of broken baskets', 3),
                ]
            },
            {
                'name': 'Collapsible Ironing Board',
                'unit': 'pcs',
                
                'supplier': 'IronSteel Inc',
                'current': Decimal('4.00'),
                'threshold': Decimal('5.00'),
                'history': [
                    ('ADD', Decimal('6.00'), 'Supplier batch delivery', 9),
                    ('USE', Decimal('2.00'), 'Customer damage replacements', 1),
                ]
            },
            {
                'name': 'Mesh Laundry Bags (3-pack)',
                'unit': 'pcs',
                
                'supplier': 'BagFlow Ltd',
                'current': Decimal('9.00'),
                'threshold': Decimal('8.00'),
                'history': [
                    ('ADD', Decimal('12.00'), 'Box delivery', 7),
                    ('USE', Decimal('3.00'), 'Given to premium club members', 2),
                ]
            },
            {
                'name': 'Luxury Wooden Hangers',
                'unit': 'pcs',
                
                'supplier': 'HangerCraft',
                'current': Decimal('150.00'),
                'threshold': Decimal('30.00'),
                'history': [
                    ('ADD', Decimal('200.00'), 'Bulk crate delivery', 20),
                    ('USE', Decimal('50.00'), 'Suite installations', 5),
                ]
            }
        ]
        
        with transaction.atomic():
            self._create_records(supplies_data, 'Laundry Supplies')
            self._create_records(accessories_data, 'Accessories')
            
        self.stdout.write(self.style.SUCCESS('Successfully seeded database with products and history.'))

    def _create_records(self, dataset, category):
        for data in dataset:
            product = Product.objects.create(
                name=data['name'],
                category=category,
                unit=data['unit'],
                
                supplier=data['supplier']
            )
            
            # Inventory
            inventory = Inventory.objects.create(
                product=product,
                current_quantity=data['current'],
                low_stock_threshold=data['threshold']
            )
            
            # Stock history
            current_sim_qty = Decimal('0.00')
            
            for index, (change_type, qty, note, days_ago) in enumerate(data['history']):
                prev_qty = current_sim_qty
                if change_type == 'ADD':
                    new_qty = prev_qty + qty
                else:
                    new_qty = prev_qty - qty
                    if new_qty < 0:
                        new_qty = Decimal('0.00')
                
                history_time = timezone.now() - datetime.timedelta(days=days_ago)
                
                sh = StockHistory.objects.create(
                    product=product,
                    change_type=change_type,
                    quantity=qty,
                    previous_quantity=prev_qty,
                    new_quantity=new_qty,
                    notes=note
                )
                # Overwrite auto_now_add creation time for simulation using update
                StockHistory.objects.filter(id=sh.id).update(created_at=history_time)
                
                current_sim_qty = new_qty
