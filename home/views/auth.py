"""
Authentication & Profile Management Views
Handles registration, login/logout, OTP email verification, password reset workflows,
and profile completion.
"""

from typing import Optional, Union, Dict, Any
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse_lazy

from home.models import Profile, EmailOTP
from home.utils import send_otp_email


def auth_view(request: HttpRequest) -> HttpResponse:
    """
    Handles user login and registration.
    Inactive users are created upon valid registration and routed to OTP verification.
    """
    if request.method == "POST":
        if "register" in request.POST:
            username: str = request.POST.get('username', '').strip()
            roll_no: str = request.POST.get('roll_no', '').strip()
            email: str = request.POST.get('email', '').strip()
            full_name: str = request.POST.get('full_name', '').strip()

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

                send_otp_email(user)
                request.session['pending_user_id'] = user.id

                messages.success(request, f"Account created! A 6-digit verification code was sent to {user.email}.")
                return redirect('verify_otp')
            except Exception as e:
                messages.error(request, f"Failed to register account: {str(e)}")

        elif "login" in request.POST:
            u_name: str = request.POST.get('username', '').strip()
            p_word: str = request.POST.get('password', '')
            user = authenticate(request, username=u_name, password=p_word)
            if user is not None:
                login(request, user)
                return redirect('check_profile_status')
            else:
                messages.error(request, "Invalid username or password.")
                return render(request, 'home/register.html')

    return render(request, 'home/register.html')


class CustomPasswordResetView(PasswordResetView):
    """
    Custom password reset view handling domain/protocol discovery
    and social auth account restrictions.
    """
    template_name = 'home/password_reset_form.html'
    email_template_name = 'home/password_reset_email.html'
    subject_template_name = 'home/password_reset_subject.txt'

    def form_valid(self, form: Any) -> HttpResponse:
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


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    """
    Custom confirmation view confirming password resets with status messaging.
    """
    template_name = 'home/password_reset_confirm.html'
    success_url = reverse_lazy('auth')

    def form_valid(self, form: Any) -> HttpResponse:
        messages.success(self.request, "Your password has been successfully updated! Please log in with your new password.")
        return super().form_valid(form)


def verify_otp_view(request: HttpRequest) -> HttpResponse:
    """
    Validates user 6-digit OTP code against EmailOTP ledger.
    Upon verification, sets user to active, logs them in, and deletes OTP.
    """
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


def resend_otp_view(request: HttpRequest) -> HttpResponseRedirect:
    """
    Regenerates and dispatches a fresh 6-digit verification OTP.
    """
    pending_user_id = request.session.get('pending_user_id')
    if not pending_user_id:
        messages.error(request, "Session expired. Please sign up again.")
        return redirect('auth')

    try:
        user = User.objects.get(id=pending_user_id)
        send_otp_email(user)
        messages.success(request, f"A fresh 6-digit verification code has been sent to {user.email}.")
    except Exception as e:
        messages.error(request, f"Failed to resend code: {str(e)}")

    return redirect('verify_otp')


@login_required
def check_profile_status(request: HttpRequest) -> HttpResponseRedirect:
    """
    Redirects user to complete-profile if profile attributes are missing.
    """
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


def _sync_allauth_email(user: User, email: str) -> None:
    """
    Helper to synchronize Allauth EmailAddress model if installed.
    """
    try:
        from allauth.account.models import EmailAddress
        email_address, _ = EmailAddress.objects.get_or_create(
            user=user,
            email=email,
            defaults={'primary': True, 'verified': False}
        )
        if not email_address.primary:
            EmailAddress.objects.filter(user=user).update(primary=False)
            email_address.primary = True
            email_address.save()
    except Exception:
        pass


@login_required
def complete_profile(request: HttpRequest) -> HttpResponse:
    """
    Ensures contestant profile contains full name, roll number, and valid email.
    """
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

        _sync_allauth_email(request.user, new_email)

        messages.success(request, "Profile completed successfully!")
        return redirect('dashboard')

    return render(request, 'home/complete_profile.html', {'profile': profile})


def logout_view(request: HttpRequest) -> HttpResponseRedirect:
    """
    Logs out the authenticated user and redirects to home page.
    """
    logout(request)
    return redirect('main-home')


def profile_view(request: HttpRequest) -> HttpResponse:
    """
    Renders user profile overview.
    """
    return render(request, 'home/profile.html')
