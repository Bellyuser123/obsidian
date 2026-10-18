"""
Asynchronous Polling & Data APIs
Provides high-performance, cached JSON APIs for real-time frontend polling:
- Contest leaderboard updates
- Submission grading status and terminal output
- Diagnostic run code results
- Problem submission history
"""

from typing import List, Dict, Any, Optional
import datetime
import time

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from home.models import Contest, ContestProblem, Submission
from .contest import get_compiled_contest_leaderboard


def reap_orphaned_submission(submission: Submission) -> Dict[str, Any]:
    """
    Recovers an execution orphaned in queue or lost runner (> 120 seconds old).
    Marks it as Runtime Error ('RE') in PostgreSQL and updates the Redis polling cache.
    """
    error_msg = "System error: execution orphaned (stuck in queue/runner lost)."
    submission.status = 'RE'
    submission.error_message = error_msg
    submission.save()

    results = [{
        'id': '00',
        'status': 'fail',
        'label': 'SYSTEM ERROR',
        'stdout': '',
        'stderr': error_msg,
        'expected': '',
        'time': '0.000s'
    }]
    status_data = {
        "status": "RE",
        "is_accepted": False,
        "score": 0.0,
        "execution_time": 0.0,
        "memory_used": 0,
        "error_message": error_msg,
        "results": results,
        "user_id": submission.user_id,
        "ok": True
    }
    cache.set(f"sub_status_{submission.id}", status_data, timeout=300)
    return status_data


@login_required
def contest_leaderboard_api(request: HttpRequest, contest_id: int) -> JsonResponse:
    """
    Returns JSON response containing cached leaderboard data for asynchronous consumption.
    """
    contest = get_object_or_404(Contest, id=contest_id)
    problem_ids = list(ContestProblem.objects.filter(contest=contest).values_list('problem_id', flat=True))
    leaderboard, problem_stats = get_compiled_contest_leaderboard(contest, problem_ids)
    return JsonResponse({
        'ok': True,
        'contest_id': contest.id,
        'leaderboard': leaderboard,
        'problem_stats': problem_stats,
    })


@login_required
def submission_status_api(request: HttpRequest, submission_id: int) -> JsonResponse:
    """
    Returns the execution status and results of a submission.
    Uses Redis cache to prevent high database query loads (polling storms mitigation).
    If a pending/running submission is older than 2 minutes, it is marked as failed (orphaned execution cleanup).
    """
    cache_key = f"sub_status_{submission_id}"
    status_data = cache.get(cache_key)

    if status_data:
        # Validate ownership check
        user_id = status_data.get('user_id')
        if user_id and user_id != request.user.id and not request.user.is_staff:
            return JsonResponse({'ok': False, 'error': 'Access denied'}, status=403)

        status = status_data.get('status')
        created_at = status_data.get('created_at')

        # 1. If the status is resolved, serve directly from cache
        if status not in ['PENDING', 'RUNNING']:
            return JsonResponse(status_data)

        # 2. If it is PENDING or RUNNING but less than 120 seconds old, serve from cache
        if created_at and time.time() - created_at < 120:
            return JsonResponse(status_data)

    try:
        submission = Submission.objects.select_related('problem', 'language').get(id=submission_id)
    except Submission.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Submission not found'}, status=404)

    if submission.user != request.user and not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Access denied'}, status=403)

    # Check if the submission is stuck/orphaned in PENDING/RUNNING (older than 120 seconds)
    cutoff = timezone.now() - datetime.timedelta(minutes=2)
    if submission.status in ['PENDING', 'RUNNING'] and submission.time_submitted < cutoff:
        status_data = reap_orphaned_submission(submission)
        return JsonResponse(status_data)

    # If it is still pending/running but not stuck yet, return the state
    if submission.status in ['PENDING', 'RUNNING']:
        if not status_data:
            status_data = {
                "status": submission.status,
                "user_id": submission.user_id,
                "created_at": submission.time_submitted.timestamp(),
                "ok": True
            }
            cache.set(cache_key, status_data, timeout=300)
        return JsonResponse(status_data)

    # Build resolved status data if DB shows resolved but cache was missing/expired
    results = []
    if submission.status in ['CE', 'RE', 'WA', 'TLE', 'AC', 'PARTIAL']:
        results = [{
            'id': '00',
            'status': 'pass' if submission.is_accepted else 'fail',
            'label': submission.status,
            'stdout': '',
            'stderr': submission.error_message or '',
            'expected': '',
            'time': f"{submission.execution_time:.3f}s"
        }]

    status_data = {
        "status": submission.status,
        "is_accepted": submission.is_accepted,
        "score": float(submission.score_awarded),
        "execution_time": float(submission.execution_time),
        "memory_used": int(submission.memory_used),
        "error_message": submission.error_message or '',
        "results": results,
        "ok": True
    }

    cache.set(cache_key, status_data, timeout=300)
    return JsonResponse(status_data)


@login_required
def submission_history_api(request: HttpRequest, contest_id: int, problem_id: int) -> JsonResponse:
    """
    Returns JSON history of user's submissions for a specific problem.
    Recovers any stuck executions older than 2 minutes.
    """
    cutoff = timezone.now() - datetime.timedelta(minutes=2)
    stuck_submissions = Submission.objects.filter(
        user=request.user,
        contest_id=contest_id,
        problem_id=problem_id,
        status__in=['PENDING', 'RUNNING'],
        time_submitted__lt=cutoff
    )
    for sub in stuck_submissions:
        reap_orphaned_submission(sub)

    submissions = Submission.objects.filter(
        user=request.user, contest_id=contest_id, problem_id=problem_id
    ).order_by('-time_submitted')

    data = []
    for sub in submissions:
        data.append({
            'id': sub.id,
            'time': sub.time_submitted.strftime("%b %d, %H:%M"),
            'status': sub.status,
            'language': sub.language.name if sub.language else 'Unknown',
            'score': round(sub.score_awarded, 2),
            'execution_time': f"{sub.execution_time:.3f}s",
            'memory_used': f"{sub.memory_used} KB",
            'total_time': f"{sub.total_time_taken:.1f}m",
            'code': sub.code,
            'error_message': sub.error_message or ''
        })

    return JsonResponse({'ok': True, 'submissions': data})


@login_required
def run_status_api(request: HttpRequest, problem_id: int) -> JsonResponse:
    """
    Returns the execution status and results of a diagnostic run code execution.
    Reads directly from Redis Cache to prevent web thread blockage.
    """
    cache_key = f"run_status_{request.user.id}_{problem_id}"
    status_data = cache.get(cache_key)
    if status_data:
        return JsonResponse(status_data)

    return JsonResponse({'ok': False, 'error': 'Run status not found'}, status=404)
