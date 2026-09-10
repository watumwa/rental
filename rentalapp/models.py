import builtins
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserProfile(TimeStampedModel):
    class Role(models.TextChoices):
        VIEWER = "viewer", "Viewer"
        ADMINISTRATOR = "administrator", "Administrator"
        MANAGER = "manager", "Property manager"
        ACCOUNTANT = "accountant", "Accountant"
        MAINTENANCE = "maintenance", "Maintenance officer"
        LANDLORD = "landlord", "Landlord"
        TENANT = "tenant", "Tenant"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rental_profile",
    )
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.VIEWER)
    phone = models.CharField(max_length=20, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("user__first_name", "user__username")

    def __str__(self):
        return f"{self.user} · {self.get_role_display()}"


class Landlord(TimeStampedModel):
    class PayoutMethod(models.TextChoices):
        BANK = "bank", "Bank transfer"
        MTN_MOMO = "mtn_momo", "MTN Mobile Money"
        AIRTEL_MONEY = "airtel_money", "Airtel Money"
        CASH = "cash", "Cash"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="landlord_profile",
    )
    full_name = models.CharField(max_length=140, blank=True)
    phone = models.CharField(max_length=20)
    national_id = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=40, blank=True)
    management_fee_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    payout_method = models.CharField(
        max_length=20,
        choices=PayoutMethod.choices,
        default=PayoutMethod.BANK,
    )
    payout_phone = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_name = models.CharField(max_length=140, blank=True)
    bank_account_number = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ("full_name", "id")

    def __str__(self):
        return self.full_name or (self.user.get_full_name() if self.user else "Unnamed owner")


class Property(TimeStampedModel):
    TYPE_CHOICES = (
        ("apartments", "Apartments"),
        ("commercial", "Commercial"),
        ("mixed_use", "Mixed use"),
        ("villas", "Villas"),
        ("other", "Other"),
    )
    STATUS_CHOICES = (("active", "Active"), ("inactive", "Inactive"))

    owner = models.ForeignKey(
        Landlord,
        on_delete=models.PROTECT,
        related_name="properties",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    address = models.TextField()
    district = models.CharField(max_length=80, blank=True)
    property_type = models.CharField(max_length=50, choices=TYPE_CHOICES, default="apartments")
    description = models.TextField(blank=True)
    total_units = models.PositiveIntegerField(default=0, help_text="Planned or declared unit count")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("property_detail", args=[self.pk])

    @property
    def unit_count(self):
        return self.units.count()

    @property
    def occupied_count(self):
        return self.units.filter(status=Unit.Status.OCCUPIED).count()

    @property
    def vacant_count(self):
        return self.units.filter(status=Unit.Status.AVAILABLE).count()

    @property
    def expected_monthly_rent(self):
        return self.units.aggregate(total=Sum("rent_amount"))["total"] or Decimal("0")


class Building(TimeStampedModel):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="buildings")
    name = models.CharField(max_length=100)
    floors = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("property__name", "name")
        constraints = [
            models.UniqueConstraint(fields=("property", "name"), name="unique_building_per_property")
        ]

    def __str__(self):
        return f"{self.property} · {self.name}"


class Unit(TimeStampedModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        APPLICATION_PENDING = "application_pending", "Application pending"
        OCCUPIED = "occupied", "Occupied"
        NOTICE_GIVEN = "notice_given", "Notice given"
        MAINTENANCE = "maintenance", "Under maintenance"
        BLOCKED = "blocked", "Blocked"

    TYPE_CHOICES = (
        ("studio", "Studio"),
        ("apartment", "Apartment"),
        ("house", "House"),
        ("shop", "Shop"),
        ("office", "Office"),
        ("other", "Other"),
    )

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="units")
    building = models.ForeignKey(
        Building,
        on_delete=models.SET_NULL,
        related_name="units",
        null=True,
        blank=True,
    )
    unit_number = models.CharField(max_length=20)
    floor = models.CharField(max_length=30, blank=True)
    unit_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default="apartment")
    bedrooms = models.PositiveSmallIntegerField(default=1)
    bathrooms = models.PositiveSmallIntegerField(default=1)
    rent_amount = models.DecimalField(max_digits=14, decimal_places=2)
    service_charge = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.AVAILABLE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("property__name", "unit_number")
        constraints = [
            models.UniqueConstraint(fields=("property", "unit_number"), name="unique_unit_per_property")
        ]

    def __str__(self):
        return f"{self.property} · {self.unit_number}"

    def get_absolute_url(self):
        return reverse("unit_detail", args=[self.pk])

    @builtins.property
    def current_lease(self):
        return self.leases.filter(status=Lease.Status.ACTIVE).select_related("tenant").first()


