"""
Obsidian Multi-Tenant Permission & Authorization Layer
Enforces cross-contest role isolation, organizer access gates, and competitor role constraints.
"""

from functools import wraps
from typing import Optional, Callable, Any
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from home.models import Contest, ContestParticipation, OrganizationMembership


def is_contest_staff(user: Optional[User], contest: Contest) -> bool:
    """
    Checks if a user has staff, host, judge, or org administrative privileges for a given contest.
    Staff members are exempt from anti-cheat proctoring strikes and can view administrative views.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or user.is_staff:
        return True

    # Legacy or explicit contest host field
    if contest.host_id is not None and contest.host_id == user.id:
        return True

    # Contextual role inside this specific contest
    if contest.participations.filter(user=user, role__in=['HOST', 'JUDGE']).exists():
        return True

    # Organization-level administrative ownership
    if contest.organization_id:
        if contest.organization.memberships.filter(
            user=user, role__in=['OWNER', 'ADMIN'], is_active=True
        ).exists():
            return True

    return False


def can_manage_contest(user: Optional[User], contest: Contest) -> bool:
    """
    Checks if a user has management permissions (edit, unban, restart, configure) for a contest.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if contest.host_id is not None and contest.host_id == user.id:
        return True

    if contest.participations.filter(user=user, role='HOST').exists():
        return True

    if contest.organization_id:
        if contest.organization.memberships.filter(
            user=user, role__in=['OWNER', 'ADMIN'], is_active=True
        ).exists():
            return True

    return False


def can_compete_in_contest(user: Optional[User], contest: Contest) -> bool:
    """
    Checks if a user is eligible to submit contestant code solutions in a contest.
    Enforces that hosts and judges cannot submit contestant solutions in their own contests.
    Platform superusers/staff retain test-mode bypass unless explicitly registered as HOST/JUDGE in ContestParticipation.
    """
    if not user or not user.is_authenticated:
        return False

    # Explicit participation with HOST or JUDGE role always denies competitor status
    if contest.participations.filter(user=user, role__in=['HOST', 'JUDGE']).exists():
        return False

    # Legacy host check: Superuser/staff retain test-mode bypass unless explicitly registered as HOST
    if contest.host_id is not None and contest.host_id == user.id:
        if not (user.is_superuser or user.is_staff):
            return False

    # Organization owner/admin check: Superuser/staff retain bypass
    if contest.organization_id:
        if contest.organization.memberships.filter(
            user=user, role__in=['OWNER', 'ADMIN'], is_active=True
        ).exists():
            if not (user.is_superuser or user.is_staff):
                return False

    return True


def contest_staff_required(view_func: Callable) -> Callable:
    """
    Decorator requiring the authenticated user to be contest staff or organizer.
    """
    @wraps(view_func)
    def _wrapped_view(request: HttpRequest, contest_id: int, *args: Any, **kwargs: Any) -> HttpResponse:
        contest = get_object_or_404(Contest, id=contest_id)
        if not is_contest_staff(request.user, contest):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.path.endswith('/'):
                return JsonResponse({'ok': False, 'error': 'Permission denied: Contest staff privileges required.'}, status=403)
            raise PermissionDenied("Contest staff privileges required.")
        return view_func(request, contest_id, *args, **kwargs)
    return _wrapped_view

