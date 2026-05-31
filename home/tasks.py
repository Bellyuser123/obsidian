import os
import time
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Max
from .models import Submission, ContestProblem, Profile, UserProblemSession
from .utils import judge_problem
from .rule_checker import check_rules

@shared_task
def judge_submission(submission_id):
    try:
        submission = Submission.objects.select_related('user', 'problem', 'contest', 'language').get(id=submission_id)
    except Submission.DoesNotExist:
        return

    # Update state to RUNNING
    submission.status = 'RUNNING'
    submission.save()
    cache.set(f"sub_status_{submission_id}", {
        "status": "RUNNING",
        "user_id": submission.user_id,
        "created_at": submission.time_submitted.timestamp(),
        "ok": True
    }, timeout=300)

    problem = submission.problem
    language = submission.language
    code = submission.code

    # 1. Rule Validation Gate
    rules = problem.rules.all()
    violations = check_rules(code, language.slug, rules)
    if violations:
        error_lines = '\n'.join(f"[{v['rule_type']}] {v['message']}" for v in violations)
        submission.status = 'CE'
        submission.error_message = error_lines
        submission.save()
        
        # Build fake CE terminal rows
        results = [{
            'id': '00',
            'status': 'fail',
            'label': 'RULE VIOLATION',
            'stdout': '',
            'stderr': error_lines,
            'expected': '',
            'time': '0.0s'
        }]
        
        cache.set(f"sub_status_{submission_id}", {
            "status": "CE",
            "is_accepted": False,
            "score": 0.0,
            "execution_time": 0.0,
            "memory_used": 0,
            "error_message": error_lines,
            "results": results,
            "user_id": submission.user_id,
            "created_at": submission.time_submitted.timestamp(),
            "ok": True
        }, timeout=300)
        return

    # 2. Run Container Sandbox
    all_cases = problem.testcases.all().order_by('id')
    if not all_cases.exists():
        submission.status = 'RE'
        submission.error_message = 'No test cases configured for this problem'
        submission.save()
        cache.set(f"sub_status_{submission_id}", {
            "status": "RE",
            "is_accepted": False,
            "score": 0.0,
            "execution_time": 0.0,
            "memory_used": 0,
            "error_message": 'No test cases configured for this problem',
            "results": [],
            "user_id": submission.user_id,
            "created_at": submission.time_submitted.timestamp(),
            "ok": True
        }, timeout=300)
        return

    results = judge_problem(code, language, all_cases, stop_on_fail=False)

    # 3. Calculate execution stats & counts
    max_time = 0.0
    max_mem = 0
    passed_count = 0
    total_count = all_cases.count()
    error_msg = ""

    for r in results:
        if r['status'] == 'pass':
            passed_count += 1
        else:
            if not error_msg:
                # Capture the first failure's stderr as the main submission error
                error_msg = r.get('stderr', '')
        try:
            t = float(r.get('time', '0s').replace('s', ''))
            if t > max_time:
                max_time = t
        except ValueError:
            pass
        m = r.get('mem_kb', 0)
        if m > max_mem:
            max_mem = m

    # 4. Determine final status
    if passed_count == total_count:
        final_status = 'AC'
        is_accepted = True
    elif passed_count > 0:
        final_status = 'PARTIAL'
        is_accepted = False
    else:
        is_accepted = False
        first_fail = next((r for r in results if r['status'] != 'pass'), None)
        if first_fail:
            reverse_map = {'WRONG ANSWER': 'WA', 'TIME LIMIT': 'TLE', 'RUNTIME ERROR': 'RE', 'COMPILE ERROR': 'CE', 'RULE VIOLATION': 'RE'}
            final_status = reverse_map.get(first_fail['label'], 'RE')
        else:
            final_status = 'RE'

    # 5. Calculate Score
    import math
    cp = ContestProblem.objects.filter(contest=submission.contest, problem=problem).first()
    points_available = cp.points if cp else 0
    max_score = getattr(problem, 'max_score', points_available)
    if hasattr(problem, 'max_score'):
        max_score = problem.max_score
    else:
        max_score = points_available

    total_weight = sum(tc.weight for tc in all_cases)
    passed_weight = 0
    passed_all = True
    for idx, tc in enumerate(all_cases):
        if idx < len(results) and results[idx]['status'] == 'pass':
            passed_weight += tc.weight
        else:
            passed_all = False

    if total_weight == 0:
        base_score = float(max_score) if passed_all else 0.0
    else:
        base_score = (passed_weight / total_weight) * max_score

    base_score = math.floor(base_score * 100) / 100

    # 6. Calculate Time & Penalties
    session = UserProblemSession.objects.filter(user=submission.user, contest=submission.contest, problem=problem).first()
    time_diff_minutes = (timezone.now() - session.first_opened_at).total_seconds() / 60.0 if session else 0.0

    # Count previous non-AC / non-PARTIAL submissions to apply penalty time
    failed_count = Submission.objects.filter(
        user=submission.user, contest=submission.contest, problem=problem
    ).exclude(id=submission.id).exclude(status__in=['AC', 'PARTIAL']).count()

    penalty_time = failed_count * submission.contest.penalty_minutes

    submission.status = final_status
    submission.is_accepted = is_accepted
    submission.score_awarded = base_score
    submission.total_time_taken = time_diff_minutes + penalty_time
    submission.execution_time = max_time
    submission.memory_used = max_mem
    if error_msg:
        submission.error_message = error_msg
    submission.save()

    # 7. Update Profile Score (only add the difference if they improved)
    best_previous = Submission.objects.filter(
        user=submission.user, contest=submission.contest, problem=problem
    ).exclude(id=submission.id).aggregate(Max('score_awarded'))['score_awarded__max']

    best_previous = best_previous or 0.0

    if base_score > best_previous:
        diff = base_score - best_previous
        profile = submission.user.profile
        profile.total_score += int(diff)
        profile.save()

    # Scrub hidden test case actual outputs before caching for client-side display
    for idx, tc in enumerate(all_cases):
        if not tc.is_sample:
            if idx < len(results):
                results[idx]['expected'] = 'Hidden Test Case'
                results[idx]['stdout'] = 'Hidden Test Case Output'

    # 8. Set Final Verdict Cache
    cache.set(f"sub_status_{submission_id}", {
        "status": final_status,
        "is_accepted": is_accepted,
        "score": base_score,
        "execution_time": max_time,
        "memory_used": max_mem,
        "error_message": error_msg,
        "results": results,
        "user_id": submission.user_id,
        "created_at": submission.time_submitted.timestamp(),
        "ok": True
    }, timeout=300)


