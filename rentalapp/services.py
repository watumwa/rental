import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    AuditLog,
    CommunicationLog,
    Expense,
    Inspection,
    Landlord,
    Lease,
    LeaseAmendment,
    LeaseNotice,
    MaintenanceRequest,
    Notification,
    OwnerStatement,
    Payment,
    PaymentAllocation,
    PaymentRefund,
    Receipt,
    RentalApplication,
    RentCharge,
    SecurityDepositTransaction,
    Tenant,
    Unit,
    UtilityMeter,
    UtilityReading,
)


def _next_month(value):
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _due_date(year, month, due_day):
    return date(year, month, min(due_day, calendar.monthrange(year, month)[1]))


@transaction.atomic
def generate_rent_schedule(lease):
    """Create an immutable monthly schedule. Existing periods are never duplicated."""
    period = lease.start_date.replace(day=1)
    final_period = lease.end_date.replace(day=1)
    month_step = {"monthly": 1, "quarterly": 3, "annual": 12}.get(lease.billing_frequency)
    if not month_step:
        raise ValidationError("Unsupported billing frequency.")
    created = []
    while period <= final_period:
        calculated_due_date = _due_date(period.year, period.month, lease.due_day)
        charge, was_created = RentCharge.objects.get_or_create(
            lease=lease,
            period=period,
            charge_type=RentCharge.ChargeType.RENT,
            defaults={
                "due_date": max(lease.start_date, calculated_due_date),
                "description": f"Rent · {period:%B %Y}",
                "amount": lease.rent_amount,
            },
        )
        if was_created:
            created.append(charge)
        if lease.unit.service_charge > 0:
            service_charge, service_created = RentCharge.objects.get_or_create(
                lease=lease,
                period=period,
                charge_type=RentCharge.ChargeType.SERVICE_CHARGE,
                defaults={
                    "due_date": max(lease.start_date, calculated_due_date),
                    "description": f"Service charge · {period:%B %Y}",
                    "amount": lease.unit.service_charge,
                },
            )
            if service_created:
                created.append(service_charge)
        for _ in range(month_step):
            period = _next_month(period)
    return created


def audit(*, actor, action, instance, old_value=None, new_value=None, request=None):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") if request else ""
    ip_address = (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) if request else None
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=instance._meta.verbose_name,
        object_id=str(instance.pk),
        object_label=str(instance),
        old_value=old_value or {},
        new_value=new_value or {},
        ip_address=ip_address,
    )


