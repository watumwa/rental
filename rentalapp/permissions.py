from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import UserProfile


ADMIN_ROLES = (UserProfile.Role.ADMINISTRATOR, UserProfile.Role.MANAGER)
FINANCE_ROLES = ADMIN_ROLES + (UserProfile.Role.ACCOUNTANT,)
OPERATIONS_ROLES = ADMIN_ROLES + (UserProfile.Role.MAINTENANCE,)
STAFF_ROLES = FINANCE_ROLES + (UserProfile.Role.MAINTENANCE,)


def get_user_role(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return UserProfile.Role.ADMINISTRATOR
    profile = getattr(user, "rental_profile", None)
    if not profile or not profile.is_active:
        return UserProfile.Role.VIEWER
    return profile.role


def user_has_role(user, roles):
    return get_user_role(user) in roles


def login_and_roles_required(*roles, write_only=False):
    """Require login for every request and selected roles for protected actions."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            should_check = not write_only or request.method not in ("GET", "HEAD", "OPTIONS")
            if roles and should_check and not user_has_role(request.user, roles):
                raise PermissionDenied("Your role does not allow this action.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
