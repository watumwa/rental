from django.db.models import Q
from django.urls import reverse

from .models import Notification
from .permissions import STAFF_ROLES, get_user_role


def workspace_context(request):
    notifications = Notification.objects.filter(is_read=False)
    if request.user.is_authenticated:
        notifications = notifications.filter(Q(user=request.user) | Q(user__isnull=True))
    else:
        notifications = notifications.filter(user__isnull=True)
    role = get_user_role(request.user)
    if role == "tenant":
        home_url = reverse("tenant_portal")
    elif role == "landlord":
        home_url = reverse("landlord_portal")
    elif role in STAFF_ROLES:
        home_url = reverse("dashboard")
    else:
        home_url = reverse("home")
    return {
        "workspace_notifications": notifications[:5],
        "workspace_notification_count": notifications.count(),
        "workspace_role": role,
        "workspace_home_url": home_url,
    }