class Tenant(TimeStampedModel):
    class Status(models.TextChoices):
        PROSPECTIVE = "prospective", "Prospective"
        ACTIVE = "active", "Active"
        NOTICE_GIVEN = "notice_given", "Notice given"
        FORMER = "former", "Former"
        BLOCKED = "blocked", "Blocked"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tenant_profile",
    )
    full_name = models.CharField(max_length=140, blank=True)
    phone = models.CharField(max_length=20)
    alternative_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    nationality = models.CharField(max_length=80, default="Ugandan", blank=True)
    national_id = models.CharField(max_length=30, blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ("full_name", "id")

    def __str__(self):
        return self.full_name or (self.user.get_full_name() if self.user else self.phone)

    def get_absolute_url(self):
        return reverse("tenant_detail", args=[self.pk])

    @property
    def active_lease(self):
        return self.leases.filter(status=Lease.Status.ACTIVE).select_related("unit__property").first()


class Lease(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending approval"
        ACTIVE = "active", "Active"
        EXPIRING = "expiring", "Expiring soon"
        EXPIRED = "expired", "Expired"
        TERMINATED = "terminated", "Terminated"
        RENEWED = "renewed", "Renewed"

    FREQUENCY_CHOICES = (("monthly", "Monthly"), ("quarterly", "Quarterly"), ("annual", "Annual"))

    lease_number = models.CharField(max_length=30, unique=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="leases")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="leases")
    start_date = models.DateField()
    end_date = models.DateField()
    rent_amount = models.DecimalField(max_digits=14, decimal_places=2)
    billing_frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default="monthly")
    due_day = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(28)]
    )
    security_deposit_required = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    security_deposit_received = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notice_period_days = models.PositiveSmallIntegerField(default=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    application = models.OneToOneField(
        "RentalApplication",
        on_delete=models.PROTECT,
        related_name="lease",
        null=True,
        blank=True,
    )
    renewal_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="renewals",
        null=True,
        blank=True,
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)
    termination_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-start_date", "lease_number")
        constraints = [
            models.UniqueConstraint(
                fields=("unit",),
                condition=models.Q(status__in=("active", "expiring")),
                name="one_current_lease_per_unit",
            )
        ]

    def __str__(self):
        return f"{self.lease_number} · {self.tenant}"

    def clean(self):
        if self.end_date and self.start_date and self.end_date <= self.start_date:
            raise ValidationError({"end_date": "The lease end date must be after the start date."})
        if self.security_deposit_received > self.security_deposit_required:
            raise ValidationError(
                {"security_deposit_received": "Received deposit cannot exceed the required deposit."}
            )
        if self.status == self.Status.ACTIVE and self.unit_id:
            conflicts = Lease.objects.filter(unit_id=self.unit_id, status=self.Status.ACTIVE)
            if self.pk:
                conflicts = conflicts.exclude(pk=self.pk)
            if conflicts.exists():
                raise ValidationError({"unit": "This unit already has an active lease."})

    @property
    def balance(self):
        charges = self.rent_charges.exclude(status=RentCharge.Status.VOID).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        payments = self.payments.filter(status=Payment.Status.POSTED).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        refunds = PaymentRefund.objects.filter(
            payment__lease=self,
            status=PaymentRefund.Status.POSTED,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return max(charges - payments + refunds, Decimal("0"))

    @property
    def deposit_held(self):
        if hasattr(self, "deposit_transactions"):
            received = self.deposit_transactions.filter(
                status=SecurityDepositTransaction.Status.POSTED,
                transaction_type__in=(
                    SecurityDepositTransaction.TransactionType.RECEIPT,
                    SecurityDepositTransaction.TransactionType.ADJUSTMENT_IN,
                ),
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            outgoing = self.deposit_transactions.filter(
                status=SecurityDepositTransaction.Status.POSTED,
                transaction_type__in=(
                    SecurityDepositTransaction.TransactionType.DEDUCTION,
                    SecurityDepositTransaction.TransactionType.REFUND,
                ),
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            if received or outgoing:
                return received - outgoing
        return self.security_deposit_received

    @property
    def deposit_balance(self):
        return max(self.security_deposit_required - self.deposit_held, Decimal("0"))


class ProtectedFinancialQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Financial records cannot be deleted. Void or reverse the transaction instead.")


class RentCharge(TimeStampedModel):
    class ChargeType(models.TextChoices):
        RENT = "rent", "Rent"
        SERVICE_CHARGE = "service_charge", "Service charge"
        WATER = "water", "Water"
        ELECTRICITY = "electricity", "Electricity"
        LATE_FEE = "late_fee", "Late fee"
        DAMAGE = "damage", "Damage"
        DISCOUNT = "discount", "Discount/credit"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Partially paid"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="rent_charges")
    period = models.DateField(help_text="First day of the billing period")
    due_date = models.DateField()
    description = models.CharField(max_length=140, default="Monthly rent")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    charge_type = models.CharField(max_length=30, choices=ChargeType.choices, default=ChargeType.RENT)
    source_reference = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)

    objects = ProtectedFinancialQuerySet.as_manager()

    class Meta:
        ordering = ("due_date", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("lease", "period", "charge_type"),
                condition=models.Q(
                    charge_type__in=("rent", "service_charge", "water", "electricity")
                ),
                name="unique_recurring_charge_period",
            )
        ]

    def __str__(self):
        return f"{self.lease.lease_number} · {self.period:%b %Y}"

    def delete(self, *args, **kwargs):
        raise ValidationError("Rent charges cannot be deleted. Void the charge instead.")

    @property
    def allocated_amount(self):
        return self.allocations.filter(payment__status=Payment.Status.POSTED).aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0")

    @property
    def balance(self):
        return max(self.amount - self.allocated_amount, Decimal("0"))

    def refresh_status(self):
        if self.status == self.Status.VOID:
            return
        paid = self.allocated_amount
        new_status = self.Status.PAID if paid >= self.amount else self.Status.PARTIAL if paid else self.Status.UNPAID
        if new_status != self.status:
            RentCharge.objects.filter(pk=self.pk).update(status=new_status, updated_at=timezone.now())
            self.status = new_status


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MTN_MOMO = "mtn_momo", "MTN Mobile Money"
        AIRTEL_MONEY = "airtel_money", "Airtel Money"
        BANK = "bank", "Bank transfer/deposit"
        CHEQUE = "cheque", "Cheque"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        VOID = "void", "Void"

    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="payments", null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField(default=timezone.localdate)
    payment_method = models.CharField(max_length=30, choices=Method.choices, default=Method.MTN_MOMO)
    reference = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POSTED)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_rent_payments",
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)
    void_reason = models.TextField(blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="voided_rent_payments",
        null=True,
        blank=True,
    )

    objects = ProtectedFinancialQuerySet.as_manager()

    class Meta:
        ordering = ("-payment_date", "-id")

    def __str__(self):
        return self.receipt_number or self.reference or f"Payment {self.pk}"

    def delete(self, *args, **kwargs):
        raise ValidationError("Payments cannot be deleted. Void the payment with a reason instead.")

    @property
    def allocated_amount(self):
        return self.allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    @property
    def unallocated_amount(self):
        refunded = self.refunds.filter(status=PaymentRefund.Status.POSTED).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        return max(self.amount - self.allocated_amount - refunded, Decimal("0"))


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    charge = models.ForeignKey(RentCharge, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProtectedFinancialQuerySet.as_manager()

    class Meta:
        ordering = ("charge__due_date", "id")
        constraints = [
            models.UniqueConstraint(fields=("payment", "charge"), name="unique_payment_charge_allocation")
        ]

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({"amount": "Allocation amount must be greater than zero."})
        if self.payment_id and self.charge_id and self.payment.lease_id != self.charge.lease_id:
            raise ValidationError("The payment and charge must belong to the same lease.")

    def __str__(self):
        return f"{self.payment} → {self.charge}"

    def delete(self, *args, **kwargs):
        raise ValidationError("Payment allocations are permanent financial records.")


class Receipt(models.Model):
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    number = models.CharField(max_length=30, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    objects = ProtectedFinancialQuerySet.as_manager()

    class Meta:
        ordering = ("-issued_at",)

    def __str__(self):
        return self.number

    def delete(self, *args, **kwargs):
        raise ValidationError("Receipts are permanent records and cannot be deleted.")


class PaymentRefund(TimeStampedModel):
    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        VOID = "void", "Void"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    refund_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    refund_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=100)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POSTED)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="posted_payment_refunds",
        null=True,
        blank=True,
    )

    objects = ProtectedFinancialQuerySet.as_manager()

    class Meta:
        ordering = ("-refund_date", "-id")
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="positive_payment_refund")]

    def delete(self, *args, **kwargs):
        raise ValidationError("Payment refunds cannot be deleted. Void the refund instead.")

    def __str__(self):
        return self.refund_number or f"Refund · {self.payment}"