@transaction.atomic
def post_payment(*, cleaned_data, actor=None, request=None):
    lease = cleaned_data["lease"]
    payment = Payment.objects.create(
        lease=lease,
        amount=cleaned_data["amount"],
        payment_date=cleaned_data["payment_date"],
        payment_method=cleaned_data["payment_method"],
        reference=cleaned_data.get("reference", ""),
        notes=cleaned_data.get("notes", ""),
        received_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    payment.receipt_number = f"RC-{payment.payment_date.year}-{payment.pk:06d}"
    payment.save(update_fields=("receipt_number", "updated_at"))
    Receipt.objects.create(payment=payment, number=payment.receipt_number)

    remaining = payment.amount
    charges = lease.rent_charges.exclude(status=RentCharge.Status.VOID).order_by("due_date", "id")
    for charge in charges:
        if remaining <= 0:
            break
        outstanding = charge.balance
        if outstanding <= 0:
            continue
        allocation = min(remaining, outstanding)
        PaymentAllocation.objects.create(payment=payment, charge=charge, amount=allocation)
        remaining -= allocation
        charge.refresh_status()

    audit(
        actor=actor,
        action="payment_posted",
        instance=payment,
        new_value={
            "amount": str(payment.amount),
            "lease": lease.lease_number,
            "allocated": str(payment.allocated_amount),
            "unallocated": str(payment.unallocated_amount),
        },
        request=request,
    )
    return payment


@transaction.atomic
def void_payment(*, payment, reason, actor=None, request=None):
    if payment.status == Payment.Status.VOID:
        raise ValidationError("This payment has already been voided.")
    old_value = {"status": payment.status, "amount": str(payment.amount), "reference": payment.reference}
    payment.status = Payment.Status.VOID
    payment.void_reason = reason
    payment.voided_at = timezone.now()
    payment.voided_by = actor if getattr(actor, "is_authenticated", False) else None
    payment.save(update_fields=("status", "void_reason", "voided_at", "voided_by", "updated_at"))
    for allocation in payment.allocations.select_related("charge"):
        allocation.charge.refresh_status()
    audit(
        actor=actor,
        action="payment_voided",
        instance=payment,
        old_value=old_value,
        new_value={"status": payment.status, "reason": reason},
        request=request,
    )
    return payment


@transaction.atomic
def refund_unallocated_payment(*, payment, cleaned_data, actor=None, request=None):
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    amount = cleaned_data["amount"]
    if payment.status != Payment.Status.POSTED:
        raise ValidationError("A voided payment cannot be refunded.")
    if amount <= 0 or amount > payment.unallocated_amount:
        raise ValidationError("Only available unallocated credit can be refunded.")
    refund = PaymentRefund.objects.create(
        payment=payment,
        amount=amount,
        refund_date=cleaned_data["refund_date"],
        reference=cleaned_data["reference"],
        reason=cleaned_data["reason"],
        posted_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    refund.refund_number = f"RF-{refund.refund_date.year}-{refund.pk:06d}"
    refund.save(update_fields=("refund_number", "updated_at"))
    audit(
        actor=actor,
        action="payment_credit_refunded",
        instance=refund,
        new_value={"payment": str(payment.pk), "amount": str(amount)},
        request=request,
    )
    return refund


@transaction.atomic
def post_manual_charge(*, lease, cleaned_data, actor=None, request=None):
    amount = cleaned_data["amount"]
    status = RentCharge.Status.UNPAID
    if cleaned_data["charge_type"] == RentCharge.ChargeType.DISCOUNT:
        amount = -amount
        status = RentCharge.Status.PAID
    charge = RentCharge.objects.create(
        lease=lease,
        amount=amount,
        status=status,
        **{key: value for key, value in cleaned_data.items() if key != "amount"},
    )
    audit(
        actor=actor,
        action="manual_charge_posted",
        instance=charge,
        new_value={"lease": lease.lease_number, "type": charge.charge_type, "amount": str(amount)},
        request=request,
    )
    return charge


def assign_reference(instance):
    if isinstance(instance, MaintenanceRequest) and not instance.request_number:
        instance.request_number = f"MR-{timezone.localdate().year}-{instance.pk:05d}"
        instance.save(update_fields=("request_number", "updated_at"))
    elif isinstance(instance, Expense) and not instance.expense_number:
        instance.expense_number = f"EX-{timezone.localdate().year}-{instance.pk:05d}"
        instance.save(update_fields=("expense_number", "updated_at"))
    elif isinstance(instance, RentalApplication) and not instance.application_number:
        instance.application_number = f"APP-{timezone.localdate().year}-{instance.pk:05d}"
        instance.save(update_fields=("application_number", "updated_at"))
    elif isinstance(instance, LeaseNotice) and not instance.notice_number:
        instance.notice_number = f"NT-{timezone.localdate().year}-{instance.pk:05d}"
        instance.save(update_fields=("notice_number", "updated_at"))
    elif isinstance(instance, Inspection) and not instance.inspection_number:
        instance.inspection_number = f"IN-{timezone.localdate().year}-{instance.pk:05d}"
        instance.save(update_fields=("inspection_number", "updated_at"))
    elif isinstance(instance, OwnerStatement) and not instance.statement_number:
        instance.statement_number = f"OS-{instance.period_end.year}-{instance.pk:05d}"
        instance.save(update_fields=("statement_number", "updated_at"))


def synchronize_occupancy(unit):
    active = unit.leases.filter(status=Lease.Status.ACTIVE).exists()
    target = Unit.Status.OCCUPIED if active else Unit.Status.AVAILABLE
    if unit.status not in (Unit.Status.MAINTENANCE, Unit.Status.BLOCKED) and unit.status != target:
        unit.status = target
        unit.save(update_fields=("status", "updated_at"))


@transaction.atomic
def decide_application(*, application, decision, actor=None, reason="", request=None):
    allowed = {
        RentalApplication.Status.SUBMITTED: (
            RentalApplication.Status.SCREENING,
            RentalApplication.Status.APPROVED,
            RentalApplication.Status.REJECTED,
            RentalApplication.Status.WITHDRAWN,
        ),
        RentalApplication.Status.SCREENING: (
            RentalApplication.Status.APPROVED,
            RentalApplication.Status.REJECTED,
            RentalApplication.Status.WITHDRAWN,
        ),
        RentalApplication.Status.APPROVED: (RentalApplication.Status.CONVERTED,),
    }
    if decision not in allowed.get(application.status, ()):
        raise ValidationError(f"Cannot move an application from {application.status} to {decision}.")
    old_status = application.status
    application.status = decision
    if decision in (RentalApplication.Status.APPROVED, RentalApplication.Status.REJECTED):
        application.decided_at = timezone.now()
        application.decided_by = actor if getattr(actor, "is_authenticated", False) else None
        application.decision_reason = reason
    if decision == RentalApplication.Status.APPROVED:
        tenant = Tenant.objects.filter(phone=application.phone).first()
        if not tenant:
            tenant = Tenant.objects.create(
                phone=application.phone,
                full_name=application.applicant_name,
                email=application.email,
                national_id=application.national_id,
                status=Tenant.Status.PROSPECTIVE,
            )
        application.tenant = tenant
        if application.unit.status == Unit.Status.AVAILABLE:
            application.unit.status = Unit.Status.RESERVED
            application.unit.save(update_fields=("status", "updated_at"))
    elif decision in (RentalApplication.Status.REJECTED, RentalApplication.Status.WITHDRAWN):
        has_other_approved = application.unit.applications.filter(
            status__in=(RentalApplication.Status.APPROVED, RentalApplication.Status.CONVERTED)
        ).exclude(pk=application.pk).exists()
        if not has_other_approved and application.unit.status in (Unit.Status.RESERVED, Unit.Status.APPLICATION_PENDING):
            application.unit.status = Unit.Status.AVAILABLE
            application.unit.save(update_fields=("status", "updated_at"))
    application.save()
    audit(
        actor=actor,
        action="application_status_changed",
        instance=application,
        old_value={"status": old_status},
        new_value={"status": decision, "reason": reason},
        request=request,
    )
    return application


@transaction.atomic
def activate_lease(*, lease, actor=None, request=None):
    if lease.status not in (Lease.Status.DRAFT, Lease.Status.PENDING):
        raise ValidationError("Only a draft or pending lease can be activated.")
    move_in = lease.inspections.filter(
        inspection_type=Inspection.InspectionType.MOVE_IN,
        status__in=(Inspection.Status.COMPLETED, Inspection.Status.ACKNOWLEDGED),
    ).first()
    if not move_in:
        raise ValidationError("Complete a move-in inspection before activating the lease.")
    if lease.renewal_of_id and lease.renewal_of.status in (Lease.Status.ACTIVE, Lease.Status.EXPIRING):
        lease.renewal_of.status = Lease.Status.RENEWED
        lease.renewal_of.save(update_fields=("status", "updated_at"))
    conflicts = Lease.objects.filter(
        unit=lease.unit,
        status__in=(Lease.Status.ACTIVE, Lease.Status.EXPIRING),
    ).exclude(pk=lease.pk)
    if conflicts.exists():
        raise ValidationError("The unit already has a current lease.")
    old_status = lease.status
    lease.status = Lease.Status.ACTIVE
    lease.signed_at = lease.signed_at or timezone.now()
    lease.activated_at = timezone.now()
    lease.full_clean()
    lease.save()
    generated = generate_rent_schedule(lease)
    synchronize_occupancy(lease.unit)
    if lease.tenant.status != Tenant.Status.ACTIVE:
        lease.tenant.status = Tenant.Status.ACTIVE
        lease.tenant.save(update_fields=("status", "updated_at"))
    if lease.application_id and lease.application.status != RentalApplication.Status.CONVERTED:
        lease.application.status = RentalApplication.Status.CONVERTED
        lease.application.save(update_fields=("status", "updated_at"))
    audit(
        actor=actor,
        action="lease_activated",
        instance=lease,
        old_value={"status": old_status},
        new_value={"status": lease.status, "charges_generated": len(generated)},
        request=request,
    )
    return lease


@transaction.atomic
def create_renewal(*, lease, start_date, end_date, rent_amount, actor=None, request=None):
    if lease.status not in (Lease.Status.ACTIVE, Lease.Status.EXPIRING, Lease.Status.EXPIRED):
        raise ValidationError("Only a current or recently expired lease can be renewed.")
    if start_date <= lease.end_date or end_date <= start_date:
        raise ValidationError("The renewal must start after the current lease and have a valid end date.")
    renewal = Lease.objects.create(
        lease_number=f"{lease.lease_number}-R{lease.renewals.count() + 1}",
        tenant=lease.tenant,
        unit=lease.unit,
        start_date=start_date,
        end_date=end_date,
        rent_amount=rent_amount,
        billing_frequency=lease.billing_frequency,
        due_day=lease.due_day,
        security_deposit_required=lease.security_deposit_required,
        notice_period_days=lease.notice_period_days,
        status=Lease.Status.PENDING,
        renewal_of=lease,
        notes=f"Renewal of {lease.lease_number}",
    )
    audit(
        actor=actor,
        action="lease_renewal_created",
        instance=renewal,
        new_value={"renewal_of": lease.lease_number},
        request=request,
    )
    return renewal


@transaction.atomic
def complete_inspection(*, inspection, actor=None, acknowledged=False, request=None):
    if inspection.status in (Inspection.Status.CANCELLED, Inspection.Status.ACKNOWLEDGED):
        raise ValidationError("This inspection cannot be completed again.")
    inspection.status = Inspection.Status.ACKNOWLEDGED if acknowledged else Inspection.Status.COMPLETED
    inspection.tenant_acknowledged = acknowledged or inspection.tenant_acknowledged
    inspection.completed_at = timezone.now()
    inspection.save(update_fields=("status", "tenant_acknowledged", "completed_at", "updated_at"))
    audit(
        actor=actor,
        action="inspection_completed",
        instance=inspection,
        new_value={"tenant_acknowledged": inspection.tenant_acknowledged},
        request=request,
    )
    return inspection


@transaction.atomic
def serve_lease_notice(*, notice, actor=None, request=None):
    if notice.status not in (LeaseNotice.Status.DRAFT, LeaseNotice.Status.SERVED):
        raise ValidationError("Only a draft notice can be served.")
    notice.status = LeaseNotice.Status.SERVED
    notice.served_by = actor if getattr(actor, "is_authenticated", False) else None
    notice.save()
    lease = notice.lease
    if lease.status == Lease.Status.ACTIVE:
        lease.status = Lease.Status.EXPIRING
        lease.save(update_fields=("status", "updated_at"))
    if lease.unit.status == Unit.Status.OCCUPIED:
        lease.unit.status = Unit.Status.NOTICE_GIVEN
        lease.unit.save(update_fields=("status", "updated_at"))
    lease.tenant.status = Tenant.Status.NOTICE_GIVEN
    lease.tenant.save(update_fields=("status", "updated_at"))
    audit(actor=actor, action="lease_notice_served", instance=notice, request=request)
    return notice


@transaction.atomic
def complete_move_out(*, lease, actor=None, reason="", request=None):
    move_out = lease.inspections.filter(
        inspection_type=Inspection.InspectionType.MOVE_OUT,
        status__in=(Inspection.Status.COMPLETED, Inspection.Status.ACKNOWLEDGED),
    ).first()
    if not move_out:
        raise ValidationError("Complete a move-out inspection before closing the tenancy.")
    if lease.deposit_held > 0:
        raise ValidationError("Refund or deduct the remaining security deposit before closing the tenancy.")
    old_status = lease.status
    lease.status = Lease.Status.TERMINATED
    lease.terminated_at = timezone.now()
    lease.termination_reason = reason
    lease.save(update_fields=("status", "terminated_at", "termination_reason", "updated_at"))
    lease.unit.status = Unit.Status.AVAILABLE
    lease.unit.save(update_fields=("status", "updated_at"))
    lease.tenant.status = Tenant.Status.FORMER
    lease.tenant.save(update_fields=("status", "updated_at"))
    lease.notices.exclude(status__in=(LeaseNotice.Status.WITHDRAWN, LeaseNotice.Status.COMPLETED)).update(
        status=LeaseNotice.Status.COMPLETED,
        updated_at=timezone.now(),
    )
    audit(
        actor=actor,
        action="move_out_completed",
        instance=lease,
        old_value={"status": old_status},
        new_value={"status": lease.status, "inspection": move_out.inspection_number},
        request=request,
    )
    return lease


@transaction.atomic
def post_deposit_transaction(*, cleaned_data, actor=None, request=None):
    lease = cleaned_data["lease"]
    if not lease.deposit_transactions.exists() and lease.security_deposit_received > 0:
        SecurityDepositTransaction.objects.create(
            lease=lease,
            transaction_type=SecurityDepositTransaction.TransactionType.ADJUSTMENT_IN,
            amount=lease.security_deposit_received,
            transaction_date=cleaned_data.get("transaction_date") or timezone.localdate(),
            reference="Opening balance",
            reason="Deposit balance migrated from the lease record.",
            posted_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
    item = SecurityDepositTransaction.objects.create(
        **cleaned_data,
        posted_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    lease.security_deposit_received = lease.deposit_held
    lease.save(update_fields=("security_deposit_received", "updated_at"))
    audit(
        actor=actor,
        action="deposit_transaction_posted",
        instance=item,
        new_value={"type": item.transaction_type, "amount": str(item.amount)},
        request=request,
    )
    return item


@transaction.atomic
def record_utility_reading(*, cleaned_data, actor=None, request=None):
    meter = cleaned_data["meter"]
    reading_date = cleaned_data["reading_date"]
    previous = meter.readings.filter(reading_date__lt=reading_date).order_by("-reading_date", "-id").first()
    previous_value = previous.reading if previous else Decimal("0")
    current_value = cleaned_data["reading"]
    if current_value < previous_value:
        raise ValidationError({"reading": "The reading cannot be lower than the previous reading."})
    consumption = current_value - previous_value
    amount = (consumption * meter.unit_rate + meter.standing_charge).quantize(Decimal("0.01"))
    lease = meter.unit.leases.filter(
        status__in=(Lease.Status.ACTIVE, Lease.Status.EXPIRING),
        start_date__lte=reading_date,
        end_date__gte=reading_date,
    ).first()
    if not lease:
        raise ValidationError("There is no current lease to bill for this meter reading.")
    period = reading_date.replace(day=1)
    charge_type = {
        UtilityMeter.UtilityType.WATER: RentCharge.ChargeType.WATER,
        UtilityMeter.UtilityType.ELECTRICITY: RentCharge.ChargeType.ELECTRICITY,
    }.get(meter.utility_type, RentCharge.ChargeType.OTHER)
    if RentCharge.objects.filter(lease=lease, period=period, charge_type=charge_type).exists():
        raise ValidationError("A utility charge for this type and billing period already exists.")
    reading = UtilityReading.objects.create(
        **cleaned_data,
        previous_reading=previous_value,
        consumption=consumption,
        amount=amount,
        recorded_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    charge = RentCharge.objects.create(
        lease=lease,
        period=period,
        due_date=reading_date,
        charge_type=charge_type,
        description=f"{meter.get_utility_type_display()} · {consumption:,.3f} units",
        amount=amount,
        source_reference=f"meter-reading:{reading.pk}",
    )
    reading.charge = charge
    reading.save(update_fields=("charge", "updated_at"))
    audit(
        actor=actor,
        action="utility_reading_recorded",
        instance=reading,
        new_value={"consumption": str(consumption), "amount": str(amount)},
        request=request,
    )
    return reading


@transaction.atomic
def approve_amendment(*, amendment, actor=None, request=None):
    if amendment.status != LeaseAmendment.Status.DRAFT:
        raise ValidationError("Only a draft amendment can be approved.")
    lease = amendment.lease
    if amendment.amendment_type == LeaseAmendment.AmendmentType.RENT_CHANGE:
        amount = Decimal(str(amendment.new_value.get("rent_amount", "0")))
        if amount <= 0:
            raise ValidationError("A rent amendment requires a positive rent_amount value.")
        amendment.old_value = {"rent_amount": str(lease.rent_amount)}
        lease.rent_amount = amount
        lease.save(update_fields=("rent_amount", "updated_at"))
        lease.rent_charges.filter(
            period__gte=amendment.effective_date.replace(day=1),
            charge_type=RentCharge.ChargeType.RENT,
            status=RentCharge.Status.UNPAID,
        ).update(amount=amount, updated_at=timezone.now())
    elif amendment.amendment_type == LeaseAmendment.AmendmentType.TERM_EXTENSION:
        end_date = date.fromisoformat(amendment.new_value.get("end_date", ""))
        if end_date <= lease.end_date:
            raise ValidationError("The new end date must extend the lease.")
        amendment.old_value = {"end_date": lease.end_date.isoformat()}
        lease.end_date = end_date
        lease.save(update_fields=("end_date", "updated_at"))
        generate_rent_schedule(lease)
    amendment.status = LeaseAmendment.Status.APPROVED
    amendment.approved_by = actor if getattr(actor, "is_authenticated", False) else None
    amendment.approved_at = timezone.now()
    amendment.save()
    audit(actor=actor, action="lease_amendment_approved", instance=amendment, request=request)
    return amendment


@transaction.atomic
def generate_owner_statement(*, cleaned_data, actor=None, request=None):
    owner = cleaned_data["owner"]
    property_item = cleaned_data.get("property")
    start = cleaned_data["period_start"]
    end = cleaned_data["period_end"]
    properties = owner.properties.all()
    if property_item:
        if property_item.owner_id != owner.pk:
            raise ValidationError("The selected property does not belong to this owner.")
        properties = properties.filter(pk=property_item.pk)
    income = Payment.objects.filter(
        lease__unit__property__in=properties,
        status=Payment.Status.POSTED,
        payment_date__range=(start, end),
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    refunds = PaymentRefund.objects.filter(
        payment__lease__unit__property__in=properties,
        status=PaymentRefund.Status.POSTED,
        refund_date__range=(start, end),
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    income -= refunds
    expenses = Expense.objects.filter(
        property__in=properties,
        status="posted",
        expense_date__range=(start, end),
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    fee = (income * owner.management_fee_rate / Decimal("100")).quantize(Decimal("0.01"))
    statement = OwnerStatement.objects.create(
        **cleaned_data,
        rent_collected=income,
        expenses=expenses,
        management_fee=fee,
        net_payable=income + cleaned_data.get("other_income", Decimal("0")) - expenses - fee,
    )
    assign_reference(statement)
    audit(actor=actor, action="owner_statement_generated", instance=statement, request=request)
    return statement


def queue_communication(*, cleaned_data, actor=None, related=None):
    item = CommunicationLog.objects.create(
        **cleaned_data,
        related_type=related._meta.label_lower if related else "",
        related_id=str(related.pk) if related else "",
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    if item.channel == "in_app":
        Notification.objects.create(
            message=item.message,
            level="info",
        )
        item.status = CommunicationLog.Status.SENT
        item.sent_at = timezone.now()
        item.save(update_fields=("status", "sent_at", "updated_at"))
    return item


@transaction.atomic
def run_daily_operations(today=None):
    today = today or timezone.localdate()
    expiring_cutoff = today + timedelta(days=45)
    Lease.objects.filter(
        status=Lease.Status.ACTIVE,
        end_date__range=(today, expiring_cutoff),
    ).update(status=Lease.Status.EXPIRING, updated_at=timezone.now())
    expired = Lease.objects.filter(
        status__in=(Lease.Status.ACTIVE, Lease.Status.EXPIRING),
        end_date__lt=today,
    )
    expired_count = expired.update(status=Lease.Status.EXPIRED, updated_at=timezone.now())
    reminder_count = 0
    for charge in RentCharge.objects.filter(
        due_date__lt=today,
    ).exclude(status__in=(RentCharge.Status.PAID, RentCharge.Status.VOID)).select_related("lease__tenant"):
        marker = f"arrears:{charge.pk}:{today.isoformat()}"
        if CommunicationLog.objects.filter(external_reference=marker).exists():
            continue
        tenant = charge.lease.tenant
        CommunicationLog.objects.create(
            channel="sms",
            recipient_name=str(tenant),
            recipient_address=tenant.phone,
            message=f"RentPro reminder: {charge.description} has an outstanding balance of UGX {charge.balance:,.0f}.",
            status=CommunicationLog.Status.QUEUED,
            related_type=charge._meta.label_lower,
            related_id=str(charge.pk),
            external_reference=marker,
        )
        reminder_count += 1
    return {"expired": expired_count, "reminders": reminder_count}
