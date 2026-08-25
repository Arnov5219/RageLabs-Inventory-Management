from django.test import TestCase, Client
from django.urls import reverse
from decimal import Decimal
from datetime import date
import json
from unittest.mock import patch

from .models import Branch, EmployeeProfile, Product, Inventory, StockHistory, MonthlyInventory, DailyInventory
from .helpers import add_stock, use_stock, edit_stock, set_base_stock
from .middleware import set_current_branch
from django.contrib.auth.models import User

class ProductPropertiesTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Premium Detergent Pods",
            category="Laundry Supplies",
            unit="pcs",
            cost=Decimal("0.50"),
            supplier="FreshCorp Industries"
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            current_quantity=Decimal("120.00"),
            low_stock_threshold=Decimal("10.00")
        )

    def test_product_properties_no_base(self):
        """remaining_percentage is None and status is 'No Base Stock' if no MonthlyInventory exists."""
        self.assertIsNone(self.product.remaining_percentage)
        self.assertEqual(self.product.stock_status, "No Base Stock")


class MonthlyBaseStockBusinessTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Fabric Softener Lavender",
            category="Laundry Supplies",
            unit="bottles",
            cost=Decimal("2.50"),
            supplier="FloraCare Co"
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            current_quantity=Decimal("0.00"),
            low_stock_threshold=Decimal("5.00")
        )

    def test_scenario_1_100_percent_green(self):
        """Test 1: Base = 20, Current = 20 -> GREEN status (100% remaining)."""
        set_base_stock(self.product, Decimal("20.00"))
        monthly = self.product.current_monthly_inventory
        self.assertEqual(monthly.base_stock, Decimal("20.00"))
        self.assertEqual(monthly.current_stock, Decimal("20.00"))
        self.assertEqual(monthly.remaining_percentage, 100.0)
        self.assertEqual(monthly.status, "GREEN")

    def test_scenario_2_80_percent_green(self):
        """Test 2: Base = 20, Current = 16 -> GREEN status (80% remaining)."""
        set_base_stock(self.product, Decimal("20.00"))
        use_stock(self.product, Decimal("4.00"))
        monthly = self.product.current_monthly_inventory
        self.assertEqual(monthly.current_stock, Decimal("16.00"))
        self.assertEqual(monthly.remaining_percentage, 80.0)
        self.assertEqual(monthly.status, "GREEN")

    def test_scenario_3_50_percent_yellow(self):
        """Test 3: Base = 20, Current = 10 -> YELLOW status (50% remaining)."""
        set_base_stock(self.product, Decimal("20.00"))
        use_stock(self.product, Decimal("10.00"))
        monthly = self.product.current_monthly_inventory
        self.assertEqual(monthly.current_stock, Decimal("10.00"))
        self.assertEqual(monthly.remaining_percentage, 50.0)
        self.assertEqual(monthly.status, "YELLOW")

    def test_scenario_4_25_percent_yellow(self):
        """Test 4: Base = 20, Current = 5 -> YELLOW status (25% remaining)."""
        set_base_stock(self.product, Decimal("20.00"))
        use_stock(self.product, Decimal("15.00"))
        monthly = self.product.current_monthly_inventory
        self.assertEqual(monthly.current_stock, Decimal("5.00"))
        self.assertEqual(monthly.remaining_percentage, 25.0)
        self.assertEqual(monthly.status, "YELLOW")

    def test_scenario_5_10_percent_red(self):
        """Test 5: Base = 20, Current = 2 -> RED status (10% remaining)."""
        set_base_stock(self.product, Decimal("20.00"))
        use_stock(self.product, Decimal("18.00"))
        monthly = self.product.current_monthly_inventory
        self.assertEqual(monthly.current_stock, Decimal("2.00"))
        self.assertEqual(monthly.remaining_percentage, 10.0)
        self.assertEqual(monthly.status, "RED")

    def test_scenario_6_0_percent_red(self):
        """Test 6: Base = 20, Current = 0 -> RED status (0% remaining)."""
        set_base_stock(self.product, Decimal("20.00"))
        use_stock(self.product, Decimal("20.00"))
        monthly = self.product.current_monthly_inventory
        self.assertEqual(monthly.current_stock, Decimal("0.00"))
        self.assertEqual(monthly.remaining_percentage, 0.0)
        self.assertEqual(monthly.status, "RED")

    def test_scenario_7_additional_stock_retains_base(self):
        """Test 7: Base = 20, Current = 2 -> Add 10 -> Base = 20, Current = 12 (Remaining = 60%)."""
        set_base_stock(self.product, Decimal("20.00"))
        use_stock(self.product, Decimal("18.00"))
        # Add 10 stock mid-month
        add_stock(self.product, Decimal("10.00"))
        monthly = self.product.current_monthly_inventory
        # Base Stock should remain 20.00, Current Stock becomes 12.00
        self.assertEqual(monthly.base_stock, Decimal("20.00"))
        self.assertEqual(monthly.current_stock, Decimal("12.00"))
        self.assertEqual(monthly.remaining_percentage, 60.0)
        self.assertEqual(monthly.status, "YELLOW")

    def test_scenario_8_new_month_reset(self):
        """Test 8: August Base = 20, September initial stock = 30 -> August Base = 20, September Base = 30."""
        # Setup August monthly base
        august_date = date(2026, 8, 15)
        set_base_stock(self.product, Decimal("20.00"), date_val=august_date)
        
        # Setup September monthly base
        september_date = date(2026, 9, 10)
        set_base_stock(self.product, Decimal("30.00"), date_val=september_date)
        
        # Check August
        aug_inv = MonthlyInventory.objects.get(product=self.product, month=date(2026, 8, 1))
        self.assertEqual(aug_inv.base_stock, Decimal("20.00"))
        
        # Check September
        sept_inv = MonthlyInventory.objects.get(product=self.product, month=date(2026, 9, 1))
        self.assertEqual(sept_inv.base_stock, Decimal("30.00"))


class StockHelpersTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Test Detergent",
            category="Laundry Supplies",
            unit="L",
            cost=Decimal("5.50"),
            supplier="Supplier A"
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            current_quantity=Decimal("10.00"),
            low_stock_threshold=Decimal("5.00")
        )

    def test_add_stock_success_does_not_establish_base(self):
        """add_stock increases current quantity, initializes base stock to 0.00, and logs stock history snapshots."""
        add_stock(self.product, Decimal("5.00"), notes="Added from cargo")
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.current_quantity, Decimal("15.00"))
        
        monthly = self.product.current_monthly_inventory
        self.assertIsNotNone(monthly)
        # Base Stock should default to 0.00
        self.assertEqual(monthly.base_stock, Decimal("0.00"))
        
        history = StockHistory.objects.filter(product=self.product).latest('created_at')
        self.assertEqual(history.change_type, "ADD")
        self.assertEqual(history.quantity, Decimal("5.00"))
        self.assertEqual(history.base_stock, Decimal("0.00"))
        self.assertIsNone(history.remaining_percentage)

    def test_use_stock_success(self):
        """use_stock decreases current quantity and records history snapshot."""
        # Establish base stock on yesterday to avoid same-day merge in the test
        from django.utils import timezone
        yesterday = timezone.localdate() - timezone.timedelta(days=1)
        set_base_stock(self.product, Decimal("10.00"), date_val=yesterday)
        use_stock(self.product, Decimal("4.00"), notes="Used in wash cycle")
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.current_quantity, Decimal("6.00"))
        
        history = StockHistory.objects.filter(product=self.product).latest('created_at')
        self.assertEqual(history.change_type, "USE")
        self.assertEqual(history.quantity, Decimal("4.00"))
        self.assertEqual(history.base_stock, Decimal("10.00"))
        self.assertEqual(history.remaining_percentage, Decimal("60.00"))


class StockAjaxEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.product = Product.objects.create(
            name="Test Detergent",
            category="Laundry Supplies",
            unit="L",
            cost=Decimal("5.50"),
            supplier="Supplier A"
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            current_quantity=Decimal("10.00"),
            low_stock_threshold=Decimal("5.00")
        )
        self.url = reverse('inventory:adjust_stock_ajax')

    def test_adjust_stock_ajax_add_does_not_establish_base(self):
        """AJAX adjust endpoint adds stock on 'add' but initializes base stock to 0.00."""
        payload = {
            'product_id': self.product.id,
            'quantity': '15',
            'action': 'add'
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(Decimal(data['new_quantity']), Decimal('25.00'))
        self.assertIsNone(data['remaining_percentage'])
        self.assertEqual(data['status'], 'No Base Stock')

    def test_adjust_stock_ajax_set_base_initial(self):
        """AJAX adjust endpoint sets monthly base stock and current stock on initial creation."""
        payload = {
            'product_id': self.product.id,
            'quantity': '50',
            'action': 'set_base'
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(Decimal(data['new_quantity']), Decimal('50.00'))  # syncs to 50 on initial creation!
        self.assertEqual(data['remaining_percentage'], 100.0)  # 50 / 50 = 100%
        self.assertEqual(data['status'], 'GREEN')
        self.assertEqual(Decimal(data['base_stock']), Decimal('50.00'))

    def test_adjust_stock_ajax_set_base_subsequent(self):
        """AJAX adjust endpoint updates monthly base stock without changing current stock if it already exists."""
        # Initial creation sets base and current to 50
        set_base_stock(self.product, Decimal("50.00"))
        
        # Subsequent update to 100 baseline
        payload = {
            'product_id': self.product.id,
            'quantity': '100',
            'action': 'set_base'
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(Decimal(data['new_quantity']), Decimal('50.00'))  # remains unchanged!
        self.assertEqual(data['remaining_percentage'], 50.0)  # 50 / 100 = 50%
        self.assertEqual(data['status'], 'YELLOW')
        self.assertEqual(Decimal(data['base_stock']), Decimal('100.00'))

    def test_adjust_stock_ajax_use_under_base(self):
        """AJAX adjust endpoint reduces stock and calculates percentage/status correctly."""
        # Establish base stock first
        set_base_stock(self.product, Decimal("10.00"))
        payload = {
            'product_id': self.product.id,
            'quantity': '8',
            'action': 'use'
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(Decimal(data['new_quantity']), Decimal('2.00'))
        # 2 / 10 = 20% remaining -> YELLOW status
        self.assertEqual(data['remaining_percentage'], 20.0)
        self.assertEqual(data['status'], 'YELLOW')

    def test_adjust_stock_ajax_edit_does_not_establish_base(self):
        """AJAX edit adjusts quantity but initializes base stock to 0.00."""
        payload = {
            'product_id': self.product.id,
            'quantity': '25',
            'action': 'edit',
            'notes': 'Manually editing to 25'
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(Decimal(data['new_quantity']), Decimal('25.00'))
        self.assertIsNone(data['remaining_percentage'])
        
        # Verify history
        history = StockHistory.objects.filter(product=self.product).latest('created_at')
        self.assertEqual(history.base_stock, Decimal('0.00'))
        self.assertIsNone(history.remaining_percentage)


class StockHistoryViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.product1 = Product.objects.create(
            name="Fabric Softener Lavender",
            category="Laundry Supplies",
            unit="bottles",
            cost=Decimal("2.50"),
            supplier="FloraCare Co"
        )
        self.inventory1 = Inventory.objects.create(
            product=self.product1,
            current_quantity=Decimal("10.00"),
            low_stock_threshold=Decimal("5.00")
        )
        self.product2 = Product.objects.create(
            name="Scent Booster Beads",
            category="Laundry Supplies",
            unit="pcs",
            cost=Decimal("1.50"),
            supplier="FloraCare Co"
        )
        self.inventory2 = Inventory.objects.create(
            product=self.product2,
            current_quantity=Decimal("5.00"),
            low_stock_threshold=Decimal("2.00")
        )

    def test_history_view_uses_stock_history_not_current_inventory(self):
        """The page is an audit trail and never synthesizes rows from Inventory."""
        from django.test.signals import template_rendered
        from unittest.mock import patch
        with patch.object(template_rendered, 'send') as mock_send:
            # Create multiple log records for Lavender
            add_stock(self.product1, Decimal("10.00"))
            use_stock(self.product1, Decimal("2.00"))
            
            response = self.client.get(reverse('inventory:history_laundry_supplies'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Fabric Softener Lavender")
            self.assertNotContains(response, "Scent Booster Beads")

            # Deleting the audit trail must make the page empty without
            # changing current inventory quantities.
            self.inventory1.refresh_from_db()
            stock_before_delete = self.inventory1.current_stock
            StockHistory.objects.all().delete()
            DailyInventory.objects.all().delete()
            response = self.client.get(reverse('inventory:history_laundry_supplies'))
            self.assertContains(response, "No history logs available for laundry supplies.")
            self.inventory1.refresh_from_db()
            self.assertEqual(self.inventory1.current_stock, stock_before_delete)

            response = self.client.get(reverse('inventory:history_laundry_accessories'))
            self.assertContains(response, "No history logs available for laundry accessories.")

    def test_detailed_product_history_view(self):
        """Detailed history view lists all logs for a specific product."""
        from django.test.signals import template_rendered
        from unittest.mock import patch
        with patch.object(template_rendered, 'send') as mock_send:
            add_stock(self.product1, Decimal("10.00"))
            use_stock(self.product1, Decimal("2.00"))
            
            url = reverse('inventory:product_history_detail', args=[self.product1.id])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Detailed transaction log and baseline audits")
            self.assertContains(response, "Fabric Softener Lavender")


class DashboardAlertViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.product1 = Product.objects.create(
            name="Fabric Softener Lavender",
            category="Laundry Supplies",
            unit="bottles",
            cost=Decimal("2.50"),
            supplier="FloraCare Co"
        )
        self.inventory1 = Inventory.objects.create(
            product=self.product1,
            current_quantity=Decimal("2.00"),
            low_stock_threshold=Decimal("5.00")
        )
        # Establish base stock of 20 -> 10% remaining (LOW)
        set_base_stock(self.product1, Decimal("20.00"))

        self.product2 = Product.objects.create(
            name="Ironing Board",
            category="Accessories",
            unit="pcs",
            cost=Decimal("15.00"),
            supplier="FloraCare Co"
        )
        self.inventory2 = Inventory.objects.create(
            product=self.product2,
            current_quantity=Decimal("10.00"),
            low_stock_threshold=Decimal("2.00")
        )
        # Missing monthly base stock -> should be excluded from alerts!

    def test_dashboard_alert_counts_excluding_missing_base(self):
        """Dashboard view low count counts Lavender (10%) but excludes Ironing Board (no base stock)."""
        from django.test.signals import template_rendered
        from unittest.mock import patch
        with patch.object(template_rendered, 'send') as mock_send:
            response = self.client.get(reverse('inventory:dashboard'))
            self.assertEqual(response.status_code, 200)
            
            # Check low stock count (1 product: Lavender)
            self.assertContains(response, "1")
            # Verify details modals context are rendered
            self.assertContains(response, "Fabric Softener Lavender")
            # Ironing board is excluded because base stock is not set
            self.assertNotContains(response, "Ironing Board")


class DailyInventoryHistoryLogicTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Ezzy",
            category="Laundry Supplies",
            unit="bottles",
            cost=Decimal("2.50"),
            supplier="Ezzycorp"
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            current_quantity=Decimal("0.00"),
            low_stock_threshold=Decimal("2.00")
        )

    def test_same_day_multiple_operations(self):
        """Additional stock changes on the same day update the same daily record."""
        # 10:00 - Set base stock to 10
        d = date(2026, 8, 22)
        set_base_stock(self.product, Decimal("10.00"), date_val=d)
        
        # Verify 2026-08-22 daily summary is created
        summaries = DailyInventory.objects.filter(product=self.product, date=d)
        self.assertEqual(summaries.count(), 1)
        summary = summaries.first()
        self.assertEqual(summary.base_stock, Decimal("10.00"))
        self.assertEqual(summary.closing_stock, Decimal("10.00"))
        
        # 12:00 - Use 2 units
        use_stock(self.product, Decimal("2.00"), date_val=d)
        summary.refresh_from_db()
        self.assertEqual(summary.closing_stock, Decimal("8.00"))
        self.assertEqual(summary.remaining_percentage, 80.0)
        
        # 15:00 - Use 1 unit
        use_stock(self.product, Decimal("1.00"), date_val=d)
        summary.refresh_from_db()
        self.assertEqual(summary.closing_stock, Decimal("7.00"))
        self.assertEqual(summary.remaining_percentage, 70.0)
        
        # Verify only 1 daily summary record exists for 2026-08-22
        self.assertEqual(DailyInventory.objects.filter(product=self.product, date=d).count(), 1)
        
        # Verify 3 stock history records exist for 2026-08-22 (not merged)
        history_count = StockHistory.objects.filter(product=self.product).count()
        self.assertEqual(history_count, 3)
        sh = StockHistory.objects.filter(product=self.product).order_by('-created_at', '-id').first()
        self.assertEqual(sh.new_quantity, Decimal("7.00"))
        self.assertEqual(sh.remaining_percentage, Decimal("70.00"))

    def test_multi_day_history_isolation(self):
        """A stock change on a new date creates a new daily record and does not modify yesterday's."""
        # Day 1 - 2026-08-21: Add 10 units (and set base first to establish 10.00 base)
        d1 = date(2026, 8, 21)
        set_base_stock(self.product, Decimal("10.00"), date_val=d1)
        
        # Verify Day 1 record
        summary1 = DailyInventory.objects.get(product=self.product, date=d1)
        self.assertEqual(summary1.closing_stock, Decimal("10.00"))
        self.assertEqual(summary1.base_stock, Decimal("10.00"))
        
        # Day 2 - 2026-08-22: Use 2 units
        d2 = date(2026, 8, 22)
        use_stock(self.product, Decimal("2.00"), date_val=d2)
        
        # Verify Day 2 record
        summary2 = DailyInventory.objects.get(product=self.product, date=d2)
        self.assertEqual(summary2.closing_stock, Decimal("8.00"))
        self.assertEqual(summary2.base_stock, Decimal("10.00"))
        
        # Verify Day 1 record is untouched!
        summary1.refresh_from_db()
        self.assertEqual(summary1.closing_stock, Decimal("10.00"))

    def test_date_filtering_in_detailed_history(self):
        """Detailed product history endpoint filters entries by date parameter."""
        d1 = date(2026, 8, 21)
        d2 = date(2026, 8, 22)
        set_base_stock(self.product, Decimal("10.00"), date_val=d1)
        use_stock(self.product, Decimal("2.00"), date_val=d2)
        
        url = reverse('inventory:product_history_detail', args=[self.product.id])
        
        # Request with date=2026-08-22
        response = self.client.get(f"{url}?date=2026-08-22")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "USE")
        self.assertNotContains(response, "Set base to 10")
        
        # Request with date=2026-08-21
        response = self.client.get(f"{url}?date=2026-08-21")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Set base to 10")
        self.assertNotContains(response, "USE")


class GoogleSheetsExportAndMonthFilterTests(TestCase):
    def setUp(self):
        self.branch, _ = Branch.objects.get_or_create(
            branch_code='OD3301LR-JGM',
            defaults={'branch_name': 'Jagamara', 'active': True},
        )
        self.branch.branch_name = 'Jagamara'
        self.branch.google_sheet_id = '1brVV0GHj-jI9A_ds_dFyiaQbGcqu2If6iboH6mok9tI'
        self.branch.active = True
        self.branch.save()
        self.user = User.objects.create_user(username='history-exporter', password='password123')
        EmployeeProfile.objects.create(user=self.user, branch=self.branch)
        self.client.login(username='history-exporter', password='password123')
        set_current_branch(self.branch)
        self.product = Product.objects.create(
            name="Ezzy",
            category="Laundry Supplies",
            unit="bottles",
            cost=Decimal("2.50"),
            supplier="Ezzycorp"
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            current_quantity=Decimal("0.00"),
            low_stock_threshold=Decimal("2.00")
        )
        # Create history on different months
        set_base_stock(self.product, Decimal("10.00"), date_val=date(2026, 8, 21))
        set_base_stock(self.product, Decimal("15.00"), date_val=date(2026, 7, 15))
        
    def test_month_filter_laundry_supplies(self):
        """Month filter selectively filters DailyInventory records displayed."""
        url = reverse('inventory:history_laundry_supplies')
        
        # Test default load returns both months
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "August 2026")
        self.assertContains(response, "July 2026")
        self.assertContains(response, "Ezzy")
        
        # Test filtering to August 2026 only
        response = self.client.get(f"{url}?months=2026-08")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2026-08-21")
        self.assertNotContains(response, "2026-07-15")
        
        # Test filtering to July 2026 only
        response = self.client.get(f"{url}?months=2026-07")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2026-07-15")
        self.assertNotContains(response, "2026-08-21")

    @patch('inventory.google_sheets.requests.post')
    @patch.dict('os.environ', {
        'GOOGLE_APPS_SCRIPT_URL': 'http://test-apps-script.local/',
        'GOOGLE_SHEETS_EXPORT_URL': 'http://test-apps-script.local/',
        'APPS_SCRIPT_SECRET': 'test_secret_abc',
    })
    def test_export_to_google_sheets_triggered(self, mock_post):
        """Export parameter in GET request invokes requests.post with formatted JSON payload."""
        url = reverse('inventory:history_laundry_supplies')
        
        # Mock successful post response
        from unittest.mock import MagicMock
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'success': True,
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1brVV0GHj-jI9A_ds_dFyiaQbGcqu2If6iboH6mok9tI/edit',
        }
        mock_post.return_value = mock_response
        
        # Request with export=google_sheets and filtered to August
        response = self.client.get(f"{url}?months=2026-08&export=google_sheets")
        self.assertEqual(response.status_code, 200)
        
        # Verify requests.post was called twice (supplies and accessories)
        self.assertEqual(mock_post.call_count, 2)
        call_args_list = mock_post.call_args_list
        
        # Verify first call (supplies)
        call_url_1, call_kwargs_1 = call_args_list[0]
        self.assertEqual(call_url_1[0], 'http://test-apps-script.local/')
        json_payload_1 = call_kwargs_1['json']
        self.assertEqual(json_payload_1['category'], 'supplies')
        self.assertEqual(json_payload_1['branch'], 'Jagamara')
        self.assertEqual(json_payload_1['branch_id'], 'OD3301LR-JGM')
        self.assertEqual(json_payload_1['spreadsheet_id'], '1brVV0GHj-jI9A_ds_dFyiaQbGcqu2If6iboH6mok9tI')
        # Only records matching the selected month filter (August 2026) should be exported
        self.assertEqual(len(json_payload_1['records']), 1)
        
        # Verify second call (accessories)
        call_url_2, call_kwargs_2 = call_args_list[1]
        self.assertEqual(call_url_2[0], 'http://test-apps-script.local/')
        json_payload_2 = call_kwargs_2['json']
        self.assertEqual(json_payload_2['category'], 'accessories')
        self.assertEqual(json_payload_2['branch_id'], 'OD3301LR-JGM')
        self.assertEqual(len(json_payload_2['records']), 0)

        # Secret token must be present in every payload sent to Apps Script
        self.assertEqual(json_payload_1['secret_token'], 'test_secret_abc')
        self.assertEqual(json_payload_2['secret_token'], 'test_secret_abc')
        
        # Verify success toast message
        self.assertContains(response, "Successfully exported August 2026 history to Jagamara Google Sheets.")

    def test_export_no_months_selected(self):
        """Exporting with no months selected returns a warning message."""
        url = reverse('inventory:history_laundry_supplies')
        # GET request with export=google_sheets but NO months parameters
        response = self.client.get(f"{url}?export=google_sheets")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select at least one month to export.")

    def test_export_no_records_found(self):
        """Exporting a month range with no data returns a warning message."""
        url = reverse('inventory:history_laundry_supplies')
        # GET request with export=google_sheets and months=2026-06 (no history in June)
        response = self.client.get(f"{url}?months=2026-06&export=google_sheets")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No history records found for the selected months.")

    @patch('inventory.google_sheets.requests.post')
    @patch.dict('os.environ', {
        'GOOGLE_APPS_SCRIPT_URL': 'http://test-apps-script.local/',
        'APPS_SCRIPT_SECRET': 'test_secret_abc',
    })
    def test_export_connection_failure(self, mock_post):
        """If requests.post raises an error, a user-friendly message is shown."""
        url = reverse('inventory:history_laundry_supplies')
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection Refused")
        
        response = self.client.get(f"{url}?months=2026-08&export=google_sheets")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unable to connect to Google Sheets: Connection/Timeout error (Connection Refused)")
        self.assertNotContains(response, "Traceback")
