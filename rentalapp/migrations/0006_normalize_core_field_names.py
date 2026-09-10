from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("rentalapp", "0005_rename_user_tenant_user_name")]

    operations = [
        migrations.RenameField(model_name="property", old_name="names", new_name="name"),
        migrations.RenameField(model_name="unit", old_name="propertyy", new_name="property"),
        migrations.RenameField(model_name="tenant", old_name="user_name", new_name="user"),
    ]
