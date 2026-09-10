#!/usr/bin/env python3
"""Create a rich, idempotent Uganda-oriented RentPro demo dataset.

All people, phone numbers, identifiers and transaction references in this file are
fictional and intended only for local development, demonstrations and tests.

Run from the project root:

    ./.venv/bin/python seed.py
"""

import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rentalproject.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from rentalapp.models import (  # noqa: E402
    Building,
    CommunicationLog,
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
    PaymentReconciliation,
    Property,
    RentalApplication,
    SecurityDepositTransaction,
    Tenant,
    Unit,
    UserProfile,
    UtilityMeter,
    UtilityReading,
    Vendor,
)
from rentalapp.services import (  # noqa: E402
    generate_owner_statement,
    generate_rent_schedule,
    post_deposit_transaction,
    post_payment,
    queue_communication,
    record_utility_reading,
)


SEED_PREFIX = "UG-SEED"
DEMO_PASSWORD = "RentProDemo2026!"


OWNERS = (
    ("Amina Nansubuga", "Kampala", "Real estate investor"),
    ("Joseph Ssemanda", "Wakiso", "Civil engineer"),
    ("Grace Akello", "Gulu", "Business owner"),
    ("Moses Okello", "Lira", "Agricultural consultant"),
    ("Sarah Namukasa", "Mukono", "Medical practitioner"),
    ("Peter Mugisha", "Mbarara", "Transport operator"),
    ("Flavia Nakaweesi", "Jinja", "Hospitality manager"),
    ("Daniel Tumwesigye", "Fort Portal", "Accountant"),
    ("Ruth Achieng", "Entebbe", "Tourism consultant"),
    ("Samuel Kato", "Masaka", "Building contractor"),
)

PROPERTIES = (
    ("Nakasero View Apartments", "Kampala", "Plot 18 Kyadondo Road, Nakasero", "apartments"),
    ("Kira Family Residences", "Wakiso", "Mamerito Road, Kira", "apartments"),
    ("Acholi Gardens", "Gulu", "Airfield Road, Bardege-Layibi", "mixed_use"),
    ("Lira City Courts", "Lira", "Obote Avenue, Lira City", "apartments"),
    ("Seeta Heights", "Mukono", "Kampala–Jinja Road, Seeta", "apartments"),
    ("Mbarara Central Arcade", "Mbarara", "Bishop Wills Street, Mbarara", "commercial"),
    ("Source Villas", "Jinja", "Kira Road, Jinja City", "villas"),
    ("Rwenzori Homes", "Kabarole", "Boma Road, Fort Portal", "apartments"),
    ("Airport View Residences", "Wakiso", "Kitoro Road, Entebbe", "mixed_use"),
    ("Masaka Hill Apartments", "Masaka", "Broadway Road, Masaka City", "apartments"),
)

TENANTS = (
    ("Brian Ssentongo", "Software developer", "Kampala"),
    ("Doreen Atim", "Procurement officer", "Gulu"),
    ("Isaac Ouma", "Secondary school teacher", "Tororo"),
    ("Mercy Nabirye", "Nurse", "Jinja"),
    ("Ronald Byaruhanga", "Banking officer", "Mbarara"),
    ("Esther Nakato", "Retail supervisor", "Mukono"),
    ("Patrick Ocen", "Electrical technician", "Lira"),
    ("Joan Asiimwe", "Legal assistant", "Kabarole"),
    ("Michael Kiggundu", "Logistics coordinator", "Wakiso"),
    ("Sharon Nampiima", "Communications officer", "Masaka"),
)

PIPELINE_APPLICANTS = (
    ("Kevin Mugerwa", "Sales representative"),
    ("Immaculate Aber", "Laboratory technician"),
    ("Andrew Wanyama", "Restaurant manager"),
    ("Lydia Nambooze", "Human resources officer"),
    ("Martin Ekwang", "Surveyor"),
    ("Rebecca Nakitende", "Pharmacist"),
    ("Denis Turyasingura", "Insurance agent"),
    ("Catherine Apio", "Social worker"),
    ("Godfrey Baluku", "Mechanic"),
    ("Priscilla Namara", "University administrator"),
)

