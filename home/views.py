from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from .models import Profile
from django.contrib.auth import logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Contest, ContestProblem, Language, Problem, TestCase
from .models import Submission, UserProblemSession
from .utils import judge_problem
from .rule_checker import check_rules
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.urls import reverse
from django.core.cache import cache
from .tasks import judge_submission, run_code_task
import json

def auth_view(request):
    if request.method == "POST":
        if "register" in request.POST:
            username = request.POST.get('username')
            roll_no = request.POST.get('roll_no')
            email = request.POST.get('email')

            # 1. Check if Username already exists
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username is already taken.")
                return render(request, 'home/register.html')  # Use the correct path!

            # 2. Check if Roll No already exists
            if Profile.objects.filter(roll_no=roll_no).exists():
                messages.error(request, f"Roll No. {roll_no} is already registered.")
                return render(request, 'home/register.html')

            # 3. If all clear, create the account
            try:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=request.POST.get('password')
                )
                Profile.objects.create(
                    user=user,
                    full_name=request.POST.get('full_name'),
                    roll_no=roll_no
                )
                login(request, user)
                return redirect('dashboard')
            except Exception as e:
                messages.error(request, "An unexpected error occurred. Try again.")

        elif "login" in request.POST:
            u_name = request.POST.get('username')
            p_word = request.POST.get('password')
            user = authenticate(request, username=u_name, password=p_word)
            if user is not None:
                login(request, user)
                return redirect('dashboard')
            else:
                messages.error(request, "Invalid username or password.")
                return render(request, 'home/register.html')
    return render(request, 'home/register.html')


def logout_view(request):
    logout(request)
    return redirect('main-home')


def profile_view(request):
    return render(request, 'home/profile.html')


def home(request):
    return render(request, 'home/home.html')


@login_required
def dashboard_view(request):
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
            roll_no="ADMIN-SYS"
        )

    context = {
        'live_contests': live_contests,
        'upcoming_contests': upcoming_contests,
        'archived_contests': archived_contests,
        'profile': user_profile,
    }
    return render(request, 'home/dashboard.html', context)


