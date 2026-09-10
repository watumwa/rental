from django.conf import settings
from django.db import migrations


def backfill_workflow_data(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    UserProfile = apps.get_model("rentalapp", "UserProfile")
    Lease = apps.get_model("rentalapp", "Lease")
    SecurityDepositTransaction = apps.get_model("rentalapp", "SecurityDepositTransaction")

    for user in User.objects.all().iterator():
        UserProfile.objects.get_or_create(user=user, defaults={"role": "manager"})

    for lease in Lease.objects.filter(security_deposit_received__gt=0).iterator():
        SecurityDepositTransaction.objects.get_or_create(
            lease=lease,
            transaction_type="adjustment_in",
            reference="Opening balance",
            defaults={
                "amount": lease.security_deposit_received,
                "transaction_date": lease.start_date,
                "reason": "Deposit balance migrated from the original lease record.",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("rentalapp", "0009_communicationlog_document_inspection_inspectionitem_and_more")]

    operations = [migrations.RunPython(backfill_workflow_data, migrations.RunPython.noop)]
