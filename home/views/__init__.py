"""
Obsidian Arena - Modular Views Package
Deconstructs monolithic views.py into domain-specific modules:
- auth: Authentication, OTP verification, password reset, and profile management
- contest: Contest lobby, dashboard, leaderboards, proctoring violations, and unbanning
- ide: Code editor workspace, code submission, and Tree-sitter static analysis gate
- api: Asynchronous JSON polling endpoints for submissions, diagnostics, and leaderboards
"""

from .auth import (
    auth_view,
    verify_otp_view,
    resend_otp_view,
    CustomPasswordResetView,
    CustomPasswordResetConfirmView,
    check_profile_status,
    complete_profile,
    profile_view,
    logout_view,
)
from .contest import (
    home,
    dashboard_view,
    check_disqualified,
    get_compiled_contest_leaderboard,
    contest_lobby,
    enter_contest,
    log_violation,
    unban_contestant,
    unban_self,
)
from .ide import (
    problem_ide_view,
    handle_submission,
)
from .api import (
    contest_leaderboard_api,
    submission_status_api,
    submission_history_api,
    run_status_api,
)

__all__ = [
    # Auth
    'auth_view',
    'verify_otp_view',
    'resend_otp_view',
    'CustomPasswordResetView',
    'CustomPasswordResetConfirmView',
    'check_profile_status',
    'complete_profile',
    'profile_view',
    'logout_view',
    # Contest
    'home',
    'dashboard_view',
    'check_disqualified',
    'get_compiled_contest_leaderboard',
    'contest_lobby',
    'enter_contest',
    'log_violation',
    'unban_contestant',
    'unban_self',
    # IDE
    'problem_ide_view',
    'handle_submission',
    # API
    'contest_leaderboard_api',
    'submission_status_api',
    'submission_history_api',
    'run_status_api',
]
