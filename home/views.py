from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from .models import Profile
from django.contrib.auth import logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Contest, ContestProblem
from .models import Submission
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.urls import reverse


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
        subs = Submission.objects.filter(contest=contest, is_accepted=True).select_related('user')
        if subs.exists():
            # aggregate per user
            from django.db.models import Count, Max
            user_stats = subs.values('user__id', 'user__username').annotate(solved=Count('problem'), latest=Max('time_submitted'))
            for u in user_stats:
                latest_dt = u['latest']
                # compute time taken from contest start to latest accepted submission
                time_taken = int((latest_dt - contest.start_time).total_seconds()) if latest_dt and contest.start_time else 0
                # format as H:MM:SS or Dd H:MM:SS for long durations
                def fmt(secs):
                    if secs <= 0:
                        return '00:00:00'
                    h = secs // 3600
                    m = (secs % 3600) // 60
                    s = secs % 60
                    return f"{h}:{str(m).zfill(2)}:{str(s).zfill(2)}"

                leaderboard.append({
                    'user_id': u['user__id'],
                    'username': u['user__username'],
                    'solved': u['solved'],
                    'latest': latest_dt,
                    'time_taken': time_taken,
                    'time_taken_str': fmt(time_taken),
                })
            # sort by solved DESC, then latest ASC (earlier latest submission means faster)
            leaderboard.sort(key=lambda r: (-r['solved'], r['latest']))

        # user's solved problems for marking rows
        solved_problems = list(subs.filter(user=request.user).values_list('problem__id', flat=True)) if request.user.is_authenticated else []
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
    context = {
        'contest': contest,
        'problem': problem,
        'contest_problem': cp,
    }
    return render(request, 'home/problem_ide.html', context)