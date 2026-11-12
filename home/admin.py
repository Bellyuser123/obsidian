from django.contrib import admin
from django.utils import timezone
from django.utils.text import slugify

from .models import (
    Profile, Language, Problem, ProblemRule, Contest, 
    ContestProblem, TestCase, UserProblemSession, Submission, CodeStub,
    ContestParticipation, ViolationLog, Organization, OrganizationMembership,
    HostApplication, ContestResult, AuditLog
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
    list_display = ('name', 'slug', 'docker_image', 'extension')
    prepopulated_fields = {'slug': ('name',)}
    fieldsets = (
        ('Basic Info', {'fields': ('name', 'slug', 'ace_mode', 'extension')}),
        ('Execution Configuration', {'fields': ('docker_image', 'compile_command', 'run_command')}),
    )


class TestCaseInline(admin.TabularInline):
    model = TestCase
    extra = 1
    fields = (
        'input_data', 'input_file', 'input_filename', 'input_format',
        'expected_output', 'output_file', 'output_filename', 'output_format',
        'is_sample', 'explanation', 'weight'
    )


class ProblemRuleInline(admin.TabularInline):
    model = ProblemRule
    extra = 1


class CodeStubInline(admin.TabularInline):
    model = CodeStub
    extra = 1


class ProblemAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'created_by', 'visibility', 'is_special_judge', 'get_contests')
    search_fields = ('title', 'statement', 'organization__name', 'created_by__username')
    list_filter = ('visibility', 'is_special_judge', 'allowed_languages')
    raw_id_fields = ('created_by', 'organization')
    inlines = [CodeStubInline, TestCaseInline, ProblemRuleInline]
    filter_horizontal = ('allowed_languages',)

    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'organization', 'created_by', 'visibility', 'statement', 'input_format', 'output_format', 'constraints')
        }),
        ('Advanced Options', {
            'fields': ('is_special_judge', 'special_judge_script', 'allowed_languages'),
            'classes': ('collapse',)
        }),
    )

    class Media:
        js = ('home/js/admin_filter.js',)

    def get_contests(self, obj):
        return ", ".join([c.name for c in obj.contests.all()])
    get_contests.short_description = 'Linked Contests'


class ContestProblemInline(admin.TabularInline):
    model = ContestProblem
    extra = 1


class ContestAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'organization', 'host', 'visibility', 'lifecycle_status',
        'start_time', 'end_time', 'passkey', 'is_team_contest', 'enable_anti_cheat', 'prize'
    )
    list_editable = ('enable_anti_cheat',)
    search_fields = ('name', 'description', 'tags', 'host__username', 'organization__name')
    list_filter = ('visibility', 'lifecycle_status', 'start_time', 'end_time', 'is_team_contest', 'enable_anti_cheat')
    raw_id_fields = ('host', 'organization')
    inlines = [ContestProblemInline]
    actions = ['reset_banned_contestants_action', 'restart_contest_action']

    @admin.action(description="Reset banned contestants and violation logs for selected contests")
    def reset_banned_contestants_action(self, request, queryset):
        for contest in queryset:
            contest.reset_banned_list()
        self.message_user(request, "Selected contest banned lists have been reset successfully.")

    @admin.action(description="Restart contest (reset bans and strikes)")
    def restart_contest_action(self, request, queryset):
        for contest in queryset:
            contest.restart_contest()
        self.message_user(request, "Selected contests restarted and banned lists reset.")


class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'contest', 'problem', 'language', 'status', 'is_accepted', 'is_staff_test', 'time_submitted')
    list_filter = ('status', 'is_accepted', 'is_staff_test', 'language', 'contest')
    search_fields = ('user__username', 'problem__title', 'code')
    readonly_fields = ('user', 'contest', 'problem', 'language', 'code', 'status', 'is_accepted', 'is_staff_test', 'time_submitted')

    def has_view_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return True


class UserProblemSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'contest', 'problem', 'first_opened_at')
    list_filter = ('contest', 'first_opened_at')
    search_fields = ('user__username', 'problem__title')


class ViolationLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'contest', 'violation_type', 'strike_number')
    list_filter = ('contest', 'violation_type', 'strike_number')
    search_fields = ('user__username', 'details')
    readonly_fields = ('user', 'contest', 'violation_type', 'strike_number', 'timestamp', 'details')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return True


class ContestParticipationAdmin(admin.ModelAdmin):
    list_display = ('user', 'contest', 'role', 'division', 'is_disqualified', 'registered_at')
    list_filter = ('contest', 'role', 'division', 'is_disqualified')
    search_fields = ('user__username', 'contest__name', 'division')


class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'org_type', 'verification_status', 'created_by', 'created_at')
    list_filter = ('org_type', 'verification_status', 'created_at')
    search_fields = ('name', 'slug', 'created_by__username')
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ('created_by',)


class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'participant_id', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active', 'joined_at')
    search_fields = ('user__username', 'organization__name', 'participant_id')
    raw_id_fields = ('user', 'organization')


class HostApplicationAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'user', 'org_type', 'status', 'reviewed_by', 'reviewed_at', 'created_at')
    list_filter = ('status', 'org_type', 'created_at')
    search_fields = ('organization_name', 'user__username', 'official_email_or_proof')
    raw_id_fields = ('user', 'reviewed_by')
    actions = ['approve_selected_applications']

    @admin.action(description="Approve selected host applications and provision organizations")
    def approve_selected_applications(self, request, queryset):
        now = timezone.now()
        count = 0
        for app in queryset.filter(status='PENDING'):
            app.status = 'APPROVED'
            app.reviewed_by = request.user
            app.reviewed_at = now
            app.save()

            base_slug = slugify(app.organization_name) or 'org'
            slug = base_slug
            idx = 1
            while Organization.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{idx}"
                idx += 1

            org = Organization.objects.create(
                name=app.organization_name,
                slug=slug,
                org_type=app.org_type,
                verification_status='APPROVED',
                created_by=app.user,
            )

            OrganizationMembership.objects.create(
                user=app.user,
                organization=org,
                role='OWNER',
                is_active=True,
            )

            AuditLog.objects.create(
                actor=request.user,
                organization=org,
                action='HOST_APPLICATION_APPROVED',
                details=f"Host application for '{app.organization_name}' approved. Organization '{org.name}' ({org.slug}) provisioned."
            )
            count += 1
        self.message_user(request, f"{count} host applications approved and provisioned.")


class ContestResultAdmin(admin.ModelAdmin):
    list_display = ('overall_rank', 'user', 'contest', 'division', 'problems_solved', 'final_score', 'total_time_seconds', 'finalized_at')
    list_filter = ('contest', 'division', 'finalized_at')
    search_fields = ('user__username', 'contest__name', 'roll_no')
    raw_id_fields = ('user', 'contest')


class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'organization', 'contest')
    list_filter = ('action', 'created_at')
    search_fields = ('actor__username', 'action', 'details', 'organization__name', 'contest__name')
    readonly_fields = ('actor', 'organization', 'contest', 'action', 'details', 'created_at')
    raw_id_fields = ('actor', 'organization', 'contest')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Register all models
admin.site.register(Profile, ProfileAdmin)
admin.site.register(Language, LanguageAdmin)
admin.site.register(Problem, ProblemAdmin)
admin.site.register(Contest, ContestAdmin)
admin.site.register(Submission, SubmissionAdmin)
admin.site.register(ViolationLog, ViolationLogAdmin)
admin.site.register(ContestParticipation, ContestParticipationAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(OrganizationMembership, OrganizationMembershipAdmin)
admin.site.register(HostApplication, HostApplicationAdmin)
admin.site.register(ContestResult, ContestResultAdmin)
admin.site.register(AuditLog, AuditLogAdmin)