class MaintenanceRequest(TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWED = "reviewed", "Reviewed"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        AWAITING_PARTS = "awaiting_parts", "Awaiting parts"
        COMPLETED = "completed", "Completed"
        VERIFIED = "verified", "Verified"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="maintenance_requests", null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="maintenance_requests")
    request_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    category = models.CharField(max_length=50, default="general")
    title = models.CharField(max_length=100)
    description = models.TextField()
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NEW)
    assigned_to = models.CharField(max_length=140, blank=True)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_maintenance_requests",
        null=True,
        blank=True,
    )
    vendor = models.ForeignKey(
        "Vendor",
        on_delete=models.PROTECT,
        related_name="maintenance_requests",
        null=True,
        blank=True,
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    quoted_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    actual_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_maintenance_requests",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True)
    tenant_verified = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.request_number or self.title


class Expense(TimeStampedModel):
    CATEGORY_CHOICES = (
        ("repairs", "Repairs"),
        ("plumbing", "Plumbing"),
        ("electrical", "Electrical"),
        ("cleaning", "Cleaning"),
        ("security", "Security"),
        ("utilities", "Utilities"),
        ("staff", "Staff"),
        ("taxes", "Taxes"),
        ("other", "Other"),
    )
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="expenses")
    expense_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    supplier = models.CharField(max_length=140, blank=True)
    vendor = models.ForeignKey(
        "Vendor",
        on_delete=models.PROTECT,
        related_name="expenses",
        null=True,
        blank=True,
    )
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    expense_date = models.DateField(default=timezone.localdate)
    payment_method = models.CharField(max_length=30, choices=Payment.Method.choices, default=Payment.Method.CASH)
    reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20, choices=(("posted", "Posted"), ("void", "Void")), default="posted"
    )
    void_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_property_expenses",
    )

    objects = ProtectedFinancialQuerySet.as_manager()

    class Meta:
        ordering = ("-expense_date", "-id")

    def __str__(self):
        return self.expense_number or self.description

    def delete(self, *args, **kwargs):
        raise ValidationError("Expenses cannot be deleted. Void the expense instead.")


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=50)
    object_label = models.CharField(max_length=255)
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.action} · {self.object_label}"


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField()
    link = models.CharField(max_length=255, blank=True)
    level = models.CharField(
        max_length=20,
        choices=(("info", "Info"), ("warning", "Warning"), ("danger", "Danger"), ("success", "Success")),
        default="info",
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.message[:50]


class Vendor(TimeStampedModel):
    class Category(models.TextChoices):
        MAINTENANCE = "maintenance", "Maintenance"
        PLUMBING = "plumbing", "Plumbing"
        ELECTRICAL = "electrical", "Electrical"
        CLEANING = "cleaning", "Cleaning"
        SECURITY = "security", "Security"
        LEGAL = "legal", "Legal"
        OTHER = "other", "Other"

    name = models.CharField(max_length=140)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.MAINTENANCE)
    contact_person = models.CharField(max_length=140, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    tax_id = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True)
    bank_details = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class RentalApplication(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        SCREENING = "screening", "Screening"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"
        CONVERTED = "converted", "Converted to lease"

    application_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="applications")
    applicant_name = models.CharField(max_length=140)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    national_id = models.CharField(max_length=30, blank=True)
    current_address = models.CharField(max_length=255, blank=True)
    employer = models.CharField(max_length=140, blank=True)
    monthly_income = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    requested_move_in = models.DateField()
    occupants = models.PositiveSmallIntegerField(default=1)
    guarantor_name = models.CharField(max_length=140, blank=True)
    guarantor_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    screening_notes = models.TextField(blank=True)
    decision_reason = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="decided_rental_applications",
        null=True,
        blank=True,
    )
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.PROTECT,
        related_name="rental_application",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.application_number or f"Application · {self.applicant_name}"


