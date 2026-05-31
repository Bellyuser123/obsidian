import re
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError



class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=100)
    roll_no = models.CharField(max_length=20, unique=True)
    total_score = models.IntegerField(default=0)
    is_disqualified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.roll_no}"


# --- NEW SUPPORT MODELS ---
class Language(models.Model):
    """Supported languages for the IDE."""
    name = models.CharField(max_length=50) # e.g. Python 3.12
    slug = models.SlugField(unique=True)   # e.g. python3
    ace_mode = models.CharField(max_length=50, help_text="Used for IDE syntax highlighting")
    extension = models.CharField(max_length=10, default=".py")
    
    # Execution Rules
    docker_image = models.CharField(max_length=100, default="python:3.12-slim", help_text="Docker image to use (e.g. gcc:latest)")
    compile_command = models.CharField(max_length=255, blank=True, null=True, help_text="Optional. Use {filename} for source file.")
    run_command = models.CharField(max_length=255, default="python {filename}", help_text="Command to run. Use {filename} for source file.")
    def __str__(self): return self.name


class Problem(models.Model):
    title = models.CharField(max_length=200)
    statement = models.TextField()
    input_format = models.TextField()
    output_format = models.TextField()
    constraints = models.TextField()

    # NEW: Advanced Judging Logic
    is_special_judge = models.BooleanField(default=False,
                                           help_text="Check output via custom logic rather than exact match")
    special_judge_script = models.TextField(blank=True, null=True, help_text="Python script to validate output")
    allowed_languages = models.ManyToManyField(Language, related_name='problems')

    def __str__(self):
        return self.title


class CodeStub(models.Model):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='stubs')
    language = models.ForeignKey(Language, on_delete=models.CASCADE)
    starter_code = models.TextField(blank=True, default="", help_text="Starter template boilerplate")

    class Meta:
        unique_together = ('problem', 'language')

    def __str__(self):
        return f"Stub for {self.problem.title} in {self.language.name}"


class ProblemRule(models.Model):
    """The 'Custom Checker' logic for mandatory/forbidden constructs."""
    RULE_TYPES = [
        ('MANDATORY', 'Must Use (Exact Token)'),
        ('FORBIDDEN', 'Must Not Use (Exact Token)'),
        ('STRUCTURAL', 'Structural Check (e.g. recursion, inheritance, lines_X)'),
    ]
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='rules')
    language = models.ForeignKey('Language', on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank to apply to all languages")
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES)
    keyword = models.CharField(
        max_length=100, 
        help_text="Exact token (e.g. 'set') OR Structure (e.g. 'recursion', 'inheritance', 'lines_5')"
    )
    error_message = models.CharField(max_length=255, help_text="User-friendly error if rule is broken")

    def __str__(self): return f"{self.rule_type}: {self.keyword}"


class Contest(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    passkey = models.CharField(max_length=50, blank=True, null=True)
    tags = models.CharField(max_length=200, blank=True, help_text="Comma-separated tags (e.g. AI, WEB, DSA)")
    prize = models.CharField(max_length=100, blank=True, help_text="Prize pool info")
    penalty_minutes = models.IntegerField(default=10, help_text="Penalty in minutes added per wrong submission")
    is_team_contest = models.BooleanField(default=False, help_text="Is this a team participation contest?")
    enable_anti_cheat = models.BooleanField(default=True, help_text="Master toggle for the anti-cheat proctoring framework.")

    problems = models.ManyToManyField(Problem, through='ContestProblem', related_name='contests')

    def __str__(self):
        return self.name


class ContestProblem(models.Model):
    # This is the "Through Table" that stores the unique points
    DIFFICULTY_CHOICES = [
        ('EASY', 'Easy'),
        ('MEDIUM', 'Medium'),
        ('HARD', 'Hard'),
    ]

    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    points = models.IntegerField(default=10)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='EASY')

    class Meta:
        # Prevents adding the same problem to the same contest twice
        unique_together = ('contest', 'problem')

    def __str__(self):
        return f"{self.contest.name} - {self.problem.title} ({self.points} pts, {self.difficulty})"


