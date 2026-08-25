from django.test import TestCase
from django.contrib.auth.models import User
from decimal import Decimal
from django.utils import timezone
from django.core import mail
from django.core.management import call_command
import unittest.mock as mock
import requests

from .models import Branch, Product, Inventory, StockHistory, DailyInventory, SheetSyncLog, EmployeeProfile
from .helpers import add_stock, use_stock, set_base_stock
from .middleware import set_current_branch, clear_current_branch

class MultiBranchTestCase(TestCase):
    def setUp(self):
        # Create Branches
        self.branch_jgm, _ = Branch.objects.get_or_create(branch_code='OD3301LR-JGM')
        self.branch_jgm.branch_name = 'Jagamara'
        self.branch_jgm.google_sheet_id = 'sheet-jgm-123'
        self.branch_jgm.active = True
        self.branch_jgm.save()
        
        self.branch_csp, _ = Branch.objects.get_or_create(branch_code='OD3302LR-CSP')
        self.branch_csp.branch_name = 'C. Spur'
        self.branch_csp.google_sheet_id = 'sheet-csp-456'
        self.branch_csp.active = True
        self.branch_csp.save()
        
        # Create Global Product
        self.product = Product.objects.create(
            name='Premium Detergent Pods',
            category='Laundry Supplies',
            unit='pcs',
            supplier='FreshCorp'
        )
        
        # Create Users
        self.employee_user = User.objects.create_user(
            username='employee01',
            password='password123'
        )
        self.employee_profile = EmployeeProfile.objects.create(
            user=self.employee_user,
            branch=self.branch_jgm
        )
        
        self.admin_user = User.objects.create_superuser(
            username='admin01',
            password='password123',
            email='admin@laundryrage.com'
        )

    def tearDown(self):
        clear_current_branch()

    def test_employee_default_branch_assignment(self):
        """Verify that employee logs in and gets default branch assigned from profile."""
        self.client.login(username='employee01', password='password123')
        
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        # Check active branch in context
        self.assertEqual(response.context['active_branch'], self.branch_jgm)

    def test_branch_isolation_on_stock_operations(self):
        """Verify stock changes in one branch do not affect another branch."""
        # Active branch JGM
        set_current_branch(self.branch_jgm)
        set_base_stock(self.product, Decimal('100.00'))
        
        # Verify JGM inventory
        inv_jgm = Inventory.objects.get(product=self.product, branch=self.branch_jgm)
        self.assertEqual(inv_jgm.current_stock, Decimal('100.00'))
        
        # Active branch CSP
        set_current_branch(self.branch_csp)
        set_base_stock(self.product, Decimal('50.00'))
        
        # Verify JGM inventory is still 100, CSP is 50
        inv_jgm.refresh_from_db()
        inv_csp = Inventory.objects.get(product=self.product, branch=self.branch_csp)
        
        self.assertEqual(inv_jgm.current_stock, Decimal('100.00'))
        self.assertEqual(inv_csp.current_stock, Decimal('50.00'))

    def test_employee_permission_restriction(self):
        """Verify that employees cannot modify or switch to other branches."""
        self.client.login(username='employee01', password='password123')
        
        # Employee attempts to switch branch via url
        response = self.client.get(f'/branch/switch/?branch_id={self.branch_csp.id}')
        # Should show access denied message and redirect
        self.assertEqual(response.status_code, 302)
        
        # Verify employee's resolved branch is still JGM
        response = self.client.get('/')
        self.assertEqual(response.context['active_branch'], self.branch_jgm)

    def test_alert_threshold_states(self):
        """Verify that thresholds produce correct NORMAL/YELLOW/RED/OUT_OF_STOCK states."""
        set_current_branch(self.branch_jgm)
        
        # Base stock 10
        inv = Inventory.objects.create(
            product=self.product,
            branch=self.branch_jgm,
            base_stock=Decimal('10.00'),
            current_stock=Decimal('10.00'),
            yellow_threshold=Decimal('8.00'),
            red_threshold=Decimal('2.00')
        )
        # Default save computes status
        self.assertEqual(inv.alert_status, 'NORMAL')
        
        # Under yellow threshold (current 5.0)
        inv.current_stock = Decimal('5.00')
        inv.save()
        self.assertEqual(inv.alert_status, 'YELLOW')
        
        # Under red threshold (current 1.0)
        inv.current_stock = Decimal('1.00')
        inv.save()
        self.assertEqual(inv.alert_status, 'RED')
        
        # Empty (current 0)
        inv.current_stock = Decimal('0.00')
        inv.save()
        self.assertEqual(inv.alert_status, 'OUT_OF_STOCK')

    def test_consolidated_daily_alert_email(self):
        """Verify consolidated daily email compilation and format."""
        # Yesterday records
        yesterday = timezone.now().date() - timezone.timedelta(days=1)
        
        # Set up JGM product stock alert
        set_current_branch(self.branch_jgm)
        inv_jgm = Inventory.objects.create(
            product=self.product,
            branch=self.branch_jgm,
            base_stock=Decimal('100.00'),
            current_stock=Decimal('5.00'),
            yellow_threshold=Decimal('40.00'),
            red_threshold=Decimal('10.00')
        )
        # Let's save a DailyInventory for yesterday with 120 (Normal) to verify "Newly RED" transition
        DailyInventory.objects.create(
            product=self.product,
            branch=self.branch_jgm,
            date=yesterday,
            base_stock=Decimal('100.00'),
            closing_stock=Decimal('120.00')
        )
        
        # Call daily command
        call_command('send_daily_alerts')
        
        # Verify one email is sent
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        
        # Verify content
        self.assertIn("Daily Consolidated Stock Alert", sent_email.subject)
        self.assertIn("Branch: Jagamara (OD3301LR-JGM)", sent_email.body)
        self.assertIn("Premium Detergent Pods", sent_email.body)
        self.assertIn("Newly RED", sent_email.body)
        self.assertIn("Required Refill: 95", sent_email.body)

    @mock.patch('requests.post')
    def test_google_sheets_sync_failure_handling(self, mock_post):
        """Verify that a sheets API error creates a failed sync log but does not fail database updates."""
        # Configure mock to raise HTTPError (simulate timeout/error)
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")
        
        set_current_branch(self.branch_jgm)
        
        # This will call set_base_stock which creates StockHistory and triggers Google Sheets sync
        # Since mock_post raises Timeout, set_base_stock should consume the error and finish successfully!
        with mock.patch.dict('os.environ', {'APPS_SCRIPT_SECRET': 'test_secret_123'}):
            try:
                set_base_stock(self.product, Decimal('100.00'))
            except Exception as e:
                self.fail(f"set_base_stock raised exception {e} when Google Sheets sync failed!")
            
        # Verify inventory was updated in DB
        inv = Inventory.objects.get(product=self.product, branch=self.branch_jgm)
        self.assertEqual(inv.base_stock, Decimal('100.00'))
        
        # Verify sync log was created with status FAILED
        sync_log = SheetSyncLog.objects.filter(branch=self.branch_jgm).first()
        self.assertIsNotNone(sync_log)
        self.assertEqual(sync_log.status, 'FAILED')
        self.assertIn("Connection timed out", sync_log.error_message)

    @mock.patch('requests.post')
    def test_send_daily_red_alert_command(self, mock_post):
        """Verify that send_daily_red_alert command sends correct action payload."""
        # Configure mock response
        mock_response = mock.Mock()
        mock_response.json.return_value = {'success': True}
        mock_post.return_value = mock_response
        
        with mock.patch.dict('os.environ', {
            'GOOGLE_APPS_SCRIPT_URL': 'http://test-apps-script.local/',
            'APPS_SCRIPT_SECRET': 'test_secret_123'
        }):
            call_command('send_daily_red_alert')
            
        # Verify post payload
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], 'http://test-apps-script.local/')
        self.assertEqual(kwargs['json']['action'], 'send_daily_red_alert')
        self.assertEqual(kwargs['json']['secret_token'], 'test_secret_123')

    @mock.patch('requests.post')
    def test_export_all_branches_blocked_for_admin(self, mock_post):
        """Verify that when 'selected_branch_id' is not in session (All Branches), export is blocked."""
        from django.contrib.auth.models import User
        from django.urls import reverse
        admin_user = User.objects.create_superuser('testadmin', 'admin@test.com', 'password123')
        self.client.force_login(admin_user)
        
        url = reverse('inventory:history_laundry_supplies')
        response = self.client.get(f"{url}?months=2026-08&export=google_sheets")
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select a specific branch on the dashboard before exporting history.")
        mock_post.assert_not_called()