class LeaseNotice(TimeStampedModel):
    class NoticeType(models.TextChoices):
        TENANT_TERMINATION = "tenant_termination", "Tenant termination"
        LANDLORD_TERMINATION = "landlord_termination", "Landlord termination"
        NON_RENEWAL = "non_renewal", "Non-renewal"
        RENEWAL_OFFER = "renewal_offer", "Renewal offer"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SERVED = "served", "Served"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        WITHDRAWN = "withdrawn", "Withdrawn"
        COMPLETED = "completed", "Completed"

    notice_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="notices")
    notice_type = models.CharField(max_length=30, choices=NoticeType.choices)
    notice_date = models.DateField(default=timezone.localdate)
    effective_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    served_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="served_lease_notices",
        null=True,
        blank=True,
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-notice_date", "-id")

    def clean(self):
        if self.effective_date and self.notice_date and self.effective_date <= self.notice_date:
            raise ValidationError({"effective_date": "The effective date must be after the notice date."})

    def __str__(self):
        return self.notice_number or f"Notice · {self.lease}"


class Inspection(TimeStampedModel):
    class InspectionType(models.TextChoices):
        MOVE_IN = "move_in", "Move-in"
        ROUTINE = "routine", "Routine"
        MOVE_OUT = "move_out", "Move-out"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        ACKNOWLEDGED = "acknowledged", "Tenant acknowledged"
        CANCELLED = "cancelled", "Cancelled"

    inspection_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="inspections")
    lease = models.ForeignKey(
        Lease,
        on_delete=models.PROTECT,
        related_name="inspections",
        null=True,
        blank=True,
    )
    inspection_type = models.CharField(max_length=20, choices=InspectionType.choices)
    scheduled_for = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rental_inspections",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    electricity_reading = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    water_reading = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    keys_issued = models.PositiveSmallIntegerField(default=0)
    tenant_acknowledged = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-scheduled_for",)

    def clean(self):
        if self.lease_id and self.unit_id and self.lease.unit_id != self.unit_id:
            raise ValidationError({"lease": "The lease must belong to the inspected unit."})

    def __str__(self):
        return self.inspection_number or f"{self.get_inspection_type_display()} · {self.unit}"


