from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='main-home'),
    path('auth/', views.auth_view, name='auth'),
    path('profile/', views.profile_view, name='profile'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('contest/<int:contest_id>/enter/', views.enter_contest, name='enter_contest'),
    path('contest/<int:contest_id>/lobby/', views.contest_lobby, name='contest_lobby'),
    path('contest/<int:contest_id>/problem/<int:problem_id>/ide/', views.problem_ide_view, name='problem_ide'),
    path('contest/<int:contest_id>/problem/<int:problem_id>/submit/', views.submit_code, name='submit_code'),
    path('submission/<int:submission_id>/status/', views.get_submission_status, name='submission_status'),
]