class TestCase(models.Model):
    FORMAT_CHOICES = [
        ('EDITOR', 'Standard Text Stream'),
        ('UPLOAD', 'Physical File'),
    ]

    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='testcases')
    input_data = models.TextField(blank=True, default="", help_text="Input given to the student's program")
    expected_output = models.TextField(blank=True, default="", help_text="What the program should return")
    is_sample = models.BooleanField(default=False, help_text="Visible to students for debugging")
    explanation = models.TextField(blank=True, null=True, help_text="Explanation for sample cases")

    weight = models.IntegerField(default=1, validators=[MinValueValidator(0)])
    input_format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='EDITOR')
    output_format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='EDITOR')
    input_filename = models.CharField(max_length=100, blank=True, null=True)
    output_filename = models.CharField(max_length=100, blank=True, null=True)
    input_file = models.FileField(upload_to='testcase_inputs/', blank=True, null=True)
    output_file = models.FileField(upload_to='testcase_outputs/', blank=True, null=True)

    def clean(self):
        super().clean()
        
        # Check input_format/input_filename
        if self.input_format == 'UPLOAD':
            if not self.input_file:
                raise ValidationError({'input_file': 'An input file must be uploaded when input format is set to UPLOAD.'})
            
            import os
            if not self.input_filename and self.input_file.name:
                self.input_filename = os.path.basename(self.input_file.name)
                
            if not self.input_filename:
                raise ValidationError({'input_filename': 'Input filename is required when input format is set to UPLOAD.'})
            self._validate_filename(self.input_filename, 'input_filename')
            
        # Check output_format/output_filename
        if self.output_format == 'UPLOAD':
            if not self.output_file:
                raise ValidationError({'output_file': 'An output file must be uploaded when output format is set to UPLOAD.'})
                
            import os
            if not self.output_filename and self.output_file.name:
                self.output_filename = os.path.basename(self.output_file.name)
                
            if not self.output_filename:
                raise ValidationError({'output_filename': 'Output filename is required when output format is set to UPLOAD.'})
            self._validate_filename(self.output_filename, 'output_filename')
        else:
            if not self.expected_output:
                raise ValidationError({'expected_output': 'Expected output is required when output format is set to EDITOR.'})

    def _validate_filename(self, filename, field_name):
        if not filename:
            return
        
        # Path traversal characters
        if '/' in filename or '\\' in filename or '..' in filename:
            raise ValidationError({field_name: 'Path traversal characters are not allowed.'})
            
        # Regex boundary: ^[a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+$
        if not re.match(r'^[a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+$', filename):
            raise ValidationError({field_name: 'Filename must match strict regex pattern ^[a-zA-Z0-9_\\-]+\\.[a-zA-Z0-9]+$'})
            
        # Hidden config basenames
        lower_name = filename.lower()
        if lower_name in ['.bashrc', '.env', 'settings.py']:
            raise ValidationError({field_name: 'This filename is reserved/blocked for security reasons.'})
            
        # Script extensions
        parts = lower_name.split('.')
        ext = parts[-1] if len(parts) > 1 else ''
        if ext in ['sh', 'exe', 'bat']:
            raise ValidationError({field_name: f'Script extension .{ext} is not allowed for security reasons.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Case for {self.problem.title}"


class UserProblemSession(models.Model):
    """Tracks when a user first opened a specific problem."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    first_opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'contest', 'problem')


class Submission(models.Model):
    # Status Choices
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('AC', 'Accepted'),
        ('PARTIAL', 'Partial'),
        ('WA', 'Wrong Answer'),
        ('TLE', 'Time Limit Exceeded'),
        ('RE', 'Runtime Error'),
        ('CE', 'Compile Error'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submissions')
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name='submissions')
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='submissions')

    code = models.TextField()  # The actual code submitted
    language = models.ForeignKey('Language', on_delete=models.SET_NULL, null=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    is_accepted = models.BooleanField(default=False)
    time_submitted = models.DateTimeField(auto_now_add=True)

    # Execution Stats
    execution_time = models.FloatField(default=0.0, help_text="Seconds")
    memory_used = models.IntegerField(default=0, help_text="KB")
    error_message = models.TextField(blank=True, null=True, help_text="Compilation or Runtime errors")

    # Scoring & Timing
    score_awarded = models.FloatField(default=0.0)
    total_time_taken = models.FloatField(default=0.0, help_text="Total time to solve in minutes, including penalties")

    # NOTE: unique_together is REMOVED to allow multiple attempts

    def __str__(self):
        return f"{self.user.username} - {self.problem.title} @ {self.time_submitted} ({'AC' if self.is_accepted else 'WA'})"


class ContestParticipation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contest_participations')
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name='participations')
    is_disqualified = models.BooleanField(default=False, help_text="Designates whether the user is disqualified from this contest.")
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'contest')

    def __str__(self):
        return f"{self.user.username} in {self.contest.name} (Disqualified: {self.is_disqualified})"


class ViolationLog(models.Model):
    VIOLATION_CHOICES = [
        ('TAB_SWITCH', 'Tab Switch / Blur'),
        ('CLIPBOARD', 'Clipboard Access'),
        ('DEVTOOLS', 'DevTools Opened'),
        ('FULLSCREEN', 'Fullscreen Exited'),
        ('DOM_INJECTION', 'DOM Injection Detect'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='violations')
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name='violations')
    violation_type = models.CharField(max_length=20, choices=VIOLATION_CHOICES)
    strike_number = models.IntegerField(help_text="Strike sequence number (e.g. 1, 2, 3)")
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True, null=True, help_text="Contextual details of the violation")

    def __str__(self):
        return f"{self.user.username} - {self.violation_type} (Strike {self.strike_number}) in {self.contest.name}"