class InspectionItem(models.Model):
    class Condition(models.TextChoices):
        EXCELLENT = "excellent", "Excellent"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        POOR = "poor", "Poor"
        DAMAGED = "damaged", "Damaged"

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="items")
    area = models.CharField(max_length=100)
    item = models.CharField(max_length=140)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.GOOD)
    notes = models.TextField(blank=True)
    estimated_damage_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ("area", "item")

    def __str__(self):
        return f"{self.area} · {self.item}"


class InventoryItem(TimeStampedModel):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="inventory_items")
    name = models.CharField(max_length=140)
    serial_number = models.CharField(max_length=80, blank=True)
    quantity = models.PositiveSmallIntegerField(default=1)
    condition = models.CharField(max_length=20, choices=InspectionItem.Condition.choices, default=InspectionItem.Condition.GOOD)
    replacement_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("unit", "name")
        constraints = [
            models.UniqueConstraint(fields=("unit", "name", "serial_number"), name="unique_unit_inventory_item")
        ]

    def __str__(self):
        return f"{self.unit} · {self.name}"


class SecurityDepositTransaction(TimeStampedModel):
    class TransactionType(models.TextChoices):
        RECEIPT = "receipt", "Deposit received"
        DEDUCTION = "deduction", "Deposit deduction"
        REFUND = "refund", "Deposit refund"
        ADJUSTMENT_IN = "adjustment_in", "Positive adjustment"

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        VOID = "void", "Void"

    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="deposit_transactions")
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    transaction_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=100, blank=True)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POSTED)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="posted_deposit_transactions",
        null=True,
        blank=True,
    )
    void_reason = models.TextField(blank=True)

    objects = ProtectedFinancialQuerySet.as_manager()

    class Meta:
        ordering = ("transaction_date", "id")
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="positive_deposit_transaction")]

    def delete(self, *args, **kwargs):
        raise ValidationError("Deposit transactions cannot be deleted. Void the transaction instead.")

    def __str__(self):
        return f"{self.lease.lease_number} · {self.get_transaction_type_display()}"


