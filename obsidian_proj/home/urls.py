from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='main-home'),
    path('auth/', views.auth_view, name='auth'),
    path('profile/', views.profile_view, name='profile'),
    path('logout/', views.logout_view, name='logout'),
]