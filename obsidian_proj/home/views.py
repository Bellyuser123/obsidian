from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from .models import Profile
from django.contrib.auth import logout
from django.contrib import messages


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
                return redirect('main-home')
            except Exception as e:
                messages.error(request, "An unexpected error occurred. Try again.")

        elif "login" in request.POST:
            user = authenticate(username=..., password=...)
            if user:
                login(request, user)
                return redirect('main-home')

    return render(request, 'home/register.html')


def logout_view(request):
    logout(request)
    return redirect('main-home')


def profile_view(request):
    return render(request, 'home/profile.html')


def home(request):
    return render(request, 'home/home.html')