@login_required
def contest_lobby(request, contest_id):
    contest = get_object_or_404(Contest, id=contest_id)
    now = timezone.now()

    is_live = contest.start_time <= now <= contest.end_time
    is_archived = now > contest.end_time

    time_remaining = (contest.end_time - now).total_seconds()

    blackout_active = is_live and (0 < time_remaining <= 600)

    problems = ContestProblem.objects.filter(contest=contest).select_related('problem')

    total_problems = problems.count()

    # Parse tags into a list for rendering
    tags = []
    if contest.tags:
        tags = [t.strip() for t in contest.tags.split(',') if t.strip()]

    # Build a simple leaderboard: count accepted problems per user and use last accepted time as tiebreaker
    leaderboard = []
    try:
        # Get all submissions for this contest to process leaderboard in-memory
        all_subs = Submission.objects.filter(contest=contest).select_related('user', 'problem')
        
        # Sort all submissions chronologically to calculate attempts/solved correctly
        sorted_subs = sorted(list(all_subs), key=lambda s: s.time_submitted)
        
        # Group submissions by (user_id, problem_id)
        subs_by_user_prob = {}
        for sub in sorted_subs:
            key = (sub.user.id, sub.problem.id)
            if key not in subs_by_user_prob:
                subs_by_user_prob[key] = []
            subs_by_user_prob[key].append(sub)

        # Get contest problem IDs in order
        problem_ids = [cp.problem.id for cp in problems]

        user_data = {}
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
            
            # Track highest score and minimum time taken for each problem
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
                    
        # Compile leaderboard list
        for uid, uinfo in user_data.items():
            solved_count = sum(1 for p in uinfo['problems'].values() if p['is_accepted'])
            total_score = sum(p['score'] for p in uinfo['problems'].values())
            total_time = sum(p['time_taken'] for p in uinfo['problems'].values())
            
            # Now build details for each problem in contest order
            prob_details = []
            for pid in problem_ids:
                subs = subs_by_user_prob.get((uid, pid), [])
                attempts = 0
                failed_before_ac = 0
                is_solved = False
                first_ac_sub = None
                
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
                        
                        # format solve_time_mins as MM:SS
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

            # Format time taken (total_time is in minutes)
            def fmt(mins):
                if mins <= 0:
                    return '00:00:00'
                secs = int(mins * 60)
                h = secs // 3600
                m = (secs % 3600) // 60
                s = secs % 60
                return f"{h}:{str(m).zfill(2)}:{str(s).zfill(2)}"
                
            leaderboard.append({
                'user_id': uid,
                'username': uinfo['username'],
                'solved': solved_count,
                'score': total_score,
                'time_taken': total_time,
                'time_taken_str': fmt(total_time),
                'problems_details': prob_details,
            })
            
        # Sort by solved DESC, then score DESC, then time_taken ASC
        leaderboard.sort(key=lambda r: (-r['solved'], -r['score'], r['time_taken']))
        
        # User's solved problems for marking rows
        solved_problems = list(Submission.objects.filter(
            user=request.user, contest=contest, is_accepted=True
        ).values_list('problem__id', flat=True).distinct()) if request.user.is_authenticated else []

        # User's attempted problems for marking rows
        attempted_problems = list(UserProblemSession.objects.filter(
            user=request.user, contest=contest
        ).values_list('problem__id', flat=True).distinct()) if request.user.is_authenticated else []

        # Compute in-memory success rate per problem
        problem_stats = {}
        for sub in all_subs:
            pid = sub.problem.id
            if pid not in problem_stats:
                problem_stats[pid] = {'total': 0, 'accepted': 0}
            problem_stats[pid]['total'] += 1
            if sub.is_accepted:
                problem_stats[pid]['accepted'] += 1

        for cp in problems:
            stats = problem_stats.get(cp.problem.id, {'total': 0, 'accepted': 0})
            if stats['total'] > 0:
                cp.success_rate = round((stats['accepted'] / stats['total']) * 100, 1)
            else:
                cp.success_rate = 0.0

        # Calculate current user stats
        user_score = 0
        user_solved_count = len(solved_problems)
        user_rank = "-"
        if request.user.is_authenticated:
            for rank, entry in enumerate(leaderboard, start=1):
                if entry['user_id'] == request.user.id:
                    user_score = entry['score']
                    user_rank = rank
                    user_solved_count = entry['solved']
                    break
            else:
                user_score = 0
                user_solved_count = 0
                user_rank = len(leaderboard) + 1

    except OperationalError:
        # Submission table doesn't exist (migrations not applied) — fallback to dummy leaderboard
        import datetime
        now = timezone.now()
        # Dummy leaderboard with time_taken (seconds) and formatted string
        leaderboard = [
            {'user_id': 1, 'username': 'cipher_null', 'solved': 7, 'time_taken': 2*3600+14*60+55, 'time_taken_str': '02:14:55', 'score': 700},
            {'user_id': 2, 'username': 'voidwalker_x', 'solved': 6, 'time_taken': 3*3600+5*60+12, 'time_taken_str': '03:05:12', 'score': 600},
            {'user_id': 3, 'username': 'obsidian_dev', 'solved': 5, 'time_taken': 4*3600+22*60+8, 'time_taken_str': '04:22:08', 'score': 500},
        ]
        for entry in leaderboard:
            entry['problems_details'] = []
            for i, cp in enumerate(problems):
                if i < entry['solved']:
                    entry['problems_details'].append({
                        'status': 'solved',
                        'text': f"1 ({i*10+5}:00 + 0)",
                    })
                elif i == entry['solved']:
                    entry['problems_details'].append({
                        'status': 'attempted',
                        'text': "2 (0:00 + 0)",
                    })
                else:
                    entry['problems_details'].append({
                        'status': 'empty',
                        'text': "",
                    })
        solved_problems = []
        attempted_problems = []
        user_score = 0
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
    # Render the contest lobby template with contest data
    return render(request, 'home/contest_lobby.html', context)


