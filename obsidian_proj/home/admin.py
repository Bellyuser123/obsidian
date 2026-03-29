from django.contrib import admin
from .models import Profile, Contest, ContestProblem, Problem, TestCase


class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user__username', 'full_name', 'roll_no', 'get_email', 'total_score')
    search_fields = ('full_name', 'roll_no', 'user__username')

    def get_email(self, obj):
        return obj.user.email

    get_email.short_description = 'Email Address'


class ProblemInline(admin.TabularInline):
    model = Problem
    extra = 1


class ContestProblemInline(admin.TabularInline):
    model = ContestProblem
    extra = 1


class ContestAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time')
    inlines = [ContestProblemInline]


class TestCaseInline(admin.TabularInline):
    model = TestCase
    extra = 2


class ProblemAdmin(admin.ModelAdmin):
    list_display = ('title', 'get_contests')
    inlines = [TestCaseInline]

    def get_contests(self, obj):
        return ", ".join([c.name for c in obj.contests.all()])
    get_contests.short_description = 'Linked Contests'


admin.site.register(Profile, ProfileAdmin)
admin.site.register(Contest, ContestAdmin)
admin.site.register(Problem, ProblemAdmin)