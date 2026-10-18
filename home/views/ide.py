"""
IDE Workspace & Code Submission Views
Handles online IDE rendering, starter code stubs, Tree-sitter static analysis gates,
and Celery background compilation dispatching.
"""

from typing import List, Dict, Any, Optional
import json
import time

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from home.models import (
    Contest,
    Problem,
    ContestProblem,
    Language,
    Submission,
    UserProblemSession,
    ContestParticipation,
    ViolationLog,
)
from home.rule_checker import check_rules
from home.tasks import judge_submission, run_code_task
from .contest import check_disqualified


def get_problem_constraints(raw_constraints: Optional[str]) -> List[str]:
    """
    Parses constraint strings into cleaned display lines.
    Supports newline or semicolon delimited format strings.
    """
    raw = raw_constraints or ''
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) <= 1 and ';' in raw:
        lines = [line.strip() for line in raw.split(';') if line.strip()]
    return lines


def format_ast_violation_results(violations: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Formats Tree-sitter rule violations into an IDE terminal failure payload.
    """
    error_lines = '\n'.join(
        f"[{v.get('rule_type', 'SYNTAX')}] {v.get('message', 'Rule violation')}" for v in violations
    )
    return [{
        'id': '00',
        'status': 'fail',
        'label': 'RULE VIOLATION',
        'stdout': '',
        'stderr': error_lines,
        'expected': '',
        'time': '0.0s'
    }]


@login_required
def problem_ide_view(request: HttpRequest, contest_id: int, problem_id: int) -> HttpResponse:
    """
    Renders the browser-based problem IDE workspace.
    Loads problem stubs, allowed languages, sample testcases, and active strike counts.
    """
    contest = get_object_or_404(Contest, id=contest_id)

    if check_disqualified(request.user, contest):
        return render(request, 'home/disqualified.html', {'contest': contest}, status=403)

    if request.user.is_authenticated:
        ContestParticipation.objects.get_or_create(user=request.user, contest=contest)

    cp = get_object_or_404(ContestProblem, contest=contest, problem__id=problem_id)
    problem = cp.problem
    now = timezone.now()

    UserProblemSession.objects.get_or_create(user=request.user, contest=contest, problem=problem)

    if now < contest.start_time:
        contest_status = 'UPCOMING'
    elif now > contest.end_time:
        contest_status = 'ENDED'
    else:
        contest_status = 'LIVE'

    contest_problem_ids = list(
        ContestProblem.objects.filter(contest=contest)
        .order_by('id')
        .values_list('problem_id', flat=True)
    )
    try:
        problem_number = contest_problem_ids.index(problem.id) + 1
    except ValueError:
        problem_number = 1

    constraint_lines = get_problem_constraints(problem.constraints)
    sample_cases = problem.testcases.filter(is_sample=True).order_by('id')

    allowed_languages_qs = problem.allowed_languages.all().order_by('name')
    if not allowed_languages_qs.exists():
        allowed_languages_qs = Language.objects.all().order_by('name')
    allowed_languages = list(allowed_languages_qs)

    stubs_dict: Dict[str, str] = {}
    for stub in problem.stubs.select_related('language'):
        stubs_dict[stub.language.slug] = stub.starter_code
    code_stubs_json = json.dumps(stubs_dict)

    current_strikes = 0
    if request.user.is_authenticated:
        current_strikes = ViolationLog.objects.filter(user=request.user, contest=contest).count()

    context = {
        'contest': contest,
        'problem': problem,
        'contest_problem': cp,
        'contest_status': contest_status,
        'contest_end_unix': int(contest.end_time.timestamp()),
        'problem_number': problem_number,
        'constraint_lines': constraint_lines,
        'sample_cases': sample_cases,
        'allowed_languages': allowed_languages,
        'code_stubs_json': code_stubs_json,
        'ANTI_CHEAT_ENABLED': contest.enable_anti_cheat,
        'CURRENT_STRIKES': current_strikes,
    }
    return render(request, 'home/problem_ide.html', context)


@login_required
def handle_submission(request: HttpRequest, contest_id: int, problem_id: int) -> JsonResponse:
    """
    Receives code execution and submission requests.
    Enforces size constraints and Tree-sitter AST rules before queueing judge tasks.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    action_type = data.get('type')
    code = data.get('code', '').strip()
    language_slug = data.get('language')

    if not code:
        return JsonResponse({'ok': False, 'error': 'Code is empty'}, status=400)
    if len(code) > 60000:
        return JsonResponse({'ok': False, 'error': 'Code exceeds maximum size of 60KB'}, status=400)

    try:
        contest = Contest.objects.get(id=contest_id)
        problem = Problem.objects.get(id=problem_id)
        language = Language.objects.get(slug=language_slug)
    except (Contest.DoesNotExist, Problem.DoesNotExist, Language.DoesNotExist):
        return JsonResponse({'ok': False, 'error': 'Invalid Contest, Problem, or Language ID'}, status=404)

    # Disqualified contestants cannot submit or run code in this contest
    if check_disqualified(request.user, contest):
        return JsonResponse({'ok': False, 'error': 'You are disqualified from this contest.'}, status=403)

    # ── Static Analysis Gate (Tree-sitter) ──────────────────────────────
    # Runs BEFORE Docker/Podman is ever touched. Custom input (RUN) skips rules.
    is_custom_run = (action_type == 'RUN' and data.get('is_custom', False))
    if not is_custom_run:
        rules = problem.rules.all()
        violations = check_rules(code, language_slug, rules)
        if violations:
            rule_result = format_ast_violation_results(violations)
            return JsonResponse({'ok': True, 'results': rule_result, 'type': action_type.lower()})

    if action_type == 'RUN':
        is_custom = data.get('is_custom', False)
        custom_input = data.get('custom_input', '') if is_custom else ''

        cache_key = f"run_status_{request.user.id}_{problem.id}"
        cache.set(cache_key, {
            "status": "PENDING",
            "ok": True
        }, timeout=300)

        run_code_task.delay(request.user.id, problem.id, code, language_slug, is_custom, custom_input)

        return JsonResponse({
            'ok': True,
            'status': 'PENDING',
            'type': 'run'
        })

    elif action_type == 'SUBMIT':
        submission = Submission.objects.create(
            user=request.user,
            contest=contest,
            problem=problem,
            code=code,
            language=language,
            status='PENDING',
            is_accepted=False
        )

        # Populate initial cache for polling to consume immediately
        cache.set(f"sub_status_{submission.id}", {
            "status": "PENDING",
            "user_id": request.user.id,
            "created_at": time.time(),
            "ok": True
        }, timeout=300)

        # Trigger background Celery task
        judge_submission.delay(submission.id)

        return JsonResponse({
            'ok': True,
            'submission_id': submission.id,
            'status': 'PENDING',
            'type': 'submit'
        })
    else:
        return JsonResponse({'ok': False, 'error': 'Invalid action type'}, status=400)