@login_required
def enter_contest(request, contest_id):
    """Endpoint to validate contest passkey (if any) and return a redirect to the lobby.

    Expects POST with optional 'passkey'. Returns JSON {ok, redirect} on success,
    or {ok: False, error} with appropriate status on failure.
    Archived contests bypass the passkey check.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    contest = get_object_or_404(Contest, id=contest_id)
    now = timezone.now()
    is_archived = now > contest.end_time

    # Archived contests don't require a passkey
    if is_archived:
        return JsonResponse({'ok': True, 'redirect': reverse('contest_lobby', args=[contest.id])})

    provided = request.POST.get('passkey', '') or ''
    # If contest has a passkey configured, validate it
    if contest.passkey:
        if provided and provided == contest.passkey:
            return JsonResponse({'ok': True, 'redirect': reverse('contest_lobby', args=[contest.id])})
        else:
            return JsonResponse({'ok': False, 'error': 'Invalid passkey'}, status=403)

    # No passkey set — allow entry
    return JsonResponse({'ok': True, 'redirect': reverse('contest_lobby', args=[contest.id])})


@login_required
def problem_ide_view(request, contest_id, problem_id):
    """Render the problem IDE page where the user can solve and upload code."""
    contest = get_object_or_404(Contest, id=contest_id)
    # try to load the problem object via ContestProblem relation
    cp = get_object_or_404(ContestProblem, contest=contest, problem__id=problem_id)
    problem = cp.problem
    now = timezone.now()

    # Create session if it doesn't exist
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

    raw_constraints = problem.constraints or ''
    constraint_lines = [line.strip() for line in raw_constraints.splitlines() if line.strip()]
    if len(constraint_lines) <= 1 and ';' in raw_constraints:
        constraint_lines = [line.strip() for line in raw_constraints.split(';') if line.strip()]

    sample_cases = problem.testcases.filter(is_sample=True).order_by('id')

    allowed_languages_qs = problem.allowed_languages.all().order_by('name')
    if not allowed_languages_qs.exists():
        allowed_languages_qs = Language.objects.all().order_by('name')
    allowed_languages = list(allowed_languages_qs)

    import json
    stubs_dict = {}
    for stub in problem.stubs.select_related('language'):
        stubs_dict[stub.language.slug] = stub.starter_code
    
    code_stubs_json = json.dumps(stubs_dict)

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
    }
    return render(request, 'home/problem_ide.html', context)


@login_required
def handle_submission(request, contest_id, problem_id):
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

    # ── Static Analysis Gate (Tree-sitter) ──────────────────────────────
    # Runs BEFORE Docker is ever touched. Custom input (RUN) skips rules.
    is_custom_run = (action_type == 'RUN' and data.get('is_custom', False))
    if not is_custom_run:
        rules = problem.rules.all()
        violations = check_rules(code, language_slug, rules)
        if violations:
            # Format violations into a user-readable result terminal entry
            error_lines = '\n'.join(
                f"[{v['rule_type']}] {v['message']}" for v in violations
            )
            rule_result = [{
                'id': '00',
                'status': 'fail',
                'label': 'RULE VIOLATION',
                'stdout': '',
                'stderr': error_lines,
                'expected': '',
                'time': '0.0s'
            }]
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
        import time
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


@login_required
def submission_status_api(request, submission_id):
    """
    Returns the execution status and results of a submission.
    Uses Redis cache to prevent high database query loads (polling storms mitigation).
    If a pending/running submission is older than 2 minutes, it is marked as failed (orphaned execution cleanup).
    """
    import time
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
    import datetime
    from django.utils import timezone
    if submission.status in ['PENDING', 'RUNNING'] and submission.time_submitted < timezone.now() - datetime.timedelta(minutes=2):
        submission.status = 'RE'
        submission.error_message = "System error: execution orphaned (stuck in queue/runner lost)."
        submission.save()
        
        # Build fake SYSTEM ERROR terminal results and cache it
        results = [{
            'id': '00',
            'status': 'fail',
            'label': 'SYSTEM ERROR',
            'stdout': '',
            'stderr': submission.error_message,
            'expected': '',
            'time': '0.000s'
        }]
        status_data = {
            "status": "RE",
            "is_accepted": False,
            "score": 0.0,
            "execution_time": 0.0,
            "memory_used": 0,
            "error_message": submission.error_message,
            "results": results,
            "user_id": submission.user_id,
            "ok": True
        }
        cache.set(cache_key, status_data, timeout=300)
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
def submission_history_api(request, contest_id, problem_id):
    """Returns JSON history of user's submissions for a specific problem."""
    # Clean up any stuck submissions in history older than 2 minutes
    import datetime
    from django.utils import timezone
    cutoff = timezone.now() - datetime.timedelta(minutes=2)
    stuck_submissions = Submission.objects.filter(
        user=request.user,
        contest_id=contest_id,
        problem_id=problem_id,
        status__in=['PENDING', 'RUNNING'],
        time_submitted__lt=cutoff
    )
    for sub in stuck_submissions:
        sub.status = 'RE'
        sub.error_message = "System error: execution orphaned (stuck in queue/runner lost)."
        sub.save()
        
        # Sync to Redis cache
        cache_key = f"sub_status_{sub.id}"
        results = [{
            'id': '00',
            'status': 'fail',
            'label': 'SYSTEM ERROR',
            'stdout': '',
            'stderr': sub.error_message,
            'expected': '',
            'time': '0.000s'
        }]
        cache.set(cache_key, {
            "status": "RE",
            "is_accepted": False,
            "score": 0.0,
            "execution_time": 0.0,
            "memory_used": 0,
            "error_message": sub.error_message,
            "results": results,
            "ok": True
        }, timeout=300)

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
def run_status_api(request, problem_id):
    """
    Returns the execution status and results of a diagnostic run code execution.
    Reads directly from Redis Cache to prevent web thread blockage.
    """
    cache_key = f"run_status_{request.user.id}_{problem_id}"
    status_data = cache.get(cache_key)
    if status_data:
        return JsonResponse(status_data)
        
    return JsonResponse({'ok': False, 'error': 'Run status not found'}, status=404)