class UtilityMeter(TimeStampedModel):
    class UtilityType(models.TextChoices):
        WATER = "water", "Water"
        ELECTRICITY = "electricity", "Electricity"
        GAS = "gas", "Gas"

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="utility_meters")
    utility_type = models.CharField(max_length=20, choices=UtilityType.choices)
    meter_number = models.CharField(max_length=80)
    unit_rate = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    standing_charge = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("unit", "utility_type")
        constraints = [
            models.UniqueConstraint(fields=("unit", "utility_type", "meter_number"), name="unique_unit_meter")
        ]

    def __str__(self):
        return f"{self.unit} · {self.get_utility_type_display()} {self.meter_number}"


class UtilityReading(TimeStampedModel):
    meter = models.ForeignKey(UtilityMeter, on_delete=models.PROTECT, related_name="readings")
    reading_date = models.DateField(default=timezone.localdate)
    reading = models.DecimalField(max_digits=14, decimal_places=3)
    previous_reading = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    consumption = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    charge = models.OneToOneField(
        RentCharge,
        on_delete=models.PROTECT,
        related_name="utility_reading",
        null=True,
        blank=True,
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_utility_readings",
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-reading_date", "-id")
        constraints = [
            models.UniqueConstraint(fields=("meter", "reading_date"), name="unique_meter_reading_date")
        ]

    def clean(self):
        if self.reading < self.previous_reading:
            raise ValidationError({"reading": "The reading cannot be lower than the previous reading."})

    def __str__(self):
        return f"{self.meter} · {self.reading_date}"


class LeaseAmendment(TimeStampedModel):
    class AmendmentType(models.TextChoices):
        RENT_CHANGE = "rent_change", "Rent change"
        TERM_EXTENSION = "term_extension", "Term extension"
        OCCUPANT_CHANGE = "occupant_change", "Occupant change"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="amendments")
    amendment_type = models.CharField(max_length=30, choices=AmendmentType.choices)
    effective_date = models.DateField()
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_lease_amendments",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-effective_date",)

    def __str__(self):
        return f"{self.lease} · {self.get_amendment_type_display()}"


def document_upload_path(instance, filename):
    return f"rental-documents/{instance.object_type}/{instance.object_id}/{filename}"