VENDORS = (
    ("Kampala Home Fixers", "maintenance", "Robert Lule"),
    ("Nile Flow Plumbing", "plumbing", "Stella Anyango"),
    ("SafeSpark Electricals", "electrical", "Julius Wasswa"),
    ("Pearl Cleaning Services", "cleaning", "Norah Nambasa"),
    ("Secure Uganda Services", "security", "David Komakech"),
    ("Rwenzori Property Works", "maintenance", "Edgar Atuhaire"),
    ("Eastern Region Plumbers", "plumbing", "James Waiswa"),
    ("Citywide Electricians", "electrical", "Mariam Nakintu"),
    ("Victoria Grounds Care", "cleaning", "Stephen Kalyango"),
    ("West Nile General Supplies", "other", "Agnes Draku"),
)

MAINTENANCE_JOBS = (
    ("Leaking kitchen tap", "plumbing", "Replace worn tap cartridge and inspect the sink trap."),
    ("Bedroom socket not working", "electrical", "Test the circuit and replace the damaged socket."),
    ("Blocked bathroom drain", "plumbing", "Clear blockage and confirm normal drainage."),
    ("Peeling sitting-room paint", "repairs", "Prepare the wall and repaint the affected section."),
    ("Security light replacement", "electrical", "Replace the external security light fitting."),
    ("Loose wardrobe hinge", "repairs", "Replace hinge screws and realign the wardrobe door."),
    ("Water pressure is low", "plumbing", "Inspect valves and supply line for restricted flow."),
    ("Window latch damaged", "repairs", "Fit a new latch and test the window lock."),
    ("Common corridor cleaning", "cleaning", "Deep-clean corridor and remove accumulated dust."),
    ("Intercom bell fault", "electrical", "Trace the intercom bell fault and restore service."),
)


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def aware_at(value, hour=9):
    return timezone.make_aware(datetime.combine(value, time(hour=hour)))


def ensure_user(username, full_name, email, role, phone, *, is_staff=False, is_superuser=False):
    User = get_user_model()
    first_name, _, last_name = full_name.partition(" ")
    user, _ = User.objects.update_or_create(
        username=username,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "is_active": True,
            "is_staff": is_staff or is_superuser,
            "is_superuser": is_superuser,
        },
    )
    user.set_password(DEMO_PASSWORD)
    user.save(update_fields=("password",))
    UserProfile.objects.update_or_create(
        user=user,
        defaults={
            "role": role,
            "phone": phone,
            "job_title": dict(UserProfile.Role.choices).get(role, "RentPro user"),
            "is_active": True,
        },
    )
    return user


