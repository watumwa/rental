from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    Building,
    CommunicationLog,
    Document,
    Expense,
    Inspection,
    InspectionItem,
    InventoryItem,
    Landlord,
    Lease,
    LeaseAmendment,
    LeaseNotice,
    MaintenanceRequest,
    OwnerStatement,
    Payment,
    PaymentRefund,
    PaymentReconciliation,
    Property,
    RentalApplication,
    RentCharge,
    SecurityDepositTransaction,
    Tenant,
    Unit,
    UtilityMeter,
    UtilityReading,
    Vendor,
)


class StyledModelForm(forms.ModelForm):
    """Apply a compact, consistent Bootstrap treatment to every operational form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            else:
                widget.attrs.setdefault("class", "form-select" if isinstance(widget, forms.Select) else "form-control")
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)
            if isinstance(widget, forms.DateInput):
                widget.attrs.setdefault("type", "date")


class PropertyForm(StyledModelForm):
    class Meta:
        model = Property
        fields = (
            "name",
            "code",
            "owner",
            "property_type",
            "status",
            "address",
            "district",
            "total_units",
            "description",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class LandlordForm(StyledModelForm):
    class Meta:
        model = Landlord
        fields = (
            "user",
            "full_name",
            "phone",
            "email",
            "national_id",
            "tax_id",
            "address",
            "occupation",
            "management_fee_rate",
            "payout_method",
            "payout_phone",
            "bank_name",
            "bank_account_name",
            "bank_account_number",
        )


class BuildingForm(StyledModelForm):
    class Meta:
        model = Building
        fields = ("property", "name", "floors", "notes")


class UnitForm(StyledModelForm):
    class Meta:
        model = Unit
        fields = (
            "property",
            "building",
            "unit_number",
            "floor",
            "unit_type",
            "bedrooms",
            "bathrooms",
            "rent_amount",
            "service_charge",
            "status",
            "notes",
        )


class TenantForm(StyledModelForm):
    class Meta:
        model = Tenant
        fields = (
            "full_name",
            "phone",
            "alternative_phone",
            "email",
            "nationality",
            "national_id",
            "emergency_contact",
            "emergency_phone",
            "status",
        )


class LeaseForm(StyledModelForm):
    class Meta:
        model = Lease
        fields = (
            "lease_number",
            "tenant",
            "unit",
            "start_date",
            "end_date",
            "rent_amount",
            "billing_frequency",
            "due_day",
            "security_deposit_required",
            "notice_period_days",
            "application",
            "renewal_of",
            "notes",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.exclude(status=Unit.Status.BLOCKED).select_related("property")
        self.fields["application"].queryset = RentalApplication.objects.filter(
            status=RentalApplication.Status.APPROVED,
            lease__isnull=True,
        ).select_related("unit")
        self.fields["application"].required = False
        self.fields["renewal_of"].required = False

    def clean(self):
        cleaned = super().clean()
        application = cleaned.get("application")
        if application:
            if cleaned.get("unit") != application.unit:
                self.add_error("unit", "The unit must match the approved application.")
            if cleaned.get("tenant") != application.tenant:
                self.add_error("tenant", "The tenant must match the approved application.")
        return cleaned


class LeaseRenewalForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    rent_amount = forms.DecimalField(
        min_value=0.01,
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, lease=None, **kwargs):
        self.lease = lease
        super().__init__(*args, **kwargs)
        if lease and not self.is_bound:
            self.fields["start_date"].initial = lease.end_date + timedelta(days=1)
            self.fields["rent_amount"].initial = lease.rent_amount

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start_date") and self.lease and cleaned["start_date"] <= self.lease.end_date:
            self.add_error("start_date", "The renewal must begin after the current lease ends.")
        if cleaned.get("start_date") and cleaned.get("end_date") and cleaned["end_date"] <= cleaned["start_date"]:
            self.add_error("end_date", "The end date must be after the start date.")
        return cleaned


class PaymentForm(StyledModelForm):
    class Meta:
        model = Payment
        fields = ("lease", "amount", "payment_date", "payment_method", "reference", "notes")
        widgets = {"payment_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lease"].required = True
        self.fields["lease"].queryset = Lease.objects.filter(
            status__in=(Lease.Status.ACTIVE, Lease.Status.EXPIRING)
        ).select_related("tenant", "unit__property")
        self.fields["payment_date"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("amount") is not None and cleaned["amount"] <= 0:
            self.add_error("amount", "Payment amount must be greater than zero.")
        if cleaned.get("payment_method") != Payment.Method.CASH and not cleaned.get("reference"):
            self.add_error("reference", "Enter the provider or bank transaction reference.")
        return cleaned


class VoidPaymentForm(forms.Form):
    reason = forms.CharField(
        min_length=5,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Reason for voiding"}),
    )


class PaymentRefundForm(StyledModelForm):
    class Meta:
        model = PaymentRefund
        fields = ("amount", "refund_date", "reference", "reason")
        widgets = {"refund_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, payment=None, **kwargs):
        self.payment = payment
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["refund_date"].initial = timezone.localdate()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("The refund amount must be greater than zero.")
        if self.payment and amount > self.payment.unallocated_amount:
            raise ValidationError("Only the payment's unallocated credit can be refunded.")
        return amount


class ManualChargeForm(StyledModelForm):
    class Meta:
        model = RentCharge
        fields = ("charge_type", "period", "due_date", "description", "amount", "source_reference")
        widgets = {
            "period": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["charge_type"].choices = (
            (RentCharge.ChargeType.LATE_FEE, "Late fee"),
            (RentCharge.ChargeType.DAMAGE, "Damage"),
            (RentCharge.ChargeType.DISCOUNT, "Discount/credit"),
            (RentCharge.ChargeType.OTHER, "Other"),
        )

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("Enter a positive amount. Discounts are converted to ledger credits automatically.")
        return amount


class MaintenanceRequestForm(StyledModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = (
            "unit",
            "tenant",
            "category",
            "title",
            "description",
            "priority",
            "status",
            "assigned_to",
            "assigned_user",
            "vendor",
            "scheduled_for",
            "estimated_cost",
            "quoted_cost",
            "actual_cost",
            "resolution",
            "tenant_verified",
        )
        widgets = {"scheduled_for": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class ExpenseForm(StyledModelForm):
    class Meta:
        model = Expense
        fields = (
            "property",
            "category",
            "supplier",
            "vendor",
            "description",
            "amount",
            "expense_date",
            "payment_method",
            "reference",
        )
        widgets = {"expense_date": forms.DateInput(attrs={"type": "date"})}

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("Expense amount must be greater than zero.")
        return amount


class RentalApplicationForm(StyledModelForm):
    class Meta:
        model = RentalApplication
        fields = (
            "unit",
            "applicant_name",
            "phone",
            "email",
            "national_id",
            "current_address",
            "employer",
            "monthly_income",
            "requested_move_in",
            "occupants",
            "guarantor_name",
            "guarantor_phone",
            "screening_notes",
        )
        widgets = {"requested_move_in": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.filter(
            status__in=(Unit.Status.AVAILABLE, Unit.Status.APPLICATION_PENDING)
        ).select_related("property")

    def clean_monthly_income(self):
        value = self.cleaned_data["monthly_income"]
        if value < 0:
            raise ValidationError("Monthly income cannot be negative.")
        return value


class ApplicationDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=(
            (RentalApplication.Status.SCREENING, "Start screening"),
            (RentalApplication.Status.APPROVED, "Approve"),
            (RentalApplication.Status.REJECTED, "Reject"),
            (RentalApplication.Status.WITHDRAWN, "Withdraw"),
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == RentalApplication.Status.REJECTED and not cleaned.get("reason"):
            self.add_error("reason", "Give a reason when rejecting an application.")
        return cleaned


class LeaseNoticeForm(StyledModelForm):
    class Meta:
        model = LeaseNotice
        fields = ("lease", "notice_type", "notice_date", "effective_date", "reason")
        widgets = {
            "notice_date": forms.DateInput(attrs={"type": "date"}),
            "effective_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lease"].queryset = Lease.objects.filter(
            status__in=(Lease.Status.ACTIVE, Lease.Status.EXPIRING)
        ).select_related("tenant", "unit")


class InspectionForm(StyledModelForm):
    class Meta:
        model = Inspection
        fields = (
            "unit",
            "lease",
            "inspection_type",
            "scheduled_for",
            "inspector",
            "status",
            "electricity_reading",
            "water_reading",
            "keys_issued",
            "tenant_acknowledged",
            "notes",
        )
        widgets = {"scheduled_for": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class InspectionItemForm(StyledModelForm):
    class Meta:
        model = InspectionItem
        fields = ("area", "item", "condition", "notes", "estimated_damage_cost")


class InventoryItemForm(StyledModelForm):
    class Meta:
        model = InventoryItem
        fields = ("unit", "name", "serial_number", "quantity", "condition", "replacement_value", "notes")


class SecurityDepositTransactionForm(StyledModelForm):
    class Meta:
        model = SecurityDepositTransaction
        fields = ("lease", "transaction_type", "amount", "transaction_date", "reference", "reason")
        widgets = {"transaction_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lease"].queryset = Lease.objects.exclude(
            status__in=(Lease.Status.DRAFT, Lease.Status.PENDING)
        ).select_related("tenant", "unit")

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("The transaction amount must be greater than zero.")
        return amount

    def clean(self):
        cleaned = super().clean()
        lease = cleaned.get("lease")
        amount = cleaned.get("amount")
        transaction_type = cleaned.get("transaction_type")
        if lease and amount and transaction_type in (
            SecurityDepositTransaction.TransactionType.DEDUCTION,
            SecurityDepositTransaction.TransactionType.REFUND,
        ) and amount > lease.deposit_held:
            self.add_error("amount", "The amount cannot exceed the deposit currently held.")
        return cleaned


class UtilityMeterForm(StyledModelForm):
    class Meta:
        model = UtilityMeter
        fields = ("unit", "utility_type", "meter_number", "unit_rate", "standing_charge", "is_active")


class UtilityReadingForm(StyledModelForm):
    class Meta:
        model = UtilityReading
        fields = ("meter", "reading_date", "reading", "notes")
        widgets = {"reading_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["meter"].queryset = UtilityMeter.objects.filter(is_active=True).select_related("unit__property")


class VendorForm(StyledModelForm):
    class Meta:
        model = Vendor
        fields = (
            "name",
            "category",
            "contact_person",
            "phone",
            "email",
            "tax_id",
            "address",
            "bank_details",
            "is_active",
        )


class LeaseAmendmentForm(StyledModelForm):
    class Meta:
        model = LeaseAmendment
        fields = ("lease", "amendment_type", "effective_date", "new_value", "reason")
        widgets = {
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "new_value": forms.Textarea(
                attrs={"rows": 3, "placeholder": '{"rent_amount": "900000"} or {"end_date": "2027-12-31"}'}
            ),
        }


class DocumentForm(StyledModelForm):
    class Meta:
        model = Document
        fields = ("title", "category", "object_type", "object_id", "file", "expires_on", "is_private")
        widgets = {"expires_on": forms.DateInput(attrs={"type": "date"})}


class CommunicationForm(StyledModelForm):
    class Meta:
        model = CommunicationLog
        fields = ("channel", "recipient_name", "recipient_address", "subject", "message")


class OwnerStatementForm(StyledModelForm):
    class Meta:
        model = OwnerStatement
        fields = ("owner", "property", "period_start", "period_end", "other_income", "notes")
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("period_start") and cleaned.get("period_end") and cleaned["period_end"] < cleaned["period_start"]:
            self.add_error("period_end", "The period end must be on or after the start.")
        if cleaned.get("property") and cleaned.get("owner") and cleaned["property"].owner_id != cleaned["owner"].pk:
            self.add_error("property", "The property does not belong to the selected owner.")
        return cleaned


class PaymentReconciliationForm(StyledModelForm):
    class Meta:
        model = PaymentReconciliation
        fields = ("provider", "external_reference", "transaction_date", "amount", "payer", "payment", "raw_data")
        widgets = {"transaction_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        cleaned = super().clean()
        payment = cleaned.get("payment")
        amount = cleaned.get("amount")
        if payment and amount != payment.amount:
            self.add_error("payment", "The imported amount does not match this payment.")
        return cleaned
