from django.db.models import Q
from django.urls import reverse

from .models import Notification
from .permissions import STAFF_ROLES, get_user_role


def workspace_context(request):
    if not request.user.is_authenticated:
        return {
            "workspace_notifications": (),
            "workspace_notification_count": 0,
            "workspace_role": None,
            "workspace_home_url": reverse("home"),
        }

    notifications = Notification.objects.filter(is_read=False)
    notifications = notifications.filter(Q(user=request.user) | Q(user__isnull=True))
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