@transaction.atomic
def seed():
    today = timezone.localdate()
    current_period = today.replace(day=1)
    lease_start = add_months(current_period, -5)
    lease_end = add_months(lease_start, 12) - timedelta(days=1)
    payment_date = current_period + timedelta(days=min(7, max(today.day - 1, 0)))

    administrator = ensure_user(
        "rentpro_admin",
        "RentPro Administrator",
        "admin@rentpro.demo.ug",
        UserProfile.Role.ADMINISTRATOR,
        "+256700990000",
        is_superuser=True,
    )
    manager = ensure_user(
        "rentpro_manager",
        "Harriet Nalubega",
        "manager@rentpro.demo.ug",
        UserProfile.Role.MANAGER,
        "+256700990101",
        is_staff=True,
    )
    accountant = ensure_user(
        "rentpro_accounts",
        "Allan Kizito",
        "accounts@rentpro.demo.ug",
        UserProfile.Role.ACCOUNTANT,
        "+256700990102",
        is_staff=True,
    )
    maintenance_officer = ensure_user(
        "rentpro_maintenance",
        "Beatrice Auma",
        "maintenance@rentpro.demo.ug",
        UserProfile.Role.MAINTENANCE,
        "+256700990103",
        is_staff=True,
    )

    vendors = []
    for index, (name, category, contact) in enumerate(VENDORS, start=1):
        vendor, _ = Vendor.objects.update_or_create(
            name=name,
            defaults={
                "category": category,
                "contact_person": contact,
                "phone": f"+25675088{index:04d}",
                "email": f"vendor{index:02d}@rentpro.demo.ug",
                "tax_id": f"TIN-DEMO-{index:06d}",
                "address": f"Service office {index}, Uganda",
                "bank_details": "Demo settlement account — not for real transfers",
                "is_active": True,
            },
        )
        vendors.append(vendor)

    owners = []
    properties = []
    buildings = []
    occupied_units = []
    spare_units = []

    for index, ((owner_name, owner_district, occupation), property_data) in enumerate(
        zip(OWNERS, PROPERTIES), start=1
    ):
        owner_user = ensure_user(
            f"ug_owner_{index:02d}",
            owner_name,
            f"owner{index:02d}@rentpro.demo.ug",
            UserProfile.Role.LANDLORD,
            f"+25677288{index:04d}",
        )
        owner, _ = Landlord.objects.update_or_create(
            user=owner_user,
            defaults={
                "full_name": owner_name,
                "phone": f"+25677288{index:04d}",
                "national_id": f"CM90{index:010d}",
                "address": f"{owner_district}, Uganda",
                "email": owner_user.email,
                "occupation": occupation,
                "tax_id": f"UG-TIN-DEMO-{index:05d}",
                "management_fee_rate": Decimal(str(6 + index % 5)),
                "payout_method": (
                    Landlord.PayoutMethod.BANK
                    if index % 3
                    else Landlord.PayoutMethod.MTN_MOMO
                ),
                "payout_phone": f"+25677288{index:04d}",
                "bank_name": "Demo Bank Uganda",
                "bank_account_name": owner_name,
                "bank_account_number": f"DEMO-AC-{index:08d}",
            },
        )
        owners.append(owner)

        property_name, district, address, property_type = property_data
        property_item, _ = Property.objects.update_or_create(
            code=f"UGP-{index:03d}",
            defaults={
                "owner": owner,
                "name": property_name,
                "address": address,
                "district": district,
                "property_type": property_type,
                "description": f"Fictional demonstration property in {district}, Uganda.",
                "total_units": 2,
                "status": "active",
            },
        )
        properties.append(property_item)

        building, _ = Building.objects.update_or_create(
            property=property_item,
            name="Main Block",
            defaults={"floors": 3 if property_type == "apartments" else 2, "notes": "Demo building"},
        )
        buildings.append(building)

        base_rent = Decimal(550_000 + index * 85_000)
        primary_unit, _ = Unit.objects.update_or_create(
            property=property_item,
            unit_number=f"A-{index:02d}",
            defaults={
                "building": building,
                "floor": str((index - 1) % 3 + 1),
                "unit_type": "office" if property_type == "commercial" else "apartment",
                "bedrooms": 2 if property_type != "commercial" else 0,
                "bathrooms": 2 if index % 2 else 1,
                "rent_amount": base_rent,
                "service_charge": Decimal(75_000 + index * 5_000),
                "status": Unit.Status.OCCUPIED,
                "notes": "Primary occupied demonstration unit",
            },
        )
        occupied_units.append(primary_unit)

        spare_unit, _ = Unit.objects.update_or_create(
            property=property_item,
            unit_number=f"B-{index:02d}",
            defaults={
                "building": building,
                "floor": str((index - 1) % 3 + 1),
                "unit_type": "shop" if property_type in ("commercial", "mixed_use") else "apartment",
                "bedrooms": 1 if property_type != "commercial" else 0,
                "bathrooms": 1,
                "rent_amount": base_rent - Decimal("100000"),
                "service_charge": Decimal(50_000 + index * 5_000),
                "status": Unit.Status.APPLICATION_PENDING if index <= 7 else Unit.Status.AVAILABLE,
                "notes": "Vacancy used by the application pipeline",
            },
        )
        spare_units.append(spare_unit)

        for inventory_index, inventory_name in enumerate(("Prepaid electricity meter", "Water meter"), start=1):
            InventoryItem.objects.update_or_create(
                unit=primary_unit,
                name=inventory_name,
                serial_number=f"UG-DEMO-{index:02d}-{inventory_index}",
                defaults={
                    "quantity": 1,
                    "condition": InspectionItem.Condition.GOOD,
                    "replacement_value": Decimal(180_000 + inventory_index * 70_000),
                    "notes": "Recorded during the demonstration move-in inspection.",
                },
            )

    tenants = []
    applications = []
    leases = []
    payments = []

    for index, (tenant_name, employer, home_district) in enumerate(TENANTS, start=1):
        tenant_user = ensure_user(
            f"ug_tenant_{index:02d}",
            tenant_name,
            f"tenant{index:02d}@rentpro.demo.ug",
            UserProfile.Role.TENANT,
            f"+25670077{index:04d}",
        )
        tenant, _ = Tenant.objects.update_or_create(
            user=tenant_user,
            defaults={
                "full_name": tenant_name,
                "phone": f"+25670077{index:04d}",
                "alternative_phone": f"+25678066{index:04d}",
                "email": tenant_user.email,
                "nationality": "Ugandan",
                "national_id": f"C{'F' if index % 2 == 0 else 'M'}91{index:010d}",
                "emergency_contact": f"Demo emergency contact {index}",
                "emergency_phone": f"+25675055{index:04d}",
                "status": Tenant.Status.ACTIVE,
            },
        )
        tenants.append(tenant)

        application, _ = RentalApplication.objects.update_or_create(
            application_number=f"UG-APP-{index:03d}",
            defaults={
                "unit": occupied_units[index - 1],
                "applicant_name": tenant_name,
                "phone": tenant.phone,
                "email": tenant.email,
                "national_id": tenant.national_id,
                "current_address": f"Previous residence, {home_district}",
                "employer": employer,
                "monthly_income": occupied_units[index - 1].rent_amount * Decimal("4.5"),
                "requested_move_in": lease_start,
                "occupants": 1 + index % 4,
                "guarantor_name": f"Demo guarantor {index}",
                "guarantor_phone": f"+25676044{index:04d}",
                "status": RentalApplication.Status.CONVERTED,
                "screening_notes": "Identity, employment and reference checks completed for demo data.",
                "decision_reason": "Approved for demonstration",
                "decided_at": aware_at(lease_start - timedelta(days=14)),
                "decided_by": manager,
                "tenant": tenant,
            },
        )
        applications.append(application)

        lease, _ = Lease.objects.update_or_create(
            lease_number=f"UG-LS-{index:03d}",
            defaults={
                "tenant": tenant,
                "unit": occupied_units[index - 1],
                "start_date": lease_start,
                "end_date": lease_end,
                "rent_amount": occupied_units[index - 1].rent_amount,
                "billing_frequency": "monthly",
                "due_day": 5,
                "security_deposit_required": occupied_units[index - 1].rent_amount,
                "security_deposit_received": Decimal("0"),
                "notice_period_days": 60,
                "status": Lease.Status.ACTIVE,
                "application": application,
                "signed_at": aware_at(lease_start - timedelta(days=2)),
                "activated_at": aware_at(lease_start),
                "notes": "Uganda demonstration tenancy; not a legal agreement.",
            },
        )
        leases.append(lease)

        inspection, _ = Inspection.objects.update_or_create(
            inspection_number=f"UG-IN-{index:03d}",
            defaults={
                "unit": lease.unit,
                "lease": lease,
                "inspection_type": Inspection.InspectionType.MOVE_IN,
                "scheduled_for": aware_at(lease_start - timedelta(days=1)),
                "completed_at": aware_at(lease_start - timedelta(days=1), 11),
                "inspector": maintenance_officer,
                "status": Inspection.Status.ACKNOWLEDGED,
                "electricity_reading": Decimal(index * 10),
                "water_reading": Decimal(index * 3),
                "keys_issued": 2,
                "tenant_acknowledged": True,
                "notes": "Move-in condition accepted by the demo tenant.",
            },
        )
        for area, item_name in (("Living room", "Walls and floor"), ("Kitchen", "Sink and cabinets")):
            InspectionItem.objects.update_or_create(
                inspection=inspection,
                area=area,
                item=item_name,
                defaults={
                    "condition": InspectionItem.Condition.GOOD,
                    "notes": "Clean and serviceable at move-in.",
                    "estimated_damage_cost": Decimal("0"),
                },
            )

        generate_rent_schedule(lease)
        lease.unit.status = Unit.Status.OCCUPIED
        lease.unit.save(update_fields=("status", "updated_at"))

        if not SecurityDepositTransaction.objects.filter(
            lease=lease, reference=f"UG-DEPOSIT-{index:03d}"
        ).exists():
            post_deposit_transaction(
                cleaned_data={
                    "lease": lease,
                    "transaction_type": SecurityDepositTransaction.TransactionType.RECEIPT,
                    "amount": lease.security_deposit_required,
                    "transaction_date": lease.start_date,
                    "reference": f"UG-DEPOSIT-{index:03d}",
                    "reason": "Security deposit received at move-in.",
                },
                actor=accountant,
            )

        payment_reference = f"UG-MOMO-{index:06d}"
        payment = Payment.objects.filter(reference=payment_reference).first()
        if not payment:
            methods = (Payment.Method.MTN_MOMO, Payment.Method.AIRTEL_MONEY, Payment.Method.BANK)
            payment = post_payment(
                cleaned_data={
                    "lease": lease,
                    "amount": (lease.rent_amount + lease.unit.service_charge) * Decimal(1 + index % 3),
                    "payment_date": payment_date,
                    "payment_method": methods[(index - 1) % len(methods)],
                    "reference": payment_reference,
                    "notes": "Fictional Uganda demonstration payment.",
                },
                actor=accountant,
            )
        payments.append(payment)

        meter, _ = UtilityMeter.objects.update_or_create(
            unit=lease.unit,
            utility_type=UtilityMeter.UtilityType.WATER,
            meter_number=f"NWSC-DEMO-{index:04d}",
            defaults={
                "unit_rate": Decimal(3_600 + index * 75),
                "standing_charge": Decimal("2500"),
                "is_active": True,
            },
        )
        if not UtilityReading.objects.filter(meter=meter).exists():
            record_utility_reading(
                cleaned_data={
                    "meter": meter,
                    "reading_date": payment_date,
                    "reading": Decimal(8 + index * 2),
                    "notes": "Fictional verified NWSC-style meter reading.",
                },
                actor=maintenance_officer,
            )

        PaymentReconciliation.objects.update_or_create(
            provider=payment.payment_method,
            external_reference=payment.reference,
            defaults={
                "transaction_date": payment.payment_date,
                "amount": payment.amount,
                "payer": tenant_name,
                "raw_data": {"source": "seed.py", "demo": True},
                "payment": payment,
                "status": PaymentReconciliation.Status.MATCHED,
                "matched_by": accountant,
                "matched_at": timezone.now(),
            },
        )

        LeaseNotice.objects.update_or_create(
            notice_number=f"UG-NT-{index:03d}",
            defaults={
                "lease": lease,
                "notice_type": LeaseNotice.NoticeType.RENEWAL_OFFER,
                "notice_date": lease.end_date - timedelta(days=90),
                "effective_date": lease.end_date,
                "reason": "Draft renewal discussion for demonstration.",
                "status": LeaseNotice.Status.DRAFT,
            },
        )
        LeaseAmendment.objects.update_or_create(
            lease=lease,
            amendment_type=LeaseAmendment.AmendmentType.RENT_CHANGE,
            effective_date=add_months(current_period, 2),
            defaults={
                "old_value": {"rent_amount": str(lease.rent_amount)},
                "new_value": {"rent_amount": str(lease.rent_amount + Decimal("50000"))},
                "reason": "Draft annual rent review example.",
                "status": LeaseAmendment.Status.DRAFT,
            },
        )

    pipeline_statuses = (
        RentalApplication.Status.SUBMITTED,
        RentalApplication.Status.SUBMITTED,
        RentalApplication.Status.SUBMITTED,
        RentalApplication.Status.SUBMITTED,
        RentalApplication.Status.SCREENING,
        RentalApplication.Status.SCREENING,
        RentalApplication.Status.SCREENING,
        RentalApplication.Status.REJECTED,
        RentalApplication.Status.REJECTED,
        RentalApplication.Status.REJECTED,
    )
    for index, ((applicant_name, employer), unit, status) in enumerate(
        zip(PIPELINE_APPLICANTS, spare_units, pipeline_statuses), start=1
    ):
        RentalApplication.objects.update_or_create(
            application_number=f"UG-PIPE-{index:03d}",
            defaults={
                "unit": unit,
                "applicant_name": applicant_name,
                "phone": f"+25674033{index:04d}",
                "email": f"applicant{index:02d}@rentpro.demo.ug",
                "national_id": f"CM92{index:010d}",
                "current_address": f"Current residence {index}, Uganda",
                "employer": employer,
                "monthly_income": unit.rent_amount * Decimal("3.5"),
                "requested_move_in": add_months(current_period, 1),
                "occupants": 1 + index % 3,
                "guarantor_name": f"Pipeline guarantor {index}",
                "guarantor_phone": f"+25679022{index:04d}",
                "status": status,
                "screening_notes": "Awaiting completion of fictional screening checks.",
                "decision_reason": "Income threshold not met in this demonstration."
                if status == RentalApplication.Status.REJECTED
                else "",
                "decided_at": timezone.now() if status == RentalApplication.Status.REJECTED else None,
                "decided_by": manager if status == RentalApplication.Status.REJECTED else None,
            },
        )

    maintenance_statuses = (
        MaintenanceRequest.Status.NEW,
        MaintenanceRequest.Status.REVIEWED,
        MaintenanceRequest.Status.ASSIGNED,
        MaintenanceRequest.Status.IN_PROGRESS,
        MaintenanceRequest.Status.AWAITING_PARTS,
        MaintenanceRequest.Status.COMPLETED,
        MaintenanceRequest.Status.VERIFIED,
        MaintenanceRequest.Status.CLOSED,
        MaintenanceRequest.Status.ASSIGNED,
        MaintenanceRequest.Status.IN_PROGRESS,
    )
    priorities = (
        MaintenanceRequest.Priority.URGENT,
        MaintenanceRequest.Priority.HIGH,
        MaintenanceRequest.Priority.MEDIUM,
        MaintenanceRequest.Priority.LOW,
    )
    for index, ((title, category, description), status) in enumerate(
        zip(MAINTENANCE_JOBS, maintenance_statuses), start=1
    ):
        is_assigned = status not in (MaintenanceRequest.Status.NEW, MaintenanceRequest.Status.REVIEWED)
        is_complete = status in (
            MaintenanceRequest.Status.COMPLETED,
            MaintenanceRequest.Status.VERIFIED,
            MaintenanceRequest.Status.CLOSED,
        )
        MaintenanceRequest.objects.update_or_create(
            request_number=f"UG-MR-{index:03d}",
            defaults={
                "tenant": tenants[index - 1],
                "unit": occupied_units[index - 1],
                "category": category,
                "title": title,
                "description": description,
                "priority": priorities[(index - 1) % len(priorities)],
                "status": status,
                "assigned_to": vendors[index - 1].name if is_assigned else "",
                "assigned_user": maintenance_officer if is_assigned else None,
                "vendor": vendors[index - 1] if is_assigned else None,
                "scheduled_for": timezone.now() + timedelta(days=index),
                "estimated_cost": Decimal(80_000 + index * 25_000),
                "quoted_cost": Decimal(75_000 + index * 25_000),
                "actual_cost": Decimal(70_000 + index * 25_000) if is_complete else Decimal("0"),
                "approved_by": manager if is_assigned else None,
                "approved_at": timezone.now() if is_assigned else None,
                "resolution": "Work completed and checked." if is_complete else "",
                "tenant_verified": status in (MaintenanceRequest.Status.VERIFIED, MaintenanceRequest.Status.CLOSED),
                "completed_at": timezone.now() if is_complete else None,
            },
        )

        Expense.objects.update_or_create(
            expense_number=f"UG-EX-{index:03d}",
            defaults={
                "property": properties[index - 1],
                "category": "repairs" if index % 2 else "utilities",
                "supplier": vendors[index - 1].name,
                "vendor": vendors[index - 1],
                "description": f"{title} — demonstration expense",
                "amount": Decimal(95_000 + index * 30_000),
                "expense_date": payment_date,
                "payment_method": Payment.Method.BANK,
                "reference": f"UG-EXP-PAY-{index:04d}",
                "status": "posted",
                "void_reason": "",
                "approved_by": manager,
            },
        )

        communication_reference = f"UG-COMM-{index:03d}"
        if not CommunicationLog.objects.filter(external_reference=communication_reference).exists():
            communication = queue_communication(
                cleaned_data={
                    "channel": "sms",
                    "recipient_name": tenants[index - 1].full_name,
                    "recipient_address": tenants[index - 1].phone,
                    "subject": "RentPro account update",
                    "message": (
                        f"Hello {tenants[index - 1].full_name}, this is a fictional RentPro "
                        "demonstration message about your tenancy account."
                    ),
                    "status": CommunicationLog.Status.QUEUED,
                    "external_reference": communication_reference,
                },
                actor=manager,
                related=leases[index - 1],
            )
            communication.external_reference = communication_reference
            communication.save(update_fields=("external_reference", "updated_at"))

        statement_number = f"UG-OS-{index:03d}"
        if not OwnerStatement.objects.filter(statement_number=statement_number).exists():
            statement = generate_owner_statement(
                cleaned_data={
                    "owner": owners[index - 1],
                    "property": properties[index - 1],
                    "period_start": current_period,
                    "period_end": today,
                    "other_income": Decimal("0"),
                    "notes": "Fictional monthly owner statement generated by seed.py.",
                },
                actor=accountant,
            )
            statement.statement_number = statement_number
            statement.status = OwnerStatement.Status.APPROVED if index <= 5 else OwnerStatement.Status.DRAFT
            statement.approved_by = accountant if index <= 5 else None
            statement.approved_at = timezone.now() if index <= 5 else None
            statement.save(
                update_fields=("statement_number", "status", "approved_by", "approved_at", "updated_at")
            )

    counts = {
        "staff demo accounts": 4,
        "landlords": Landlord.objects.filter(user__username__startswith="ug_owner_").count(),
        "properties": Property.objects.filter(code__startswith="UGP-").count(),
        "buildings": Building.objects.filter(property__code__startswith="UGP-").count(),
        "units": Unit.objects.filter(property__code__startswith="UGP-").count(),
        "vendors": Vendor.objects.filter(email__endswith="@rentpro.demo.ug").count(),
        "tenants": Tenant.objects.filter(user__username__startswith="ug_tenant_").count(),
        "applications": RentalApplication.objects.filter(application_number__startswith="UG-").count(),
        "leases": Lease.objects.filter(lease_number__startswith="UG-LS-").count(),
        "inspections": Inspection.objects.filter(inspection_number__startswith="UG-IN-").count(),
        "deposit transactions": SecurityDepositTransaction.objects.filter(reference__startswith="UG-DEPOSIT-").count(),
        "payments": Payment.objects.filter(reference__startswith="UG-MOMO-").count(),
        "utility readings": UtilityReading.objects.filter(meter__meter_number__startswith="NWSC-DEMO-").count(),
        "reconciliations": PaymentReconciliation.objects.filter(external_reference__startswith="UG-MOMO-").count(),
        "maintenance requests": MaintenanceRequest.objects.filter(request_number__startswith="UG-MR-").count(),
        "expenses": Expense.objects.filter(expense_number__startswith="UG-EX-").count(),
        "owner statements": OwnerStatement.objects.filter(statement_number__startswith="UG-OS-").count(),
        "communications": CommunicationLog.objects.filter(external_reference__startswith="UG-COMM-").count(),
    }
    return counts


def main():
    counts = seed()
    print("\nRentPro Uganda demo data is ready (all identities are fictional).")
    print("-" * 68)
    for label, count in counts.items():
        print(f"{label:<30} {count:>5}")
    print("-" * 68)
    print("Demo administrator: rentpro_admin")
    print("Demo manager:       rentpro_manager")
    print(f"Demo password:      {DEMO_PASSWORD}")
    print("Change or remove demo credentials before any non-local deployment.\n")


if __name__ == "__main__":
    main()
