"""
Contest Lifecycle & Competition Views
Handles contest listings, dashboard, lobby, cached leaderboards, passkey validation,
and proctoring violation enforcement.
"""

from typing import List, Dict, Any, Tuple, Optional, Union
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.utils import OperationalError
from django.http import HttpRequest, HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from home.models import (
    Contest,
    ContestProblem,
    ContestParticipation,
    Profile,
    Submission,
    UserProblemSession,
    ViolationLog,
)


def home(request: HttpRequest) -> HttpResponse:
    """
    Renders public landing page.
    """
    return render(request, 'home/home.html')


@login_required
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    Displays contestant dashboard with live, upcoming, and archived contests.
    Ensures contestant profile is complete before granting access.
    """
    now = timezone.now()

    live_contests = Contest.objects.filter(start_time__lte=now, end_time__gte=now)
    for contest in live_contests:
        contest.seconds_remaining = int((contest.end_time - now).total_seconds())

    upcoming_contests = Contest.objects.filter(start_time__gt=now).order_by('start_time')
    archived_contests = Contest.objects.filter(end_time__lt=now).order_by('-end_time')

    try:
        user_profile = request.user.profile
    except Profile.DoesNotExist:
        user_profile = Profile.objects.create(
            user=request.user,
            full_name=request.user.username,
            roll_no="ADMIN-SYS",
            roll_number="ADMIN-SYS",
            is_profile_complete=True
        )

    roll = user_profile.roll_number or user_profile.roll_no
    if not user_profile.is_profile_complete or not roll:
        return redirect('complete_profile')

    context = {
        'live_contests': live_contests,
        'upcoming_contests': upcoming_contests,
        'archived_contests': archived_contests,
        'profile': user_profile,
    }
    return render(request, 'home/dashboard.html', context)


def check_disqualified(user: Optional[User], contest: Contest) -> bool:
    """
    Evaluates whether a user is currently disqualified for a contest.
    Enforces the following security rules:
    - Unauthenticated users cannot be banned
    - Superusers, staff, and contest hosts are immune to disqualification
    - Disqualification is only active when contest anti-cheat is enabled
    - Disqualification only applies while the contest is live
    - When contest ends, banned participants are automatically cleared
    """
    if not user or not user.is_authenticated:
        return False

    # Superuser, staff, or the contest host cannot be banned
    if user.is_superuser or user.is_staff or (hasattr(contest, 'host_id') and contest.host_id and user.id == contest.host_id):
        return False

    # Banning should only be in contests where proctor mode is enabled
    if not contest.enable_anti_cheat:
        return False

    now = timezone.now()
    # When the contest ends, reset the banned list
    if now > contest.end_time:
        if ContestParticipation.objects.filter(contest=contest, is_disqualified=True).exists():
            contest.reset_banned_list()
        return False

    # The contestant should only be banned till the contest is live
    if now < contest.start_time:
        return False

    participation = ContestParticipation.objects.filter(user=user, contest=contest).first()
    if participation and participation.is_disqualified:
        return True
    return False


def format_duration_hms(mins: float) -> str:
    """
    Formats minute float into HH:MM:SS string.
    """
    if mins <= 0:
        return '00:00:00'
    secs = int(mins * 60)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h}:{str(m).zfill(2)}:{str(s).zfill(2)}"


def get_compiled_contest_leaderboard(
    contest: Contest,
    problem_ids: List[int]
) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, int]]]:
    """
    Retrieves or compiles the contest leaderboard and problem statistics,
    caching the result in Redis with a 60-second TTL to eliminate web server
    crashes and CPU exhaustion under high contest participant loads.
    """
    cache_key = f"contest_leaderboard_{contest.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached.get('leaderboard', []), cached.get('problem_stats', {})

    all_subs = list(Submission.objects.filter(contest=contest).select_related('user', 'problem'))
    sorted_subs = sorted(all_subs, key=lambda s: s.time_submitted)

    subs_by_user_prob: Dict[Tuple[int, int], List[Submission]] = {}
    for sub in sorted_subs:
        key = (sub.user.id, sub.problem.id)
        if key not in subs_by_user_prob:
            subs_by_user_prob[key] = []
        subs_by_user_prob[key].append(sub)

    user_data: Dict[int, Dict[str, Any]] = {}
    for sub in all_subs:
        uid = sub.user.id
        username = sub.user.username
        pid = sub.problem.id

        if uid not in user_data:
            user_data[uid] = {
                'user_id': uid,
                'username': username,
                'problems': {}
            }

        prob_dict = user_data[uid]['problems']
        if pid not in prob_dict:
            prob_dict[pid] = {
                'score': sub.score_awarded or 0.0,
                'time_taken': sub.total_time_taken or 0.0,
                'is_accepted': sub.is_accepted
            }
        else:
            current_best = prob_dict[pid]
            sub_score = sub.score_awarded or 0.0
            sub_time = sub.total_time_taken or 0.0
            if (sub_score > current_best['score']) or \
               (sub_score == current_best['score'] and sub_time < current_best['time_taken']):
                prob_dict[pid] = {
                    'score': sub_score,
                    'time_taken': sub_time,
                    'is_accepted': sub.is_accepted or current_best['is_accepted']
                }

    leaderboard: List[Dict[str, Any]] = []
    for uid, uinfo in user_data.items():
        solved_count = sum(1 for p in uinfo['problems'].values() if p['is_accepted'])
        total_score = sum(p['score'] for p in uinfo['problems'].values())
        total_time = sum(p['time_taken'] for p in uinfo['problems'].values())

        prob_details: List[Dict[str, str]] = []
        for pid in problem_ids:
            subs = subs_by_user_prob.get((uid, pid), [])
            attempts = 0
            failed_before_ac = 0
            is_solved = False
            first_ac_sub: Optional[Submission] = None

            for sub in subs:
                attempts += 1
                if sub.is_accepted:
                    is_solved = True
                    first_ac_sub = sub
                    break
                else:
                    if sub.status not in ['AC', 'PARTIAL']:
                        failed_before_ac += 1

            if attempts > 0:
                if is_solved and first_ac_sub:
                    penalty = failed_before_ac * contest.penalty_minutes
                    solve_time_mins = max(0.0, (first_ac_sub.total_time_taken or 0.0) - penalty)
                    total_secs = int(round(solve_time_mins * 60))
                    m = total_secs // 60
                    s = total_secs % 60
                    time_str = f"{m}:{str(s).zfill(2)}"
                    prob_details.append({
                        'status': 'solved',
                        'text': f"{attempts} ({time_str} + {penalty})",
                    })
                else:
                    prob_details.append({
                        'status': 'attempted',
                        'text': f"{attempts} (0:00 + 0)",
                    })
            else:
                prob_details.append({
                    'status': 'empty',
                    'text': '',
                })

        leaderboard.append({
            'user_id': uid,
            'username': uinfo['username'],
            'solved': solved_count,
            'score': total_score,
            'time_taken': total_time,
            'time_taken_str': format_duration_hms(total_time),
            'problems_details': prob_details,
        })

    leaderboard.sort(key=lambda r: (-r['solved'], -r['score'], r['time_taken']))

    problem_stats: Dict[int, Dict[str, int]] = {}
    for sub in all_subs:
        pid = sub.problem.id
        if pid not in problem_stats:
            problem_stats[pid] = {'total': 0, 'accepted': 0}
        problem_stats[pid]['total'] += 1
        if sub.is_accepted:
            problem_stats[pid]['accepted'] += 1

    cache.set(cache_key, {'leaderboard': leaderboard, 'problem_stats': problem_stats}, timeout=60)
    return leaderboard, problem_stats


@login_required
def contest_lobby(request: HttpRequest, contest_id: int) -> HttpResponse:
    """
    Renders the contest lobby including problems list, cached leaderboard,
    and user participation rank.
    """
    contest = get_object_or_404(Contest, id=contest_id)

    if check_disqualified(request.user, contest):
        return render(request, 'home/disqualified.html', {'contest': contest}, status=403)

    if request.user.is_authenticated:
        ContestParticipation.objects.get_or_create(user=request.user, contest=contest)

    now = timezone.now()
    is_live = contest.start_time <= now <= contest.end_time
    is_archived = now > contest.end_time
    time_remaining = (contest.end_time - now).total_seconds()
    blackout_active = is_live and (0 < time_remaining <= 600)

    problems = ContestProblem.objects.filter(contest=contest).select_related('problem')
    total_problems = problems.count()

    tags = []
    if contest.tags:
        tags = [t.strip() for t in contest.tags.split(',') if t.strip()]

    problem_ids = [cp.problem.id for cp in problems]
    leaderboard = []

    try:
        leaderboard, problem_stats = get_compiled_contest_leaderboard(contest, problem_ids)

        for cp in problems:
            stats = problem_stats.get(cp.problem.id, {'total': 0, 'accepted': 0})
            if stats['total'] > 0:
                cp.success_rate = round((stats['accepted'] / stats['total']) * 100, 1)
            else:
                cp.success_rate = 0.0

        solved_problems = list(Submission.objects.filter(
            user=request.user, contest=contest, is_accepted=True
        ).values_list('problem__id', flat=True).distinct()) if request.user.is_authenticated else []

        attempted_problems = list(UserProblemSession.objects.filter(
            user=request.user, contest=contest
        ).values_list('problem__id', flat=True).distinct()) if request.user.is_authenticated else []

        user_score = 0.0
        user_solved_count = len(solved_problems)
        user_rank: Union[int, str] = "-"
        if request.user.is_authenticated:
            for rank, entry in enumerate(leaderboard, start=1):
                if entry['user_id'] == request.user.id:
                    user_score = entry['score']
                    user_rank = rank
                    user_solved_count = entry['solved']
                    break
            else:
                user_score = 0.0
                user_solved_count = 0
                user_rank = len(leaderboard) + 1

    except OperationalError:
        # Fallback dummy leaderboard if migrations are pending in dev/test
        leaderboard = [
            {'user_id': 1, 'username': 'cipher_null', 'solved': 7, 'time_taken': 2*3600+14*60+55, 'time_taken_str': '02:14:55', 'score': 700},
            {'user_id': 2, 'username': 'voidwalker_x', 'solved': 6, 'time_taken': 3*3600+5*60+12, 'time_taken_str': '03:05:12', 'score': 600},
            {'user_id': 3, 'username': 'obsidian_dev', 'solved': 5, 'time_taken': 4*3600+22*60+8, 'time_taken_str': '04:22:08', 'score': 500},
        ]
        for entry in leaderboard:
            entry['problems_details'] = []
            for i, cp in enumerate(problems):
                if i < entry['solved']:
                    entry['problems_details'].append({'status': 'solved', 'text': f"1 ({i*10+5}:00 + 0)"})
                elif i == entry['solved']:
                    entry['problems_details'].append({'status': 'attempted', 'text': "2 (0:00 + 0)"})
                else:
                    entry['problems_details'].append({'status': 'empty', 'text': ""})
        solved_problems = []
        attempted_problems = []
        user_score = 0.0
        user_solved_count = 0
        user_rank = "-"
        for cp in problems:
            cp.success_rate = 0.0

    context = {
        'contest': contest,
        'problems': problems,
        'is_live': is_live,
        'is_archived': is_archived,
        'blackout_active': blackout_active,
        'time_remaining': int(time_remaining) if time_remaining > 0 else 0,
        'contest_end_unix': int(contest.end_time.timestamp()),
        'total_problems': total_problems,
        'solved_problems': solved_problems,
        'attempted_problems': attempted_problems,
        'leaderboard': leaderboard,
        'tags': tags,
        'user_score': user_score,
        'user_rank': user_rank,
        'user_solved_count': user_solved_count,
    }
    return render(request, 'home/contest_lobby.html', context)


@login_required
def enter_contest(request: HttpRequest, contest_id: int) -> JsonResponse:
    """
    Validates contest passkey (if configured).
    Archived contests bypass the passkey check.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    contest = get_object_or_404(Contest, id=contest_id)

    if check_disqualified(request.user, contest):
        return JsonResponse({'ok': False, 'error': 'You are disqualified from this contest.'}, status=403)

    now = timezone.now()
    is_archived = now > contest.end_time

    # Archived contests don't require a passkey
    if is_archived:
        if request.user.is_authenticated:
            ContestParticipation.objects.get_or_create(user=request.user, contest=contest)
        return JsonResponse({'ok': True, 'redirect': reverse('contest_lobby', args=[contest.id])})

    provided = request.POST.get('passkey', '') or ''
    # If contest has a passkey configured, validate it
    if contest.passkey:
        if provided and provided == contest.passkey:
            if request.user.is_authenticated:
                ContestParticipation.objects.get_or_create(user=request.user, contest=contest)
            return JsonResponse({'ok': True, 'redirect': reverse('contest_lobby', args=[contest.id])})
        else:
            return JsonResponse({'ok': False, 'error': 'Invalid passkey'}, status=403)

    # No passkey set — allow entry
    if request.user.is_authenticated:
        ContestParticipation.objects.get_or_create(user=request.user, contest=contest)
    return JsonResponse({'ok': True, 'redirect': reverse('contest_lobby', args=[contest.id])})


