from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Landlord, Tenant, UserProfile


@receiver(post_save, sender=get_user_model())
def create_rental_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=Landlord)
def mark_landlord_role(sender, instance, **kwargs):
    if instance.user_id:
        profile, _ = UserProfile.objects.get_or_create(user=instance.user)
        if profile.role == UserProfile.Role.VIEWER:
            profile.role = UserProfile.Role.LANDLORD
            profile.save(update_fields=("role", "updated_at"))


@receiver(post_save, sender=Tenant)
def mark_tenant_role(sender, instance, **kwargs):
    if instance.user_id:
        profile, _ = UserProfile.objects.get_or_create(user=instance.user)
        if profile.role == UserProfile.Role.VIEWER:
            profile.role = UserProfile.Role.TENANT
            profile.save(update_fields=("role", "updated_at"))
