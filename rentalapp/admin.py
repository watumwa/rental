from django.contrib import admin

from .models import (
    AuditLog,
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
    MessageTemplate,
    Notification,
    OwnerStatement,
    Payment,
    PaymentAllocation,
    PaymentReconciliation,
    PaymentRefund,
    Property,
    Receipt,
    RentalApplication,
    RentCharge,
    SecurityDepositTransaction,
    Tenant,
    Unit,
    UserProfile,
    UtilityMeter,
    UtilityReading,
    Vendor,
)


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "property_type", "status", "owner")
    list_filter = ("status", "property_type", "district")
    search_fields = ("name", "code", "address")


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("unit_number", "property", "unit_type", "rent_amount", "status")
    list_filter = ("status", "unit_type", "property")
    search_fields = ("unit_number", "property__name")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "national_id", "status")
    list_filter = ("status",)
    search_fields = ("full_name", "phone", "national_id")


class RentChargeInline(admin.TabularInline):
    model = RentCharge
    extra = 0
    readonly_fields = ("period", "due_date", "description", "amount", "charge_type", "status")
    can_delete = False


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ("lease_number", "tenant", "unit", "start_date", "end_date", "rent_amount", "status")
    list_filter = ("status", "billing_frequency")
    search_fields = ("lease_number", "tenant__full_name", "unit__unit_number")
    inlines = (RentChargeInline,)


class AllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    readonly_fields = ("charge", "amount", "created_at")
    can_delete = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "lease", "payment_date", "amount", "payment_method", "status")
    list_filter = ("status", "payment_method", "payment_date")
    search_fields = ("receipt_number", "reference", "lease__tenant__full_name")
    inlines = (AllocationInline,)
    readonly_fields = ("receipt_number", "status", "void_reason", "voided_at", "voided_by")

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (
                "lease",
                "amount",
                "payment_date",
                "payment_method",
                "reference",
                "receipt_number",
                "status",
                "received_by",
                "void_reason",
                "voided_at",
                "voided_by",
            )
        return self.readonly_fields


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("number", "payment", "issued_at")
    readonly_fields = ("payment", "number", "issued_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Building)
admin.site.register(Landlord)
admin.site.register(MaintenanceRequest)
admin.site.register(Expense)
admin.site.register(Notification)
admin.site.register(AuditLog)
admin.site.register(UserProfile)
admin.site.register(Vendor)
admin.site.register(RentalApplication)
admin.site.register(LeaseNotice)
admin.site.register(LeaseAmendment)
admin.site.register(Inspection)
admin.site.register(InspectionItem)
admin.site.register(InventoryItem)
admin.site.register(UtilityMeter)
admin.site.register(UtilityReading)
admin.site.register(Document)
admin.site.register(MessageTemplate)
admin.site.register(CommunicationLog)
admin.site.register(PaymentReconciliation)
admin.site.register(OwnerStatement)


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = ("refund_number", "payment", "refund_date", "amount", "status")
    readonly_fields = ("payment", "refund_number", "amount", "refund_date", "reference", "reason", "status", "posted_by")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SecurityDepositTransaction)
class SecurityDepositTransactionAdmin(admin.ModelAdmin):
    list_display = ("lease", "transaction_type", "transaction_date", "amount", "status")
    list_filter = ("transaction_type", "status", "transaction_date")
    search_fields = ("lease__lease_number", "lease__tenant__full_name", "reference")

    def has_delete_permission(self, request, obj=None):
        return False