@login_required
@require_POST
def log_violation(request: HttpRequest, contest_id: int) -> JsonResponse:
    """
    Records proctoring violations and enforces strike penalties:
    - Host, staff, and superuser are exempt from bans
    - Banning is only enforced if contest.enable_anti_cheat is True
    - Banning is only enforced while contest is live
    - Contestants receive 3 warnings (strikes 1-3) and are banned on the 4th strike
    """
    contest = get_object_or_404(Contest, id=contest_id)
    if not contest.enable_anti_cheat:
        return JsonResponse({'ok': True, 'action': 'NONE'})

    # Superuser or the host of the contest shouldn't be banned
    if request.user.is_superuser or request.user.is_staff or (contest.host_id and request.user.id == contest.host_id):
        return JsonResponse({'ok': True, 'action': 'NONE', 'message': 'Admin or contest host is exempt from banning.'})

    now = timezone.now()
    # Contestant should only be banned till the contest is live
    if not (contest.start_time <= now <= contest.end_time):
        return JsonResponse({'ok': True, 'action': 'NONE', 'message': 'Contest is not live.'})

    violation_type = request.POST.get('violation_type')
    details = request.POST.get('details', '')

    # Check if already disqualified
    participation, _ = ContestParticipation.objects.get_or_create(user=request.user, contest=contest)
    if participation.is_disqualified:
        return JsonResponse({'action': 'BAN', 'current_strikes': ViolationLog.objects.filter(user=request.user, contest=contest).count()})

    existing_strikes = ViolationLog.objects.filter(user=request.user, contest=contest).count()
    strike_number = existing_strikes + 1

    ViolationLog.objects.create(
        user=request.user,
        contest=contest,
        violation_type=violation_type,
        strike_number=strike_number,
        details=details
    )

    # 3 strikes (3 chances) before the contestant is banned on the 4th strike
    if strike_number >= 4:
        participation.is_disqualified = True
        participation.save()
        return JsonResponse({'action': 'BAN', 'current_strikes': strike_number})
    else:
        return JsonResponse({'action': 'WARN', 'current_strikes': strike_number, 'chances_remaining': 4 - strike_number})


