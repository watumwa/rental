from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def ugx(value):
    try:
        number = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return "UGX 0"
    return f"UGX {number:,.0f}"


@register.filter
def status_class(value):
    value = str(value or "").lower()
    if value in {"active", "paid", "posted", "completed", "verified", "closed", "available", "success"}:
        return "success"
    if value in {"partial", "partially paid", "in_progress", "in progress", "assigned", "info", "reserved"}:
        return "info"
    if value in {"pending", "pending approval", "new", "expiring", "expiring soon", "notice_given", "warning"}:
        return "warning"
    if value in {"overdue", "void", "terminated", "expired", "blocked", "urgent", "danger"}:
        return "danger"
    if value in {"maintenance", "under maintenance", "awaiting_parts", "awaiting parts", "high"}:
        return "orange"
    return "neutral"


@register.filter
def initials(value):
    words = str(value or "R").split()
    return "".join(word[0] for word in words[:2]).upper()
