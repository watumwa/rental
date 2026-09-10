import csv
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    ApplicationDecisionForm,
    BuildingForm,
    CommunicationForm,
    DocumentForm,
    ExpenseForm,
    InspectionForm,
    InspectionItemForm,
    InventoryItemForm,
    LandlordForm,
    LeaseForm,
    LeaseAmendmentForm,
    LeaseNoticeForm,
    LeaseRenewalForm,
    ManualChargeForm,
    MaintenanceRequestForm,
    OwnerStatementForm,
    PaymentForm,
    PaymentRefundForm,
    PaymentReconciliationForm,
    PropertyForm,
    RentalApplicationForm,
    SecurityDepositTransactionForm,
    TenantForm,
    UnitForm,
    UtilityMeterForm,
    UtilityReadingForm,
    VendorForm,
    VoidPaymentForm,
)
from .models import (
    AuditLog,
    Building,
    CommunicationLog,
    Document,
    Expense,
    Inspection,
    InventoryItem,
    Landlord,
    Lease,
    LeaseAmendment,
    LeaseNotice,
    MaintenanceRequest,
    Notification,
    OwnerStatement,
    Payment,
    PaymentReconciliation,
    PaymentRefund,
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
from .permissions import ADMIN_ROLES, FINANCE_ROLES, OPERATIONS_ROLES, STAFF_ROLES, get_user_role, login_and_roles_required
from .services import (
    activate_lease,
    approve_amendment,
    assign_reference,
    audit,
    complete_inspection,
    complete_move_out,
    create_renewal,
    decide_application,
    generate_owner_statement,
    post_deposit_transaction,
    post_manual_charge,
    post_payment,
    queue_communication,
    record_utility_reading,
    refund_unallocated_payment,
    serve_lease_notice,
    synchronize_occupancy,
    void_payment,
)


def _actor(request):
    return request.user if request.user.is_authenticated else None


def post_login_required(view):
    """Allow staff to read core records and managers to change them."""
    staff_view = login_and_roles_required(*STAFF_ROLES)(view)

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if (
            request.user.is_authenticated
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and get_user_role(request.user) not in ADMIN_ROLES
        ):
            raise PermissionDenied("Only a property manager can change this record.")
        return staff_view(request, *args, **kwargs)

    return wrapped


def _form_errors(request, form):
    messages.error(request, "Please correct the highlighted fields and try again.")
    return form


@login_and_roles_required()
def role_home(request):
    role = get_user_role(request.user)
    if role in STAFF_ROLES:
        return redirect("dashboard")
    if role == "tenant":
        return redirect("tenant_portal")
    if role == "landlord":
        return redirect("landlord_portal")
    raise PermissionDenied("Ask an administrator to assign this account a RentPro role.")


@login_and_roles_required(*STAFF_ROLES)
def dashboard(request):
    today = timezone.localdate()
    period = today.replace(day=1)
    properties = list(Property.objects.filter(status="active").prefetch_related("units"))
    units = Unit.objects.select_related("property")
    total_units = units.count()
    occupied_units = units.filter(status=Unit.Status.OCCUPIED).count()
    vacant_units = units.filter(status=Unit.Status.AVAILABLE).count()
    maintenance_units = units.filter(status=Unit.Status.MAINTENANCE).count()
    occupancy_rate = round((occupied_units / total_units * 100), 1) if total_units else 0

    current_charges = list(
        RentCharge.objects.filter(period=period).select_related("lease__tenant", "lease__unit__property")
    )
    expected_rent = sum((item.amount for item in current_charges), Decimal("0"))
    collected_rent = sum((item.allocated_amount for item in current_charges), Decimal("0"))
    collection_rate = round((collected_rent / expected_rent * 100), 1) if expected_rent else 0

    overdue_charges = [
        charge
        for charge in RentCharge.objects.filter(due_date__lte=today)
        .exclude(status__in=(RentCharge.Status.PAID, RentCharge.Status.VOID))
        .select_related("lease__tenant", "lease__unit__property")
        if charge.balance > 0
    ]
    outstanding = sum((charge.balance for charge in overdue_charges), Decimal("0"))
    affected_tenants = len({charge.lease.tenant_id for charge in overdue_charges})
    arrears_buckets = _arrears_buckets(overdue_charges, today)

    maintenance_counts = {
        key: MaintenanceRequest.objects.filter(status=key).count()
        for key in (
            MaintenanceRequest.Status.NEW,
            MaintenanceRequest.Status.ASSIGNED,
            MaintenanceRequest.Status.IN_PROGRESS,
            MaintenanceRequest.Status.AWAITING_PARTS,
        )
    }
    maintenance_counts["completed"] = MaintenanceRequest.objects.filter(
        status__in=(MaintenanceRequest.Status.COMPLETED, MaintenanceRequest.Status.VERIFIED, MaintenanceRequest.Status.CLOSED),
        updated_at__year=today.year,
        updated_at__month=today.month,
    ).count()

    recent_activity = []
    for payment in Payment.objects.select_related("lease__tenant", "lease__unit").all()[:6]:
        recent_activity.append(
            {
                "time": payment.created_at,
                "icon": "ph-wallet",
                "tone": "success" if payment.status == Payment.Status.POSTED else "danger",
                "title": "Rent payment received" if payment.status == Payment.Status.POSTED else "Payment voided",
                "detail": f"{payment.lease.unit.unit_number if payment.lease else 'Unassigned'} · UGX {payment.amount:,.0f}",
                "url": reverse("receipt_detail", args=[payment.pk]),
            }
        )
    for item in MaintenanceRequest.objects.select_related("unit").all()[:6]:
        recent_activity.append(
            {
                "time": item.created_at,
                "icon": "ph-wrench",
                "tone": "warning",
                "title": "Maintenance request created",
                "detail": f"{item.unit.unit_number} · {item.title}",
                "url": reverse("maintenance_list"),
            }
        )
    recent_activity = sorted(recent_activity, key=lambda item: item["time"], reverse=True)[:7]

    expiring_leases = Lease.objects.filter(
        status__in=(Lease.Status.ACTIVE, Lease.Status.EXPIRING),
        end_date__range=(today, today + timedelta(days=45)),
    ).select_related("tenant", "unit__property")[:5]

    months = []
    cursor = period
    for _ in range(6):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
    month_totals = defaultdict(Decimal)
    for row in (
        Payment.objects.filter(status=Payment.Status.POSTED, payment_date__gte=months[0])
        .values("payment_date__year", "payment_date__month")
        .annotate(total=Sum("amount"))
    ):
        month_totals[(row["payment_date__year"], row["payment_date__month"])] = row["total"]
    collection_trend = [
        {"label": month.strftime("%b"), "amount": month_totals[(month.year, month.month)]} for month in months
    ]
    max_collection = max((item["amount"] for item in collection_trend), default=Decimal("0"))
    for item in collection_trend:
        item["height"] = round(item["amount"] / max_collection * 100) if max_collection else 4

    context = {
        "today": today,
        "properties_count": len(properties),
        "total_units": total_units,
        "occupied_units": occupied_units,
        "vacant_units": vacant_units,
        "maintenance_units": maintenance_units,
        "occupancy_rate": occupancy_rate,
        "expected_rent": expected_rent,
        "collected_rent": collected_rent,
        "collection_rate": collection_rate,
        "outstanding": outstanding,
        "affected_tenants": affected_tenants,
        "arrears_buckets": arrears_buckets,
        "maintenance_counts": maintenance_counts,
        "recent_activity": recent_activity,
        "expiring_leases": expiring_leases,
        "collection_trend": collection_trend,
    }
    return render(request, "dashboard.html", context)


@post_login_required
def property_list(request):
    form = PropertyForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save()
            audit(actor=_actor(request), action="property_created", instance=item, request=request)
            messages.success(request, f"{item.name} was added successfully.")
            return redirect(item)
        _form_errors(request, form)
    queryset = Property.objects.select_related("owner").prefetch_related("units")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(address__icontains=query) | Q(district__icontains=query))
    if status:
        queryset = queryset.filter(status=status)
    properties = list(queryset)
    for item in properties:
        item.display_units = len(item.units.all())
        item.display_occupied = sum(unit.status == Unit.Status.OCCUPIED for unit in item.units.all())
        item.display_vacant = sum(unit.status == Unit.Status.AVAILABLE for unit in item.units.all())
        item.display_rent = sum((unit.rent_amount for unit in item.units.all()), Decimal("0"))
    return render(request, "properties/list.html", {"properties": properties, "form": form, "query": query, "status": status})


