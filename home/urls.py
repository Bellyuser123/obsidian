from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='main-home'),
    path('auth/', views.auth_view, name='auth'),
    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('resend-otp/', views.resend_otp_view, name='resend_otp'),

    # Password Reset URLs
    path('password-reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='home/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='home/password_reset_complete.html'), name='password_reset_complete'),

    path('check-profile/', views.check_profile_status, name='check_profile_status'),
    path('complete-profile/', views.complete_profile, name='complete_profile'),
    path('profile/', views.profile_view, name='profile'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('contest/<int:contest_id>/enter/', views.enter_contest, name='enter_contest'),
    path('contest/<int:contest_id>/lobby/', views.contest_lobby, name='contest_lobby'),
    path('contest/<int:contest_id>/problem/<int:problem_id>/ide/', views.problem_ide_view, name='problem_ide'),
    path('contest/<int:contest_id>/problem/<int:problem_id>/submit/', views.handle_submission, name='handle_submission'),
    path('contest/<int:contest_id>/problem/<int:problem_id>/submissions_api/', views.submission_history_api, name='submission_history_api'),
    path('submission/<int:submission_id>/status/', views.submission_status_api, name='submission_status_api'),
    path('run/<int:problem_id>/status/', views.run_status_api, name='run_status_api'),
    path('contest/<int:contest_id>/violation/', views.log_violation, name='log_violation'),
    path('contest/<int:contest_id>/unban/', views.unban_self, name='unban_self'),
]
