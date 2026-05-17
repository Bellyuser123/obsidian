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
            })
            
        # Sort by solved DESC, then score DESC, then time_taken ASC
        leaderboard.sort(key=lambda r: (-r['solved'], -r['score'], r['time_taken']))
        
        # User's solved problems for marking rows
        solved_problems = list(Submission.objects.filter(
            user=request.user, contest=contest, is_accepted=True
        ).values_list('problem__id', flat=True).distinct()) if request.user.is_authenticated else []
    except OperationalError:
        # Submission table doesn't exist (migrations not applied) — fallback to dummy leaderboard
        import datetime
        now = timezone.now()
        # Dummy leaderboard with time_taken (seconds) and formatted string
        leaderboard = [
            {'user_id': 1, 'username': 'cipher_null', 'solved': 7, 'time_taken': 2*3600+14*60+55, 'time_taken_str': '2:14:55'},
            {'user_id': 2, 'username': 'voidwalker_x', 'solved': 6, 'time_taken': 3*3600+5*60+12, 'time_taken_str': '3:05:12'},
            {'user_id': 3, 'username': 'obsidian_dev', 'solved': 5, 'time_taken': 4*3600+22*60+8, 'time_taken_str': '4:22:08'},
        ]
        solved_problems = []

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
        'leaderboard': leaderboard,
        'tags': tags,
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
        
        if is_custom:
            custom_input = data.get('custom_input', '')
            
            # Create a mock TestCase-like object for the batch judge
            class MockTestCase:
                def __init__(self, id, input_data):
                    self.id = id
                    self.input_data = input_data
                    self.expected_output = ''
            
            results = judge_problem(code, language, [MockTestCase('custom', custom_input)], stop_on_fail=False)
            return JsonResponse({'ok': True, 'results': results, 'type': 'custom', 'custom_input': custom_input})
            
        else:
            # Retrieve sample test cases
            sample_cases = problem.testcases.filter(is_sample=True).order_by('id')
            if not sample_cases.exists():
                return JsonResponse({'ok': False, 'error': 'No sample test cases configured.'})
                
            # Evaluate without stopping on first failure so user sees all samples
            results = judge_problem(code, language, sample_cases, stop_on_fail=False)
            return JsonResponse({'ok': True, 'results': results, 'type': 'run'})
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
        
        # Evaluate against ALL test cases
        all_cases = problem.testcases.all().order_by('id')
        if not all_cases.exists():
            submission.status = 'RE'
            submission.save()
            return JsonResponse({'ok': False, 'error': 'No test cases configured for this problem'})
            
        results = judge_problem(code, language, all_cases, stop_on_fail=False)
        
        # Calculate execution stats
        max_time = 0.0
        max_mem = 0
        passed_count = 0
        total_count = all_cases.count()
        
        for r in results:
            if r['status'] == 'pass':
                passed_count += 1
            try:
                t = float(r.get('time', '0s').replace('s', ''))
                if t > max_time: max_time = t
            except ValueError:
                pass
            m = r.get('mem_kb', 0)
            if m > max_mem: max_mem = m

        # Determine final status
        if total_count == 0:
             final_status = 'RE'
             is_accepted = False
        elif passed_count == total_count:
             final_status = 'AC'
             is_accepted = True
        elif passed_count > 0:
             final_status = 'PARTIAL'
             is_accepted = False
        else:
             is_accepted = False
             first_fail = next((r for r in results if r['status'] != 'pass'), None)
             if first_fail:
                 reverse_map = {'WRONG ANSWER': 'WA', 'TIME LIMIT': 'TLE', 'RUNTIME ERROR': 'RE', 'COMPILE ERROR': 'CE'}
                 final_status = reverse_map.get(first_fail['label'], 'RE')
             else:
                 final_status = 'RE'
                 
        # Calculate Score
        cp = ContestProblem.objects.filter(contest=contest, problem=problem).first()
        points_available = cp.points if cp else 0
        base_score = (passed_count / total_count) * points_available if total_count > 0 else 0
        
        # Calculate Time & Penalties
        session = UserProblemSession.objects.filter(user=request.user, contest=contest, problem=problem).first()
        time_diff_minutes = (timezone.now() - session.first_opened_at).total_seconds() / 60.0 if session else 0.0
        
        # Count previous non-AC submissions for this problem to apply penalty
        failed_count = Submission.objects.filter(
            user=request.user, contest=contest, problem=problem
        ).exclude(id=submission.id).exclude(status__in=['AC', 'PARTIAL']).count()
        
        penalty_time = failed_count * contest.penalty_minutes
        
        submission.status = final_status
        submission.is_accepted = is_accepted
        submission.score_awarded = base_score
        submission.total_time_taken = time_diff_minutes + penalty_time
        submission.execution_time = max_time
        submission.memory_used = max_mem
        submission.save()
        
        # Update Profile Score (only add the difference if they improved)
        from django.db.models import Max
        best_previous = Submission.objects.filter(
            user=request.user, contest=contest, problem=problem
        ).exclude(id=submission.id).aggregate(Max('score_awarded'))['score_awarded__max']
        
        best_previous = best_previous or 0.0
        
        if base_score > best_previous:
            diff = base_score - best_previous
            profile = request.user.profile
            profile.total_score += int(diff)
            profile.save()
        
        # Scrub hidden test cases before returning
        for idx, tc in enumerate(all_cases):
            if not tc.is_sample:
                # results is 0-indexed, up to len(results)
                if idx < len(results):
                    results[idx]['expected'] = 'Hidden Test Case'
                    results[idx]['stdout'] = 'Hidden Test Case Output'
            
        return JsonResponse({'ok': True, 'results': results, 'type': 'submit'})
    else:
        return JsonResponse({'ok': False, 'error': 'Invalid action type'}, status=400)


@login_required
def submission_history_api(request, contest_id, problem_id):
    """Returns JSON history of user's submissions for a specific problem."""
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