@login_required
def unban_contestant(request: HttpRequest, contest_id: int, user_id: Optional[int] = None) -> HttpResponse:
    """
    Secure contestant unban endpoint.
    Eliminates the SEC-01 'Unauthenticated Self-Unban Backdoor'.
    Only contest hosts, staff, or superusers can unban contestants.
    Regular contestants attempting to unban themselves receive 403 Forbidden.
    """
    contest = get_object_or_404(Contest, id=contest_id)

    # Strict authorization gate: only superuser, staff, or the contest host
    is_authorized = (
        request.user.is_superuser or
        request.user.is_staff or
        (contest.host_id and request.user.id == contest.host_id)
    )
    if not is_authorized:
        return HttpResponseForbidden("Permission denied. Only contest hosts and superusers can unban contestants.")

    target_user_id = user_id or request.GET.get('user_id') or request.POST.get('user_id')

    if target_user_id:
        target_user = get_object_or_404(User, id=target_user_id)
        participation = ContestParticipation.objects.filter(user=target_user, contest=contest).first()
        if participation:
            participation.is_disqualified = False
            participation.save()

        profile = getattr(target_user, 'profile', None)
        if profile and profile.is_disqualified:
            profile.is_disqualified = False
            profile.save()

        ViolationLog.objects.filter(user=target_user, contest=contest).delete()
        messages.success(request, f"Contestant {target_user.username} has been unbanned from {contest.name}.")
    else:
        # Reset entire contest banned list and violation strikes
        contest.reset_banned_list()
        messages.success(request, f"All banned contestants for {contest.name} have been reset successfully.")

    return redirect('contest_lobby', contest_id=contest.id)


# Backward-compatible alias for existing routing and reverses
unban_self = unban_contestant
