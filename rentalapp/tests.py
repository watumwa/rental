from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AuditLog,
    CommunicationLog,
    Expense,
    Inspection,
    Landlord,
    Lease,
    LeaseNotice,
    Payment,
    Property,
    Receipt,
    RentalApplication,
    RentCharge,
    SecurityDepositTransaction,
    Tenant,
    Unit,
    UserProfile,
    UtilityMeter,
)
from .services import (
    activate_lease,
    complete_inspection,
    complete_move_out,
    decide_application,
    generate_owner_statement,
    generate_rent_schedule,
    post_deposit_transaction,
    post_manual_charge,
    post_payment,
    record_utility_reading,
    refund_unallocated_payment,
    run_daily_operations,
    serve_lease_notice,
    synchronize_occupancy,
    void_payment,
)


class RentWorkflowTests(TestCase):
    def setUp(self):
        self.property = Property.objects.create(
            name="Kampala Heights",
            code="KH",
            address="Ntinda, Kampala",
            district="Kampala",
            total_units=2,
        )
        self.unit = Unit.objects.create(
            property=self.property,
            unit_number="A-204",
            rent_amount=Decimal("800000"),
        )
        self.tenant = Tenant.objects.create(full_name="John Musoke", phone="+256700000000")
        self.lease = Lease.objects.create(
            lease_number="LS-2026-001",
            tenant=self.tenant,
            unit=self.unit,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 10, 31),
            rent_amount=Decimal("800000"),
            due_day=1,
            security_deposit_required=Decimal("800000"),
            security_deposit_received=Decimal("800000"),
            status=Lease.Status.ACTIVE,
        )
        generate_rent_schedule(self.lease)
        synchronize_occupancy(self.unit)

    def payment_data(self, amount, reference="MTN-123"):
        return {
            "lease": self.lease,
            "amount": Decimal(amount),
            "payment_date": date(2026, 8, 3),
            "payment_method": Payment.Method.MTN_MOMO,
            "reference": reference,
            "notes": "",
        }

    def test_schedule_is_generated_for_every_month_and_is_idempotent(self):
        self.assertEqual(self.lease.rent_charges.count(), 3)
        self.assertEqual(generate_rent_schedule(self.lease), [])
        self.assertEqual(self.lease.rent_charges.count(), 3)

    def test_partial_payment_updates_only_the_first_charge(self):
        payment = post_payment(cleaned_data=self.payment_data("500000"))
        first = self.lease.rent_charges.order_by("period").first()
        self.assertEqual(payment.allocated_amount, Decimal("500000"))
        self.assertEqual(first.balance, Decimal("300000"))
        self.assertEqual(first.status, RentCharge.Status.PARTIAL)
        self.assertTrue(Receipt.objects.filter(payment=payment, number=payment.receipt_number).exists())

    def test_advance_payment_is_allocated_across_future_periods(self):
        payment = post_payment(cleaned_data=self.payment_data("2400000"))
        self.assertEqual(payment.allocations.count(), 3)
        self.assertEqual(payment.unallocated_amount, Decimal("0"))
        self.assertFalse(self.lease.rent_charges.exclude(status=RentCharge.Status.PAID).exists())

    def test_unallocated_amount_is_retained_as_tenant_credit(self):
        payment = post_payment(cleaned_data=self.payment_data("2500000"))
        self.assertEqual(payment.allocated_amount, Decimal("2400000"))
        self.assertEqual(payment.unallocated_amount, Decimal("100000"))

    def test_unallocated_credit_can_be_partially_refunded(self):
        payment = post_payment(cleaned_data=self.payment_data("2500000"))
        refund_unallocated_payment(
            payment=payment,
            cleaned_data={
                "amount": Decimal("60000"),
                "refund_date": date(2026, 8, 4),
                "reference": "RF-MTN-1",
                "reason": "Tenant requested excess payment return",
            },
        )
        self.assertEqual(payment.unallocated_amount, Decimal("40000"))

    def test_manual_discount_reduces_the_lease_ledger(self):
        before = self.lease.balance
        post_manual_charge(
            lease=self.lease,
            cleaned_data={
                "charge_type": RentCharge.ChargeType.DISCOUNT,
                "period": date(2026, 8, 1),
                "due_date": date(2026, 8, 1),
                "description": "Goodwill credit",
                "amount": Decimal("100000"),
                "source_reference": "CR-1",
            },
        )
        self.assertEqual(self.lease.balance, before - Decimal("100000"))

    def test_void_reverses_allocations_without_deleting_records(self):
        payment = post_payment(cleaned_data=self.payment_data("800000"))
        void_payment(payment=payment, reason="Duplicate Mobile Money callback")
        payment.refresh_from_db()
        first = self.lease.rent_charges.order_by("period").first()
        first.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.VOID)
        self.assertEqual(first.status, RentCharge.Status.UNPAID)
        self.assertTrue(payment.allocations.exists())
        self.assertTrue(AuditLog.objects.filter(action="payment_voided", object_id=str(payment.pk)).exists())

    def test_financial_records_cannot_be_deleted(self):
        payment = post_payment(cleaned_data=self.payment_data("800000"))
        with self.assertRaises(ValidationError):
            payment.delete()
        with self.assertRaises(ValidationError):
            Payment.objects.filter(pk=payment.pk).delete()
        with self.assertRaises(ValidationError):
            payment.receipt.delete()

    def test_active_lease_marks_unit_occupied(self):
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)


class PageSmokeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="manager", password="safe-test-password")
        self.user.rental_profile.role = UserProfile.Role.MANAGER
        self.user.rental_profile.save(update_fields=("role", "updated_at"))
        self.property = Property.objects.create(
            name="Kampala Heights", code="KH", address="Ntinda, Kampala", district="Kampala", total_units=2
        )
        self.unit = Unit.objects.create(
            property=self.property, unit_number="A-204", rent_amount=Decimal("800000")
        )
        self.tenant = Tenant.objects.create(full_name="John Musoke", phone="+256700000000")
        self.lease = Lease.objects.create(
            lease_number="LS-2026-001",
            tenant=self.tenant,
            unit=self.unit,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 10, 31),
            rent_amount=Decimal("800000"),
            due_day=1,
            status=Lease.Status.ACTIVE,
        )
        generate_rent_schedule(self.lease)
        self.payment = post_payment(
            cleaned_data={
                "lease": self.lease,
                "amount": Decimal("500000"),
                "payment_date": date(2026, 8, 3),
                "payment_method": Payment.Method.MTN_MOMO,
                "reference": "MTN-123",
                "notes": "",
            }
        )

    def test_core_pages_render(self):
        self.client.force_login(self.user)
        urls = (
            reverse("dashboard"),
            reverse("property_list"),
            reverse("property_detail", args=[self.property.pk]),
            reverse("unit_list"),
            reverse("unit_detail", args=[self.unit.pk]),
            reverse("tenant_list"),
            reverse("tenant_detail", args=[self.tenant.pk]),
            reverse("lease_list"),
            reverse("lease_detail", args=[self.lease.pk]),
            reverse("payment_list"),
            reverse("payment_create"),
            reverse("receipt_detail", args=[self.payment.pk]),
            reverse("arrears"),
            reverse("maintenance_list"),
            reverse("expense_list"),
            reverse("reports"),
            reverse("audit_logs"),
            reverse("global_search") + "?q=John",
            reverse("portfolio_setup"),
            reverse("application_list"),
            reverse("notice_list"),
            reverse("amendment_list"),
            reverse("inspection_list"),
            reverse("deposit_list"),
            reverse("utility_list"),
            reverse("document_list"),
            reverse("communication_list"),
            reverse("owner_statement_list"),
            reverse("reconciliation_list"),
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_payment_post_endpoint_generates_receipt(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("payment_create"),
            {
                "lease": self.lease.pk,
                "amount": "300000",
                "payment_date": "2026-08-08",
                "payment_method": Payment.Method.AIRTEL_MONEY,
                "reference": "AIRTEL-456",
                "notes": "Balance payment",
            },
        )
        created = Payment.objects.get(reference="AIRTEL-456")
        self.assertRedirects(response, reverse("receipt_detail", args=[created.pk]))
        self.assertTrue(created.receipt_number.startswith("RC-2026-"))


class AccessControlTests(TestCase):
    def setUp(self):
        self.viewer = get_user_model().objects.create_user(username="viewer", password="test-password")

    def test_anonymous_users_are_sent_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_login_does_not_query_notifications_for_anonymous_users(self):
        with patch("rentalapp.context_processors.Notification.objects.filter") as notification_filter:
            response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        notification_filter.assert_not_called()

    def test_unassigned_viewer_cannot_open_staff_workspace(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)


class CompleteRentalLifecycleTests(TestCase):
    def setUp(self):
        self.manager = get_user_model().objects.create_user(username="lifecycle-manager", password="test-password")
        self.manager.rental_profile.role = UserProfile.Role.MANAGER
        self.manager.rental_profile.save(update_fields=("role", "updated_at"))
        self.owner = Landlord.objects.create(
            full_name="Amina Nansubuga",
            phone="+256700000001",
            management_fee_rate=Decimal("8"),
        )
        self.property = Property.objects.create(
            owner=self.owner,
            name="Lake View Apartments",
            code="LVA",
            address="Luzira, Kampala",
        )
        self.unit = Unit.objects.create(
            property=self.property,
            unit_number="B-02",
            rent_amount=Decimal("1000000"),
            service_charge=Decimal("100000"),
        )

    def test_application_approval_creates_tenant_and_reserves_unit(self):
        application = RentalApplication.objects.create(
            unit=self.unit,
            applicant_name="Sarah Atim",
            phone="+256701111111",
            requested_move_in=date(2026, 9, 1),
            monthly_income=Decimal("3500000"),
        )
        decide_application(
            application=application,
            decision=RentalApplication.Status.APPROVED,
            actor=self.manager,
            reason="Income and references verified",
        )
        application.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(application.tenant.status, Tenant.Status.PROSPECTIVE)
        self.assertEqual(self.unit.status, Unit.Status.RESERVED)

    def _pending_lease(self, deposit=Decimal("0")):
        tenant = Tenant.objects.create(
            full_name="Sarah Atim",
            phone="+256701111111",
            status=Tenant.Status.PROSPECTIVE,
        )
        return Lease.objects.create(
            lease_number="LS-LIFECYCLE-001",
            tenant=tenant,
            unit=self.unit,
            start_date=date(2026, 9, 1),
            end_date=date(2027, 8, 31),
            rent_amount=Decimal("1000000"),
            security_deposit_required=deposit,
            status=Lease.Status.PENDING,
        )

    def _completed_inspection(self, lease, inspection_type):
        inspection = Inspection.objects.create(
            unit=self.unit,
            lease=lease,
            inspection_type=inspection_type,
            scheduled_for=timezone.make_aware(datetime(2026, 8, 30, 9, 0)),
        )
        complete_inspection(inspection=inspection, actor=self.manager, acknowledged=True)
        return inspection

    def test_move_in_activation_generates_rent_and_service_charges(self):
        lease = self._pending_lease()
        self._completed_inspection(lease, Inspection.InspectionType.MOVE_IN)
        activate_lease(lease=lease, actor=self.manager)
        lease.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(lease.status, Lease.Status.ACTIVE)
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)
        self.assertTrue(lease.rent_charges.filter(charge_type=RentCharge.ChargeType.RENT).exists())
        self.assertTrue(lease.rent_charges.filter(charge_type=RentCharge.ChargeType.SERVICE_CHARGE).exists())

    def test_notice_deposit_settlement_and_move_out_close_tenancy(self):
        lease = self._pending_lease(deposit=Decimal("1000000"))
        self._completed_inspection(lease, Inspection.InspectionType.MOVE_IN)
        activate_lease(lease=lease, actor=self.manager)
        post_deposit_transaction(
            cleaned_data={
                "lease": lease,
                "transaction_type": SecurityDepositTransaction.TransactionType.RECEIPT,
                "amount": Decimal("1000000"),
                "transaction_date": date(2026, 9, 1),
                "reference": "DEP-001",
                "reason": "",
            },
            actor=self.manager,
        )
        notice = LeaseNotice.objects.create(
            lease=lease,
            notice_type=LeaseNotice.NoticeType.TENANT_TERMINATION,
            notice_date=date(2027, 7, 1),
            effective_date=date(2027, 8, 31),
            reason="Relocating",
        )
        serve_lease_notice(notice=notice, actor=self.manager)
        self._completed_inspection(lease, Inspection.InspectionType.MOVE_OUT)
        post_deposit_transaction(
            cleaned_data={
                "lease": lease,
                "transaction_type": SecurityDepositTransaction.TransactionType.REFUND,
                "amount": Decimal("1000000"),
                "transaction_date": date(2027, 8, 31),
                "reference": "REF-001",
                "reason": "Full refund",
            },
            actor=self.manager,
        )
        complete_move_out(lease=lease, actor=self.manager, reason="Handover completed")
        lease.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(lease.status, Lease.Status.TERMINATED)
        self.assertEqual(self.unit.status, Unit.Status.AVAILABLE)
        self.assertEqual(lease.deposit_held, Decimal("0"))

    def test_utility_reading_creates_tenant_charge(self):
        lease = self._pending_lease()
        self._completed_inspection(lease, Inspection.InspectionType.MOVE_IN)
        activate_lease(lease=lease, actor=self.manager)
        meter = UtilityMeter.objects.create(
            unit=self.unit,
            utility_type=UtilityMeter.UtilityType.WATER,
            meter_number="W-100",
            unit_rate=Decimal("2500"),
            standing_charge=Decimal("5000"),
        )
        reading = record_utility_reading(
            cleaned_data={
                "meter": meter,
                "reading_date": date(2026, 9, 20),
                "reading": Decimal("12"),
                "notes": "Verified",
            },
            actor=self.manager,
        )
        self.assertEqual(reading.consumption, Decimal("12"))
        self.assertEqual(reading.amount, Decimal("35000.00"))
        self.assertEqual(reading.charge.charge_type, RentCharge.ChargeType.WATER)

    def test_owner_statement_calculates_net_payout(self):
        lease = self._pending_lease()
        self._completed_inspection(lease, Inspection.InspectionType.MOVE_IN)
        activate_lease(lease=lease, actor=self.manager)
        post_payment(
            cleaned_data={
                "lease": lease,
                "amount": Decimal("1100000"),
                "payment_date": date(2026, 9, 3),
                "payment_method": Payment.Method.BANK,
                "reference": "BANK-OWNER-1",
                "notes": "",
            },
            actor=self.manager,
        )
        Expense.objects.create(
            property=self.property,
            category="repairs",
            description="Door repair",
            amount=Decimal("100000"),
            expense_date=date(2026, 9, 10),
        )
        statement = generate_owner_statement(
            cleaned_data={
                "owner": self.owner,
                "property": self.property,
                "period_start": date(2026, 9, 1),
                "period_end": date(2026, 9, 30),
                "other_income": Decimal("0"),
                "notes": "",
            },
            actor=self.manager,
        )
        self.assertEqual(statement.management_fee, Decimal("88000.00"))
        self.assertEqual(statement.net_payable, Decimal("912000.00"))


class DailyOperationsTests(TestCase):
    def test_daily_run_expires_leases_and_queues_idempotent_reminders(self):
        property_item = Property.objects.create(name="Daily Ops", address="Kampala")
        unit = Unit.objects.create(property=property_item, unit_number="1", rent_amount=Decimal("500000"))
        tenant = Tenant.objects.create(full_name="Reminder Tenant", phone="+256700123123")
        lease = Lease.objects.create(
            lease_number="LS-DAILY-1",
            tenant=tenant,
            unit=unit,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 7, 31),
            rent_amount=Decimal("500000"),
            status=Lease.Status.ACTIVE,
        )
        RentCharge.objects.create(
            lease=lease,
            period=date(2026, 7, 1),
            due_date=date(2026, 7, 1),
            amount=Decimal("500000"),
        )
        result = run_daily_operations(today=date(2026, 8, 13))
        run_daily_operations(today=date(2026, 8, 13))
        lease.refresh_from_db()
        self.assertEqual(result["expired"], 1)
        self.assertEqual(lease.status, Lease.Status.EXPIRED)
        self.assertEqual(CommunicationLog.objects.count(), 1)