class Document(TimeStampedModel):
    class Category(models.TextChoices):
        IDENTIFICATION = "identification", "Identification"
        APPLICATION = "application", "Application"
        LEASE = "lease", "Lease"
        INSPECTION = "inspection", "Inspection"
        RECEIPT = "receipt", "Receipt"
        INVOICE = "invoice", "Invoice"
        NOTICE = "notice", "Notice"
        OTHER = "other", "Other"

    title = models.CharField(max_length=140)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.OTHER)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=50)
    file = models.FileField(upload_to=document_upload_path)
    expires_on = models.DateField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_rental_documents",
        null=True,
        blank=True,
    )
    is_private = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("object_type", "object_id"))]

    def __str__(self):
        return self.title


class MessageTemplate(TimeStampedModel):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "In-app"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"

    name = models.CharField(max_length=100, unique=True)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.IN_APP)
    subject = models.CharField(max_length=140, blank=True)
    body = models.TextField(help_text="Use plain text. Merge fields can be filled before sending.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class CommunicationLog(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    channel = models.CharField(max_length=20, choices=MessageTemplate.Channel.choices)
    recipient_name = models.CharField(max_length=140)
    recipient_address = models.CharField(max_length=255)
    subject = models.CharField(max_length=140, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    related_type = models.CharField(max_length=80, blank=True)
    related_id = models.CharField(max_length=50, blank=True)
    external_reference = models.CharField(max_length=140, blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rental_communications",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_channel_display()} · {self.recipient_name}"


class PaymentReconciliation(TimeStampedModel):
    class Status(models.TextChoices):
        UNMATCHED = "unmatched", "Unmatched"
        MATCHED = "matched", "Matched"
        DISPUTED = "disputed", "Disputed"
        IGNORED = "ignored", "Ignored"

    provider = models.CharField(max_length=40, choices=Payment.Method.choices)
    external_reference = models.CharField(max_length=140)
    transaction_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payer = models.CharField(max_length=140, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="reconciliation",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNMATCHED)
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="matched_payment_reconciliations",
        null=True,
        blank=True,
    )
    matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-transaction_date", "-id")
        constraints = [
            models.UniqueConstraint(fields=("provider", "external_reference"), name="unique_provider_transaction")
        ]

    def __str__(self):
        return f"{self.provider} · {self.external_reference}"


class OwnerStatement(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    statement_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    owner = models.ForeignKey(Landlord, on_delete=models.PROTECT, related_name="statements")
    property = models.ForeignKey(
        Property,
        on_delete=models.PROTECT,
        related_name="owner_statements",
        null=True,
        blank=True,
    )
    period_start = models.DateField()
    period_end = models.DateField()
    rent_collected = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    other_income = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    management_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_payable = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_owner_statements",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    payout_reference = models.CharField(max_length=140, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-period_end", "-id")
        constraints = [
            models.CheckConstraint(condition=models.Q(period_end__gte=models.F("period_start")), name="valid_owner_statement_period"),
            models.UniqueConstraint(
                fields=("owner", "property", "period_start", "period_end"),
                name="unique_owner_statement_period",
            ),
        ]

    def __str__(self):
        return self.statement_number or f"Statement · {self.owner}"


# Legacy records retained for migration compatibility and gradual product expansion.
class Complaint(models.Model):
    STATUS = (("Open", "Open"), ("Resolved", "Resolved"), ("Closed", "Closed"))
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    subject = models.CharField(max_length=100)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS, default="Open")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.subject


class Booking(models.Model):
    STATUS_CHOICES = (
        ("Pending", "Pending"),
        ("Confirmed", "Confirmed"),
        ("Cancelled", "Cancelled"),
        ("Completed", "Completed"),
    )
    booking_date = models.DateField()
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    customer_name = models.CharField(max_length=100)
    customer_phone = models.CharField(max_length=20)
    customer_email = models.EmailField()
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.customer_name


class Broker(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    national_id = models.CharField(max_length=30)
    address = models.CharField(max_length=255)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return self.user.get_full_name()


class Location(models.Model):
    district = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    village = models.CharField(max_length=100)
    street = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.city}, {self.district}"


# Backwards-compatible imports used by older code and migrations.
landlord = Landlord
broker = Broker