@shared_task
def run_code_task(user_id, problem_id, code, language_slug, is_custom=False, custom_input=''):
    cache_key = f"run_status_{user_id}_{problem_id}"
    cache.set(cache_key, {
        "status": "RUNNING",
        "ok": True
    }, timeout=300)

    try:
        from .models import Problem, Language
        problem = Problem.objects.get(id=problem_id)
        language = Language.objects.get(slug=language_slug)
        
        if is_custom:
            class MockTestCase:
                def __init__(self, id, input_data):
                    self.id = id
                    self.input_data = input_data
                    self.expected_output = ''
            
            test_cases = [MockTestCase('custom', custom_input)]
        else:
            test_cases = list(problem.testcases.filter(is_sample=True).order_by('id'))
            if not test_cases:
                cache.set(cache_key, {
                    "status": "FAILURE",
                    "error": "No sample test cases configured.",
                    "ok": False
                }, timeout=300)
                return

        results = judge_problem(code, language, test_cases, stop_on_fail=False)

        cache.set(cache_key, {
            "status": "SUCCESS",
            "results": results,
            "type": "custom" if is_custom else "run",
            "custom_input": custom_input,
            "ok": True
        }, timeout=300)

    except Exception as e:
        cache.set(cache_key, {
            "status": "FAILURE",
            "error": str(e),
            "ok": False
        }, timeout=300)


from celery.signals import task_prerun, task_postrun
from django.db import close_old_connections

@task_prerun.connect
def close_db_connections_before_task(*args, **kwargs):
    close_old_connections()

@task_postrun.connect
def close_db_connections_after_task(*args, **kwargs):
    close_old_connections()

