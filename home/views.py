from django.db import models
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from .models import Profile
from django.contrib.auth import logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Contest, ContestProblem, Language, Problem, TestCase
from .models import Submission, UserProblemSession, ContestParticipation, ViolationLog
from .utils import judge_problem
from .rule_checker import check_rules
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.urls import reverse
from django.core.cache import cache
from .tasks import judge_submission, run_code_task
import json
from django.views.decorators.http import require_POST

def auth_view(request):
    if request.method == "POST":
        if "register" in request.POST:
            username = request.POST.get('username')
            roll_no = request.POST.get('roll_no')
            email = request.POST.get('email')
            full_name = request.POST.get('full_name')

            # 1. Check if Username already exists
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username is already taken.")
                return render(request, 'home/register.html')

            # 2. Check if Roll No already exists
            if Profile.objects.filter(roll_no=roll_no).exists():
                messages.error(request, f"Roll No. {roll_no} is already registered.")
                return render(request, 'home/register.html')

            # 3. Check if Email already exists
            if User.objects.filter(email__iexact=email).exists():
                messages.error(request, f"Email {email} is already registered.")
                return render(request, 'home/register.html')

            # 4. Create inactive user and trigger OTP
            try:
                name_parts = (full_name or '').split(' ', 1)
                first_name = name_parts[0]
                last_name = name_parts[1] if len(name_parts) > 1 else ''

                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=request.POST.get('password'),
                    first_name=first_name,
                    last_name=last_name,
                    is_active=False
                )
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.full_name = full_name
                profile.roll_no = roll_no
                profile.is_profile_complete = True
                profile.save()

                from .utils import send_otp_email
                send_otp_email(user)
                request.session['pending_user_id'] = user.id

                messages.success(request, f"Account created! A 6-digit verification code was sent to {user.email}.")
                return redirect('verify_otp')
            except Exception as e:
                messages.error(request, f"Failed to register account: {str(e)}")

        elif "login" in request.POST:
            u_name = request.POST.get('username')
            p_word = request.POST.get('password')
            user = authenticate(request, username=u_name, password=p_word)
            if user is not None:
                login(request, user)
                return redirect('check_profile_status')
            else:
                messages.error(request, "Invalid username or password.")
                return render(request, 'home/register.html')
    return render(request, 'home/register.html')


from django.conf import settings
from django.contrib.auth.views import PasswordResetView
import os

class CustomPasswordResetView(PasswordResetView):
    template_name = 'home/password_reset_form.html'
    email_template_name = 'home/password_reset_email.html'
    subject_template_name = 'home/password_reset_subject.txt'

    def form_valid(self, form):
        email = form.cleaned_data["email"]
        users = User.objects.filter(email__iexact=email)
        for user in users:
            if not user.has_usable_password():
                messages.error(
                    self.request,
                    f"The account associated with {email} was created using Google or GitHub. Please log in using your social account."
                )
                return self.form_invalid(form)

        domain = os.getenv('SITE_DOMAIN', self.request.get_host())
        protocol = 'https' if self.request.is_secure() or not settings.DEBUG else 'http'
        extra_email_context = {
            'domain': domain,
            'protocol': protocol,
            'site_name': 'Obsidian Arena'
        }
        opts = {
            'use_https': self.request.is_secure(),
            'token_generator': self.token_generator,
            'from_email': self.from_email,
            'email_template_name': self.email_template_name,
            'subject_template_name': self.subject_template_name,
            'request': self.request,
            'html_email_template_name': self.email_template_name,
            'extra_email_context': extra_email_context,
            'domain_override': domain,
        }
        form.save(**opts)
        return redirect(self.get_success_url())


from django.contrib.auth.views import PasswordResetConfirmView
from django.urls import reverse_lazy

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'home/password_reset_confirm.html'
    success_url = reverse_lazy('auth')

    def form_valid(self, form):
        messages.success(self.request, "Your password has been successfully updated! Please log in with your new password.")
        return super().form_valid(form)


def verify_otp_view(request):
    pending_user_id = request.session.get('pending_user_id')
    if not pending_user_id:
        messages.error(request, "No pending verification session. Please sign up or log in.")
        return redirect('auth')

    try:
        user = User.objects.get(id=pending_user_id)
    except User.DoesNotExist:
        messages.error(request, "User not found. Please sign up again.")
        return redirect('auth')

    if request.method == 'POST':
        otp_input = request.POST.get('otp_code', '').strip()
        from .models import EmailOTP
        try:
            email_otp = EmailOTP.objects.get(user=user)
            if email_otp.otp_code == otp_input and email_otp.is_valid():
                user.is_active = True
                user.save()
                email_otp.delete()
                del request.session['pending_user_id']
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, "Email verified successfully! Welcome to Obsidian Arena.")
                return redirect('check_profile_status')
            else:
                messages.error(request, "Invalid or expired 6-digit verification code. Please try again or click Resend.")
        except EmailOTP.DoesNotExist:
            messages.error(request, "No OTP found. Please request a new verification code.")

    return render(request, 'home/verify_otp.html', {'user': user})


def resend_otp_view(request):
    pending_user_id = request.session.get('pending_user_id')
    if not pending_user_id:
        messages.error(request, "Session expired. Please sign up again.")
        return redirect('auth')

    try:
        user = User.objects.get(id=pending_user_id)
        from .utils import send_otp_email
        send_otp_email(user)
        messages.success(request, f"A fresh 6-digit verification code has been sent to {user.email}.")
    except Exception as e:
        messages.error(request, f"Failed to resend code: {str(e)}")

    return redirect('verify_otp')


