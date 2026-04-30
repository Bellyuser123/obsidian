from django.contrib import admin
from .models import (
    Profile, Language, Problem, ProblemRule, Contest, 
    ContestProblem, TestCase, UserProblemSession, Submission
)

class ProfileAdmin(admin.ModelAdmin):
    list_display = ('get_username', 'full_name', 'roll_no', 'get_email', 'total_score')
    search_fields = ('full_name', 'roll_no', 'user__username', 'user__email')
    list_filter = ('total_score',)

    def get_username(self, obj):
        return obj.user.username
    get_username.short_description = 'Username'

    def get_email(self, obj):
        return obj.user.email
    get_email.short_description = 'Email Address'


class LanguageAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'ace_mode', 'extension')
    prepopulated_fields = {'slug': ('name',)}


class TestCaseInline(admin.TabularInline):
    model = TestCase
    extra = 1
    fields = ('input_data', 'expected_output', 'is_sample', 'explanation')


class ProblemRuleInline(admin.TabularInline):
    model = ProblemRule
    extra = 1


class ProblemAdmin(admin.ModelAdmin):
    list_display = ('title', 'is_special_judge', 'get_contests')
    search_fields = ('title', 'statement')
    list_filter = ('is_special_judge', 'allowed_languages')
    inlines = [TestCaseInline, ProblemRuleInline]
    filter_horizontal = ('allowed_languages',)

    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'statement', 'input_format', 'output_format', 'constraints')
        }),
        ('Advanced Options', {
            'fields': ('is_special_judge', 'special_judge_script', 'allowed_languages'),
            'classes': ('collapse',)
        }),
    )

    class Media:
        js = ('js/admin_filter.js',)

    def get_contests(self, obj):
        return ", ".join([c.name for c in obj.contests.all()])
    get_contests.short_description = 'Linked Contests'


class ContestProblemInline(admin.TabularInline):
    model = ContestProblem
    extra = 1


class ContestAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time', 'passkey', 'prize')
    search_fields = ('name', 'description', 'tags')
    list_filter = ('start_time', 'end_time')
    inlines = [ContestProblemInline]


class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'contest', 'problem', 'language', 'status', 'is_accepted', 'time_submitted')
    list_filter = ('status', 'is_accepted', 'language', 'contest')
    search_fields = ('user__username', 'problem__title', 'code')
    readonly_fields = ('time_submitted',)


class UserProblemSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'contest', 'problem', 'first_opened_at')
    list_filter = ('contest', 'first_opened_at')
    search_fields = ('user__username', 'problem__title')


# Register all models
admin.site.register(Profile, ProfileAdmin)
admin.site.register(Language, LanguageAdmin)
admin.site.register(Problem, ProblemAdmin)
# admin.site.register(ProblemRule) # Can be registered separately or just via Inline
admin.site.register(Contest, ContestAdmin)
# admin.site.register(TestCase)    # Usually managed via Inline, but good to have
admin.site.register(Submission, SubmissionAdmin)
# admin.site.register(UserProblemSession, UserProblemSessionAdmin)
# admin.site.register(ContestProblem) # Managed via Inline but registered for direct access