@login_and_roles_required(*STAFF_ROLES)
def property_detail(request, pk):
    item = get_object_or_404(Property.objects.select_related("owner"), pk=pk)
    units = list(item.units.select_related("building").all())
    active_leases = Lease.objects.filter(unit__property=item, status=Lease.Status.ACTIVE).select_related("tenant", "unit")
    charges = list(RentCharge.objects.filter(lease__unit__property=item).select_related("lease"))
    collected = Payment.objects.filter(
        lease__unit__property=item, status=Payment.Status.POSTED
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    collected -= PaymentRefund.objects.filter(
        payment__lease__unit__property=item,
        status=PaymentRefund.Status.POSTED,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    outstanding = sum((charge.balance for charge in charges if charge.due_date <= timezone.localdate()), Decimal("0"))
    context = {
        "property": item,
        "units": units,
        "active_leases": active_leases,
        "occupied": sum(unit.status == Unit.Status.OCCUPIED for unit in units),
        "vacant": sum(unit.status == Unit.Status.AVAILABLE for unit in units),
        "expected": sum((unit.rent_amount for unit in units), Decimal("0")),
        "collected": collected,
        "outstanding": outstanding,
        "maintenance": item.units.values_list("maintenance_requests", flat=True).count(),
    }
    return render(request, "properties/detail.html", context)


@post_login_required
def unit_list(request):
    form = UnitForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save()
            audit(actor=_actor(request), action="unit_created", instance=item, request=request)
            messages.success(request, f"Unit {item.unit_number} was added.")
            return redirect("unit_detail", pk=item.pk)
        _form_errors(request, form)
    queryset = Unit.objects.select_related("property", "building")
    property_id = request.GET.get("property", "")
    status = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()
    if property_id:
        queryset = queryset.filter(property_id=property_id)
    if status:
        queryset = queryset.filter(status=status)
    if query:
        queryset = queryset.filter(Q(unit_number__icontains=query) | Q(property__name__icontains=query))
    return render(
        request,
        "units/list.html",
        {
            "units": queryset,
            "form": form,
            "properties": Property.objects.filter(status="active"),
            "selected_property": property_id,
            "selected_status": status,
            "query": query,
            "status_choices": Unit.Status.choices,
        },
    )


@login_and_roles_required(*STAFF_ROLES)
def unit_detail(request, pk):
    unit = get_object_or_404(Unit.objects.select_related("property", "building"), pk=pk)
    leases = unit.leases.select_related("tenant").all()
    current_lease = leases.filter(status=Lease.Status.ACTIVE).first()
    return render(
        request,
        "units/detail.html",
        {
            "unit": unit,
            "leases": leases,
            "current_lease": current_lease,
            "maintenance_requests": unit.maintenance_requests.select_related("tenant")[:8],
        },
    )


@post_login_required
def tenant_list(request):
    form = TenantForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save()
            audit(actor=_actor(request), action="tenant_created", instance=item, request=request)
            messages.success(request, f"{item} was registered.")
            return redirect(item)
        _form_errors(request, form)
    queryset = Tenant.objects.prefetch_related("leases__unit__property")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        queryset = queryset.filter(
            Q(full_name__icontains=query) | Q(phone__icontains=query) | Q(national_id__icontains=query)
        )
    if status:
        queryset = queryset.filter(status=status)
    tenants = list(queryset)
    for tenant in tenants:
        tenant.display_lease = next((lease for lease in tenant.leases.all() if lease.status == Lease.Status.ACTIVE), None)
        tenant.display_balance = sum((lease.balance for lease in tenant.leases.all()), Decimal("0"))
    return render(
        request,
        "tenants/list.html",
        {"tenants": tenants, "form": form, "query": query, "selected_status": status, "status_choices": Tenant.Status.choices},
    )


def _tenant_ledger(tenant):
    events = []
    leases = tenant.leases.prefetch_related("rent_charges", "payments")
    for lease in leases:
        for charge in lease.rent_charges.exclude(status=RentCharge.Status.VOID):
            events.append(
                {
                    "date": charge.due_date,
                    "sort": 0,
                    "description": charge.description,
                    "reference": lease.lease_number,
                    "debit": charge.amount,
                    "credit": None,
                    "url": reverse("lease_detail", args=[lease.pk]),
                }
            )
        for payment in lease.payments.filter(status=Payment.Status.POSTED):
            events.append(
                {
                    "date": payment.payment_date,
                    "sort": 1,
                    "description": payment.get_payment_method_display(),
                    "reference": payment.receipt_number,
                    "debit": None,
                    "credit": payment.amount,
                    "url": reverse("receipt_detail", args=[payment.pk]),
                }
            )
    events.sort(key=lambda event: (event["date"], event["sort"], event["reference"] or ""))
    balance = Decimal("0")
    for event in events:
        balance += event["debit"] or Decimal("0")
        balance -= event["credit"] or Decimal("0")
        event["balance"] = balance
    return list(reversed(events)), balance


@login_and_roles_required(*STAFF_ROLES)
def tenant_detail(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    ledger, balance = _tenant_ledger(tenant)
    active_lease = tenant.active_lease
    return render(
        request,
        "tenants/detail.html",
        {
            "tenant": tenant,
            "active_lease": active_lease,
            "leases": tenant.leases.select_related("unit__property"),
            "ledger": ledger,
            "balance": max(balance, Decimal("0")),
            "credit": abs(min(balance, Decimal("0"))),
        },
    )


@post_login_required
def lease_list(request):
    initial = {}
    application_id = request.GET.get("application")
    if application_id:
        application = RentalApplication.objects.filter(
            pk=application_id,
            status=RentalApplication.Status.APPROVED,
            lease__isnull=True,
        ).select_related("tenant", "unit").first()
        if application:
            initial = {
                "application": application,
                "tenant": application.tenant,
                "unit": application.unit,
                "rent_amount": application.unit.rent_amount,
                "start_date": application.requested_move_in,
            }
    form = LeaseForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if form.is_valid():
            lease = form.save(commit=False)
            lease.status = Lease.Status.PENDING
            lease.save()
            audit(
                actor=_actor(request),
                action="lease_created",
                instance=lease,
                new_value={"status": lease.status},
                request=request,
            )
            messages.success(request, f"{lease.lease_number} is pending approval and move-in inspection.")
            return redirect("lease_detail", pk=lease.pk)
        _form_errors(request, form)
    queryset = Lease.objects.select_related("tenant", "unit__property").prefetch_related("rent_charges")
    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "leases/list.html",
        {"leases": queryset, "form": form, "selected_status": status, "status_choices": Lease.Status.choices},
    )


@login_and_roles_required(*STAFF_ROLES)
def lease_detail(request, pk):
    lease = get_object_or_404(Lease.objects.select_related("tenant", "unit__property"), pk=pk)
    charges = list(lease.rent_charges.prefetch_related("allocations__payment"))
    return render(
        request,
        "leases/detail.html",
        {
            "lease": lease,
            "charges": charges,
            "payments": lease.payments.prefetch_related("allocations").all(),
            "total_charged": sum((item.amount for item in charges), Decimal("0")),
            "total_paid": sum((item.allocated_amount for item in charges), Decimal("0")),
            "deposit_held": lease.deposit_held,
            "deposit_transactions": lease.deposit_transactions.all(),
            "notices": lease.notices.all(),
            "inspections": lease.inspections.all(),
            "amendments": lease.amendments.all(),
            "renewal_form": LeaseRenewalForm(lease=lease),
            "charge_form": ManualChargeForm(),
        },
    )


@login_and_roles_required(*STAFF_ROLES)
def payment_list(request):
    payments = Payment.objects.select_related("lease__tenant", "lease__unit__property", "received_by").prefetch_related("allocations")
    method = request.GET.get("method", "")
    query = request.GET.get("q", "").strip()
    if method:
        payments = payments.filter(payment_method=method)
    if query:
        payments = payments.filter(
            Q(reference__icontains=query)
            | Q(receipt_number__icontains=query)
            | Q(lease__tenant__full_name__icontains=query)
            | Q(lease__unit__unit_number__icontains=query)
        )
    return render(
        request,
        "payments/list.html",
        {"payments": payments, "method_choices": Payment.Method.choices, "selected_method": method, "query": query},
    )


@login_and_roles_required(*FINANCE_ROLES)
def payment_create(request):
    initial = {}
    if request.GET.get("lease"):
        initial["lease"] = request.GET["lease"]
    form = PaymentForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if form.is_valid():
            payment = post_payment(cleaned_data=form.cleaned_data, actor=_actor(request), request=request)
            if payment.unallocated_amount:
                messages.warning(
                    request,
                    f"Payment posted. UGX {payment.unallocated_amount:,.0f} remains as unallocated tenant credit.",
                )
            else:
                messages.success(request, f"Payment posted and receipt {payment.receipt_number} generated.")
            return redirect("receipt_detail", pk=payment.pk)
        _form_errors(request, form)
    return render(request, "payments/form.html", {"form": form})


@login_and_roles_required(*STAFF_ROLES)
def receipt_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("lease__tenant", "lease__unit__property", "received_by").prefetch_related(
            "allocations__charge"
        ),
        pk=pk,
    )
    previous_balance = Decimal("0")
    if payment.lease:
        previous_balance = sum(
            (
                charge.amount
                - (
                    charge.allocations.filter(
                        payment__status=Payment.Status.POSTED, payment__payment_date__lt=payment.payment_date
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0")
                )
                for charge in payment.lease.rent_charges.filter(due_date__lte=payment.payment_date)
            ),
            Decimal("0"),
        )
    return render(
        request,
        "payments/receipt.html",
        {
            "payment": payment,
            "previous_balance": max(previous_balance, Decimal("0")),
            "refund_form": PaymentRefundForm(payment=payment),
            "refunds": payment.refunds.all(),
        },
    )


@login_and_roles_required(*FINANCE_ROLES)
def payment_void(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    form = VoidPaymentForm(request.POST)
    if form.is_valid():
        void_payment(payment=payment, reason=form.cleaned_data["reason"], actor=_actor(request), request=request)
        messages.success(request, f"{payment.receipt_number} was voided. The original record has been retained.")
    else:
        messages.error(request, "A clear void reason of at least five characters is required.")
    return redirect("receipt_detail", pk=payment.pk)


@login_and_roles_required(*FINANCE_ROLES)
def payment_refund(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    payment = get_object_or_404(Payment, pk=pk)
    form = PaymentRefundForm(request.POST, payment=payment)
    if form.is_valid():
        try:
            refund = refund_unallocated_payment(
                payment=payment,
                cleaned_data=form.cleaned_data,
                actor=_actor(request),
                request=request,
            )
            messages.success(request, f"Refund {refund.refund_number} was posted.")
        except ValidationError as error:
            messages.error(request, _validation_message(error))
    else:
        messages.error(request, "Refund only available unallocated credit and provide a reference and reason.")
    return redirect("receipt_detail", pk=payment.pk)


def _arrears_buckets(charges, today):
    buckets = {
        "current": {"label": "Current", "amount": Decimal("0")},
        "1_30": {"label": "1–30 days", "amount": Decimal("0")},
        "31_60": {"label": "31–60 days", "amount": Decimal("0")},
        "61_90": {"label": "61–90 days", "amount": Decimal("0")},
        "90_plus": {"label": "90+ days", "amount": Decimal("0")},
    }
    for charge in charges:
        days = max((today - charge.due_date).days, 0)
        key = "current" if days == 0 else "1_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "90_plus"
        buckets[key]["amount"] += charge.balance
    total = sum((item["amount"] for item in buckets.values()), Decimal("0"))
    for item in buckets.values():
        item["percentage"] = round(item["amount"] / total * 100) if total else 0
    return buckets


@login_and_roles_required(*STAFF_ROLES)
def arrears(request):
    today = timezone.localdate()
    charges = [
        charge
        for charge in RentCharge.objects.filter(due_date__lte=today)
        .exclude(status__in=(RentCharge.Status.PAID, RentCharge.Status.VOID))
        .select_related("lease__tenant", "lease__unit__property")
        if charge.balance > 0
    ]
    tenants = {}
    for charge in charges:
        key = charge.lease_id
        row = tenants.setdefault(
            key,
            {
                "lease": charge.lease,
                "due": Decimal("0"),
                "paid": Decimal("0"),
                "balance": Decimal("0"),
                "oldest_due": charge.due_date,
            },
        )
        row["due"] += charge.amount
        row["paid"] += charge.allocated_amount
        row["balance"] += charge.balance
        row["oldest_due"] = min(row["oldest_due"], charge.due_date)
    rows = sorted(tenants.values(), key=lambda row: (row["oldest_due"], -row["balance"]))
    total = sum((row["balance"] for row in rows), Decimal("0"))
    return render(
        request,
        "payments/arrears.html",
        {"rows": rows, "total": total, "buckets": _arrears_buckets(charges, today), "today": today},
    )


@login_and_roles_required(*OPERATIONS_ROLES)
def maintenance_list(request):
    form = MaintenanceRequestForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save()
            assign_reference(item)
            audit(actor=_actor(request), action="maintenance_created", instance=item, request=request)
            messages.success(request, f"Request {item.request_number} was created.")
            return redirect("maintenance_list")
        _form_errors(request, form)
    queryset = MaintenanceRequest.objects.select_related("unit__property", "tenant")
    status = request.GET.get("status", "")
    if status:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "maintenance/list.html",
        {"requests": queryset, "form": form, "selected_status": status, "status_choices": MaintenanceRequest.Status.choices},
    )


@login_and_roles_required(*FINANCE_ROLES)
def expense_list(request):
    form = ExpenseForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save(commit=False)
            item.approved_by = _actor(request)
            item.save()
            assign_reference(item)
            audit(actor=_actor(request), action="expense_recorded", instance=item, request=request)
            messages.success(request, f"Expense {item.expense_number} was recorded.")
            return redirect("expense_list")
        _form_errors(request, form)
    expenses = Expense.objects.select_related("property", "approved_by")
    total = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return render(request, "expenses/list.html", {"expenses": expenses, "form": form, "total": total})


@login_and_roles_required(*STAFF_ROLES)
def reports(request):
    rows = []
    for property_item in Property.objects.prefetch_related("units", "expenses"):
        income = Payment.objects.filter(
            lease__unit__property=property_item, status=Payment.Status.POSTED
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        income -= PaymentRefund.objects.filter(
            payment__lease__unit__property=property_item,
            status=PaymentRefund.Status.POSTED,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        expenses_total = property_item.expenses.filter(status="posted").aggregate(total=Sum("amount"))["total"] or Decimal("0")
        units = list(property_item.units.all())
        rows.append(
            {
                "property": property_item,
                "units": len(units),
                "occupied": sum(unit.status == Unit.Status.OCCUPIED for unit in units),
                "income": income,
                "expenses": expenses_total,
                "net": income - expenses_total,
            }
        )
    return render(request, "reports/index.html", {"rows": rows})


@login_and_roles_required(*ADMIN_ROLES)
def audit_log_list(request):
    return render(request, "audit/list.html", {"logs": AuditLog.objects.select_related("actor")[:200]})


@login_and_roles_required(*STAFF_ROLES)
def global_search(request):
    query = request.GET.get("q", "").strip()
    context = {"query": query, "properties": [], "units": [], "tenants": [], "leases": [], "payments": []}
    if query:
        context.update(
            {
                "properties": Property.objects.filter(Q(name__icontains=query) | Q(address__icontains=query))[:8],
                "units": Unit.objects.filter(Q(unit_number__icontains=query) | Q(property__name__icontains=query)).select_related("property")[:8],
                "tenants": Tenant.objects.filter(Q(full_name__icontains=query) | Q(phone__icontains=query))[:8],
                "leases": Lease.objects.filter(Q(lease_number__icontains=query) | Q(tenant__full_name__icontains=query)).select_related("tenant", "unit")[:8],
                "payments": Payment.objects.filter(Q(receipt_number__icontains=query) | Q(reference__icontains=query)).select_related("lease__tenant")[:8],
            }
        )
    return render(request, "search/results.html", context)


def _validation_message(error):
    if hasattr(error, "message_dict"):
        return " ".join(message for messages_list in error.message_dict.values() for message in messages_list)
    return " ".join(error.messages) if hasattr(error, "messages") else str(error)


@login_and_roles_required(*ADMIN_ROLES)
def portfolio_setup(request):
    forms = {
        "owner": LandlordForm(prefix="owner"),
        "building": BuildingForm(prefix="building"),
        "vendor": VendorForm(prefix="vendor"),
        "inventory": InventoryItemForm(prefix="inventory"),
    }
    if request.method == "POST":
        action = request.POST.get("_action", "")
        form_classes = {
            "owner": LandlordForm,
            "building": BuildingForm,
            "vendor": VendorForm,
            "inventory": InventoryItemForm,
        }
        form_class = form_classes.get(action)
        if not form_class:
            return HttpResponseNotAllowed(["POST"])
        form = form_class(request.POST, prefix=action)
        forms[action] = form
        if form.is_valid():
            item = form.save()
            audit(actor=_actor(request), action=f"{action}_created", instance=item, request=request)
            messages.success(request, f"{item} was saved successfully.")
            return redirect("portfolio_setup")
        _form_errors(request, form)
    return render(
        request,
        "operations/portfolio.html",
        {
            "forms": forms,
            "owners": Landlord.objects.prefetch_related("properties"),
            "buildings": Building.objects.select_related("property"),
            "vendors": Vendor.objects.all(),
            "inventory_items": InventoryItem.objects.select_related("unit__property")[:100],
        },
    )


@login_and_roles_required(*ADMIN_ROLES)
def application_list(request):
    form = RentalApplicationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save()
            assign_reference(item)
            if item.unit.status == Unit.Status.AVAILABLE:
                item.unit.status = Unit.Status.APPLICATION_PENDING
                item.unit.save(update_fields=("status", "updated_at"))
            audit(actor=_actor(request), action="application_submitted", instance=item, request=request)
            messages.success(request, f"Application {item.application_number} was submitted.")
            return redirect("application_list")
        _form_errors(request, form)
    status = request.GET.get("status", "")
    applications = RentalApplication.objects.select_related("unit__property", "tenant", "decided_by")
    if status:
        applications = applications.filter(status=status)
    return render(
        request,
        "applications/list.html",
        {
            "applications": applications,
            "form": form,
            "decision_form": ApplicationDecisionForm(),
            "status_choices": RentalApplication.Status.choices,
            "selected_status": status,
        },
    )


@login_and_roles_required(*ADMIN_ROLES)
def application_decide(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    application = get_object_or_404(RentalApplication, pk=pk)
    form = ApplicationDecisionForm(request.POST)
    if form.is_valid():
        try:
            decide_application(
                application=application,
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data.get("reason", ""),
                actor=_actor(request),
                request=request,
            )
            messages.success(request, f"{application.application_number} is now {application.get_status_display()}.")
        except ValidationError as error:
            messages.error(request, _validation_message(error))
    else:
        messages.error(request, _validation_message(ValidationError(form.errors.as_text())))
    return redirect("application_list")


@login_and_roles_required(*ADMIN_ROLES)
def lease_activate(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    lease = get_object_or_404(Lease, pk=pk)
    try:
        activate_lease(lease=lease, actor=_actor(request), request=request)
        messages.success(request, f"{lease.lease_number} is active and its billing schedule was generated.")
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    return redirect("lease_detail", pk=lease.pk)


@login_and_roles_required(*ADMIN_ROLES)
def lease_renew(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    lease = get_object_or_404(Lease, pk=pk)
    form = LeaseRenewalForm(request.POST, lease=lease)
    if form.is_valid():
        try:
            renewal = create_renewal(
                lease=lease,
                actor=_actor(request),
                request=request,
                **form.cleaned_data,
            )
            messages.success(request, f"Renewal {renewal.lease_number} was created for approval.")
            return redirect("lease_detail", pk=renewal.pk)
        except ValidationError as error:
            messages.error(request, _validation_message(error))
    else:
        messages.error(request, "Correct the renewal dates and amount.")
    return redirect("lease_detail", pk=lease.pk)


@login_and_roles_required(*ADMIN_ROLES)
def lease_close(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    lease = get_object_or_404(Lease, pk=pk)
    try:
        complete_move_out(
            lease=lease,
            actor=_actor(request),
            reason=request.POST.get("reason", "Move-out completed"),
            request=request,
        )
        messages.success(request, f"{lease.lease_number} was closed and the unit is available.")
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    return redirect("lease_detail", pk=lease.pk)


@login_and_roles_required(*FINANCE_ROLES)
def lease_charge(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    lease = get_object_or_404(Lease, pk=pk)
    form = ManualChargeForm(request.POST)
    if form.is_valid():
        try:
            post_manual_charge(
                lease=lease,
                cleaned_data=form.cleaned_data,
                actor=_actor(request),
                request=request,
            )
            messages.success(request, "The charge or credit was posted to the tenant ledger.")
        except ValidationError as error:
            messages.error(request, _validation_message(error))
    else:
        messages.error(request, "Correct the manual charge details.")
    return redirect("lease_detail", pk=lease.pk)


@login_and_roles_required(*ADMIN_ROLES)
def notice_list(request):
    form = LeaseNoticeForm(request.POST or None, initial={"lease": request.GET.get("lease")})
    if request.method == "POST":
        if form.is_valid():
            notice = form.save()
            assign_reference(notice)
            try:
                serve_lease_notice(notice=notice, actor=_actor(request), request=request)
                messages.success(request, f"Notice {notice.notice_number} was served.")
            except ValidationError as error:
                messages.error(request, _validation_message(error))
            return redirect("notice_list")
        _form_errors(request, form)
    return render(
        request,
        "leases/notices.html",
        {"notices": LeaseNotice.objects.select_related("lease__tenant", "lease__unit", "served_by"), "form": form},
    )


@login_and_roles_required(*OPERATIONS_ROLES)
def inspection_list(request):
    inspection_initial = {}
    if request.GET.get("lease"):
        linked_lease = Lease.objects.filter(pk=request.GET["lease"]).first()
        if linked_lease:
            inspection_initial = {"lease": linked_lease, "unit": linked_lease.unit}
    form = InspectionForm(request.POST or None, initial=inspection_initial)
    if request.method == "POST":
        if form.is_valid():
            item = form.save()
            assign_reference(item)
            audit(actor=_actor(request), action="inspection_scheduled", instance=item, request=request)
            messages.success(request, f"Inspection {item.inspection_number} was scheduled.")
            return redirect("inspection_detail", pk=item.pk)
        _form_errors(request, form)
    return render(
        request,
        "inspections/list.html",
        {"inspections": Inspection.objects.select_related("unit__property", "lease__tenant", "inspector"), "form": form},
    )


@login_and_roles_required(*OPERATIONS_ROLES)
def inspection_detail(request, pk):
    inspection = get_object_or_404(Inspection.objects.select_related("unit__property", "lease__tenant", "inspector"), pk=pk)
    form = InspectionItemForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save(commit=False)
            item.inspection = inspection
            item.save()
            messages.success(request, f"{item.item} was added to the checklist.")
            return redirect("inspection_detail", pk=inspection.pk)
        _form_errors(request, form)
    return render(request, "inspections/detail.html", {"inspection": inspection, "form": form})


@login_and_roles_required(*OPERATIONS_ROLES)
def inspection_complete(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    inspection = get_object_or_404(Inspection, pk=pk)
    try:
        complete_inspection(
            inspection=inspection,
            actor=_actor(request),
            acknowledged=bool(request.POST.get("acknowledged")),
            request=request,
        )
        messages.success(request, f"Inspection {inspection.inspection_number} was completed.")
    except ValidationError as error:
        messages.error(request, _validation_message(error))
    return redirect("inspection_detail", pk=inspection.pk)


@login_and_roles_required(*FINANCE_ROLES)
def deposit_list(request):
    form = SecurityDepositTransactionForm(request.POST or None, initial={"lease": request.GET.get("lease")})
    if request.method == "POST":
        if form.is_valid():
            try:
                item = post_deposit_transaction(cleaned_data=form.cleaned_data, actor=_actor(request), request=request)
                messages.success(request, f"Deposit transaction for {item.lease.lease_number} was posted.")
                return redirect("deposit_list")
            except ValidationError as error:
                messages.error(request, _validation_message(error))
        else:
            _form_errors(request, form)
    return render(
        request,
        "finance/deposits.html",
        {
            "transactions": SecurityDepositTransaction.objects.select_related("lease__tenant", "lease__unit", "posted_by"),
            "form": form,
        },
    )


@login_and_roles_required(*OPERATIONS_ROLES)
def utility_list(request):
    meter_form = UtilityMeterForm(prefix="meter")
    reading_form = UtilityReadingForm(prefix="reading")
    if request.method == "POST":
        action = request.POST.get("_action")
        if action == "meter":
            meter_form = UtilityMeterForm(request.POST, prefix="meter")
            if meter_form.is_valid():
                meter = meter_form.save()
                audit(actor=_actor(request), action="utility_meter_created", instance=meter, request=request)
                messages.success(request, f"Meter {meter.meter_number} was added.")
                return redirect("utility_list")
            _form_errors(request, meter_form)
        elif action == "reading":
            reading_form = UtilityReadingForm(request.POST, prefix="reading")
            if reading_form.is_valid():
                try:
                    reading = record_utility_reading(
                        cleaned_data=reading_form.cleaned_data,
                        actor=_actor(request),
                        request=request,
                    )
                    messages.success(request, f"Reading recorded; {reading.amount:,.0f} was added to the tenant ledger.")
                    return redirect("utility_list")
                except ValidationError as error:
                    messages.error(request, _validation_message(error))
            else:
                _form_errors(request, reading_form)
        else:
            return HttpResponseNotAllowed(["POST"])
    return render(
        request,
        "operations/utilities.html",
        {
            "meters": UtilityMeter.objects.select_related("unit__property"),
            "readings": UtilityReading.objects.select_related("meter__unit__property", "charge")[:100],
            "meter_form": meter_form,
            "reading_form": reading_form,
        },
    )


@login_and_roles_required(*STAFF_ROLES)
def document_list(request):
    form = DocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if get_user_role(request.user) not in ADMIN_ROLES:
            raise PermissionDenied("Only a manager can upload documents.")
        if form.is_valid():
            item = form.save(commit=False)
            item.uploaded_by = _actor(request)
            item.save()
            audit(actor=_actor(request), action="document_uploaded", instance=item, request=request)
            messages.success(request, f"{item.title} was uploaded.")
            return redirect("document_list")
        _form_errors(request, form)
    return render(request, "operations/documents.html", {"documents": Document.objects.select_related("uploaded_by")[:200], "form": form})


@login_and_roles_required()
def document_download(request, pk):
    item = get_object_or_404(Document, pk=pk)
    role = get_user_role(request.user)
    allowed = role in STAFF_ROLES
    if role == "tenant":
        tenant = getattr(request.user, "tenant_profile", None)
        allowed = bool(
            tenant
            and not item.is_private
            and item.object_type.lower() == "tenant"
            and item.object_id == str(tenant.pk)
        )
    elif role == "landlord":
        owner = getattr(request.user, "landlord_profile", None)
        allowed = bool(
            owner
            and not item.is_private
            and item.object_type.lower() in ("landlord", "owner")
            and item.object_id == str(owner.pk)
        )
    if not allowed:
        raise PermissionDenied("You do not have access to this document.")
    try:
        return FileResponse(item.file.open("rb"), as_attachment=False, filename=item.file.name.rsplit("/", 1)[-1])
    except FileNotFoundError as error:
        raise Http404("The document file is missing.") from error


@login_and_roles_required(*STAFF_ROLES)
def communication_list(request):
    form = CommunicationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = queue_communication(cleaned_data=form.cleaned_data, actor=_actor(request))
            label = "sent" if item.status == CommunicationLog.Status.SENT else "queued for delivery"
            messages.success(request, f"Message to {item.recipient_name} was {label}.")
            return redirect("communication_list")
        _form_errors(request, form)
    return render(
        request,
        "communications/list.html",
        {"communications": CommunicationLog.objects.select_related("created_by")[:200], "form": form},
    )


@login_and_roles_required(*FINANCE_ROLES)
def owner_statement_list(request):
    form = OwnerStatementForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                item = generate_owner_statement(cleaned_data=form.cleaned_data, actor=_actor(request), request=request)
                messages.success(request, f"Statement {item.statement_number} was generated.")
                return redirect("owner_statement_detail", pk=item.pk)
            except ValidationError as error:
                messages.error(request, _validation_message(error))
        else:
            _form_errors(request, form)
    return render(
        request,
        "accounting/statements.html",
        {"statements": OwnerStatement.objects.select_related("owner", "property", "approved_by"), "form": form},
    )


@login_and_roles_required(*FINANCE_ROLES)
def owner_statement_detail(request, pk):
    statement = get_object_or_404(OwnerStatement.objects.select_related("owner", "property", "approved_by"), pk=pk)
    return render(request, "accounting/statement_detail.html", {"statement": statement})


@login_and_roles_required(*FINANCE_ROLES)
def owner_statement_action(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    statement = get_object_or_404(OwnerStatement, pk=pk)
    action = request.POST.get("action")
    if action == "approve" and statement.status == OwnerStatement.Status.DRAFT:
        statement.status = OwnerStatement.Status.APPROVED
        statement.approved_by = _actor(request)
        statement.approved_at = timezone.now()
        fields = ("status", "approved_by", "approved_at", "updated_at")
    elif action == "pay" and statement.status == OwnerStatement.Status.APPROVED:
        reference = request.POST.get("reference", "").strip()
        if not reference:
            messages.error(request, "A payout reference is required.")
            return redirect("owner_statement_detail", pk=statement.pk)
        statement.status = OwnerStatement.Status.PAID
        statement.paid_at = timezone.now()
        statement.payout_reference = reference
        fields = ("status", "paid_at", "payout_reference", "updated_at")
    else:
        messages.error(request, "That statement action is not allowed in its current status.")
        return redirect("owner_statement_detail", pk=statement.pk)
    statement.save(update_fields=fields)
    audit(actor=_actor(request), action=f"owner_statement_{action}", instance=statement, request=request)
    messages.success(request, f"Statement {statement.statement_number} was {action}d.")
    return redirect("owner_statement_detail", pk=statement.pk)


@login_and_roles_required(*FINANCE_ROLES)
def reconciliation_list(request):
    form = PaymentReconciliationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save(commit=False)
            if item.payment_id:
                item.status = PaymentReconciliation.Status.MATCHED
                item.matched_by = _actor(request)
                item.matched_at = timezone.now()
            item.save()
            audit(actor=_actor(request), action="payment_reconciliation_imported", instance=item, request=request)
            messages.success(request, f"Transaction {item.external_reference} was imported.")
            return redirect("reconciliation_list")
        _form_errors(request, form)
    return render(
        request,
        "finance/reconciliation.html",
        {"items": PaymentReconciliation.objects.select_related("payment", "matched_by")[:200], "form": form},
    )


@login_and_roles_required(*ADMIN_ROLES)
def amendment_list(request):
    form = LeaseAmendmentForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            item = form.save()
            audit(actor=_actor(request), action="lease_amendment_created", instance=item, request=request)
            messages.success(request, "The amendment was saved as a draft.")
            return redirect("amendment_list")
        _form_errors(request, form)
    return render(
        request,
        "leases/amendments.html",
        {"amendments": LeaseAmendment.objects.select_related("lease__tenant", "approved_by"), "form": form},
    )


@login_and_roles_required(*ADMIN_ROLES)
def amendment_approve(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    amendment = get_object_or_404(LeaseAmendment, pk=pk)
    try:
        approve_amendment(amendment=amendment, actor=_actor(request), request=request)
        messages.success(request, "The amendment was approved and applied to the lease.")
    except (ValidationError, ValueError) as error:
        messages.error(request, _validation_message(error) if isinstance(error, ValidationError) else str(error))
    return redirect("amendment_list")


@login_and_roles_required(*OPERATIONS_ROLES)
def maintenance_transition(request, pk):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    item = get_object_or_404(MaintenanceRequest, pk=pk)
    target = request.POST.get("status", "")
    allowed = {
        MaintenanceRequest.Status.NEW: (MaintenanceRequest.Status.REVIEWED, MaintenanceRequest.Status.ASSIGNED),
        MaintenanceRequest.Status.REVIEWED: (MaintenanceRequest.Status.ASSIGNED,),
        MaintenanceRequest.Status.ASSIGNED: (MaintenanceRequest.Status.IN_PROGRESS,),
        MaintenanceRequest.Status.IN_PROGRESS: (MaintenanceRequest.Status.AWAITING_PARTS, MaintenanceRequest.Status.COMPLETED),
        MaintenanceRequest.Status.AWAITING_PARTS: (MaintenanceRequest.Status.IN_PROGRESS, MaintenanceRequest.Status.COMPLETED),
        MaintenanceRequest.Status.COMPLETED: (MaintenanceRequest.Status.VERIFIED,),
        MaintenanceRequest.Status.VERIFIED: (MaintenanceRequest.Status.CLOSED,),
    }
    if target not in allowed.get(item.status, ()):
        messages.error(request, "That maintenance transition is not allowed.")
        return redirect("maintenance_list")
    old = item.status
    item.status = target
    if target == MaintenanceRequest.Status.ASSIGNED:
        item.approved_by = _actor(request)
        item.approved_at = timezone.now()
    if target == MaintenanceRequest.Status.COMPLETED:
        item.completed_at = timezone.now()
        item.resolution = request.POST.get("resolution", item.resolution)
    if target == MaintenanceRequest.Status.VERIFIED:
        item.tenant_verified = True
    item.save()
    audit(
        actor=_actor(request),
        action="maintenance_status_changed",
        instance=item,
        old_value={"status": old},
        new_value={"status": target},
        request=request,
    )
    messages.success(request, f"{item.request_number} is now {item.get_status_display()}.")
    return redirect("maintenance_list")


@login_and_roles_required(*STAFF_ROLES)
def reports_export(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="rentpro-property-performance.csv"'
    writer = csv.writer(response)
    writer.writerow(("Property", "Owner", "Units", "Occupied", "Income (UGX)", "Expenses (UGX)", "Net (UGX)"))
    for property_item in Property.objects.select_related("owner").prefetch_related("units", "expenses"):
        income = Payment.objects.filter(
            lease__unit__property=property_item,
            status=Payment.Status.POSTED,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        income -= PaymentRefund.objects.filter(
            payment__lease__unit__property=property_item,
            status=PaymentRefund.Status.POSTED,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        expense_total = property_item.expenses.filter(status="posted").aggregate(total=Sum("amount"))["total"] or Decimal("0")
        units = list(property_item.units.all())
        writer.writerow(
            (
                property_item.name,
                str(property_item.owner or ""),
                len(units),
                sum(unit.status == Unit.Status.OCCUPIED for unit in units),
                income,
                expense_total,
                income - expense_total,
            )
        )
    return response


@login_and_roles_required(*STAFF_ROLES, "tenant")
def tenant_portal(request):
    tenant = getattr(request.user, "tenant_profile", None)
    if not tenant:
        raise PermissionDenied("This account is not linked to a tenant.")
    ledger, balance = _tenant_ledger(tenant)
    return render(
        request,
        "portals/tenant.html",
        {
            "tenant": tenant,
            "lease": tenant.active_lease,
            "ledger": ledger,
            "balance": max(balance, Decimal("0")),
            "maintenance_requests": tenant.maintenance_requests.select_related("unit")[:10],
            "documents": Document.objects.filter(object_type="tenant", object_id=str(tenant.pk), is_private=False),
        },
    )


@login_and_roles_required(*STAFF_ROLES, "landlord")
def landlord_portal(request):
    owner = getattr(request.user, "landlord_profile", None)
    if not owner:
        raise PermissionDenied("This account is not linked to a landlord.")
    properties = owner.properties.prefetch_related("units", "expenses")
    statements = owner.statements.filter(status__in=(OwnerStatement.Status.APPROVED, OwnerStatement.Status.PAID))
    return render(
        request,
        "portals/landlord.html",
        {"owner": owner, "properties": properties, "statements": statements},
    )


# Compatibility names retained for old bookmarks and templates.
login_view = dashboard
add_property_view = property_list
add_Unit_view = unit_list
add_Tenant_view = tenant_list
add_Payment_view = payment_list
add_MaintenanceRequest_view = maintenance_list