@login_required
def check_profile_status(request):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=request.user, is_profile_complete=False)

    roll = profile.roll_no
    email = request.user.email
    full_name = profile.full_name or request.user.get_full_name()

    if not roll or not profile.is_profile_complete or not email or not full_name:
        return redirect('complete_profile')
    return redirect('dashboard')


@login_required
def complete_profile(request):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=request.user, is_profile_complete=False)

    roll = profile.roll_no
    email = request.user.email
    full_name = profile.full_name or request.user.get_full_name()

    if profile.is_profile_complete and roll and email and full_name:
        return redirect('dashboard')

    if request.method == 'POST':
        new_full_name = request.POST.get('full_name', '').strip()
        new_username = request.POST.get('username', '').strip()
        new_roll = request.POST.get('roll_no', '').strip() or request.POST.get('roll_number', '').strip()
        new_email = request.POST.get('email', '').strip()

        if not new_full_name:
            messages.error(request, "Full Name is required.")
            return render(request, 'home/complete_profile.html', {'profile': profile})

        if not new_username:
            messages.error(request, "Username cannot be empty.")
            return render(request, 'home/complete_profile.html', {'profile': profile})

        if not new_roll:
            messages.error(request, "Roll Number is required.")
            return render(request, 'home/complete_profile.html', {'profile': profile})

        if not new_email:
            messages.error(request, "Email Address is required.")
            return render(request, 'home/complete_profile.html', {'profile': profile})

        # Check username uniqueness if changed
        if User.objects.filter(username=new_username).exclude(id=request.user.id).exists():
            messages.error(request, f"Username '{new_username}' is already taken.")
            return render(request, 'home/complete_profile.html', {'profile': profile})

        # Check email uniqueness if changed
        if User.objects.filter(email__iexact=new_email).exclude(id=request.user.id).exists():
            messages.error(request, f"Email address '{new_email}' is already registered with another account.")
            return render(request, 'home/complete_profile.html', {'profile': profile})

        # Check roll_no uniqueness if changed
        if Profile.objects.filter(roll_no=new_roll).exclude(user=request.user).exists():
            messages.error(request, f"Roll Number '{new_roll}' is already registered.")
            return render(request, 'home/complete_profile.html', {'profile': profile})

        # Update User first & last name
        name_parts = new_full_name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        request.user.username = new_username
        request.user.email = new_email
        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.save()

        profile.full_name = new_full_name
        profile.roll_no = new_roll
        profile.is_profile_complete = True
        profile.save()

        # Also sync allauth EmailAddress model if installed
        try:
            from allauth.account.models import EmailAddress
            email_address, created = EmailAddress.objects.get_or_create(
                user=request.user,
                email=new_email,
                defaults={'primary': True, 'verified': False}
            )
            if not email_address.primary:
                EmailAddress.objects.filter(user=request.user).update(primary=False)
                email_address.primary = True
                email_address.save()
        except Exception:
            pass

        messages.success(request, "Profile completed successfully!")
        return redirect('dashboard')

    return render(request, 'home/complete_profile.html', {'profile': profile})


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


def check_disqualified(user, contest):
    if not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return False
    participation = ContestParticipation.objects.filter(user=user, contest=contest).first()
    if participation and participation.is_disqualified:
        return True
    return False


@login_required
def contest_lobby(request, contest_id):
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
def problem_ide_view(request, contest_id, problem_id):
    """Render the problem IDE page where the user can solve and upload code."""
    contest = get_object_or_404(Contest, id=contest_id)
    
    if check_disqualified(request.user, contest):
        return render(request, 'home/disqualified.html', {'contest': contest}, status=403)
        
    if request.user.is_authenticated:
        ContestParticipation.objects.get_or_create(user=request.user, contest=contest)
        
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


@login_required
@require_POST
def log_violation(request, contest_id):
    contest = get_object_or_404(Contest, id=contest_id)
    if not contest.enable_anti_cheat:
        return JsonResponse({'ok': True, 'action': 'NONE'})

    violation_type = request.POST.get('violation_type')
    details = request.POST.get('details', '')

    # Check if they are already disqualified
    participation, created = ContestParticipation.objects.get_or_create(user=request.user, contest=contest)
    if participation.is_disqualified:
        return JsonResponse({'action': 'BAN'})

    # Count current logs for user in this contest
    existing_strikes = ViolationLog.objects.filter(user=request.user, contest=contest).count()
    strike_number = existing_strikes + 1

    ViolationLog.objects.create(
        user=request.user,
        contest=contest,
        violation_type=violation_type,
        strike_number=strike_number,
        details=details
    )

    if strike_number >= 3:
        participation.is_disqualified = True
        participation.save()
        return JsonResponse({'action': 'BAN'})
    else:
        return JsonResponse({'action': 'WARN', 'current_strikes': strike_number})


@login_required
def unban_self(request, contest_id):
    from .models import Contest, ContestParticipation, ViolationLog
    contest = get_object_or_404(Contest, id=contest_id)
    
    participation = ContestParticipation.objects.filter(user=request.user, contest=contest).first()
    if participation:
        participation.is_disqualified = False
        participation.save()
        
    profile = getattr(request.user, 'profile', None)
    if profile:
        profile.is_disqualified = False
        profile.save()

    ViolationLog.objects.filter(user=request.user, contest=contest).delete()
    
    messages.success(request, "Your proctor strikes and disqualification have been reset successfully.")
    return redirect('contest_lobby', contest_id=contest.id)

