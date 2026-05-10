from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=100)
    roll_no = models.CharField(max_length=20, unique=True)
    total_score = models.IntegerField(default=0)

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
        ('MANDATORY', 'Must Use'),
        ('FORBIDDEN', 'Must Not Use'),
        ('STRUCTURAL', 'Structural Check (e.g. Recursion)'),
    ]
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='rules')
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES)
    keyword = models.CharField(max_length=100, help_text="The function/method name (e.g. 'math.sqrt' or 'for')")
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
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='testcases')
    input_data = models.TextField(help_text="Input given to the student's program")
    expected_output = models.TextField(help_text="What the program should return")
    is_sample = models.BooleanField(default=False, help_text="Visible to students for debugging")
    explanation = models.TextField(blank=True, null=True, help_text="Explanation for sample cases")

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

    # Optional: store execution time and memory for the result terminal
    execution_time = models.FloatField(default=0.0, help_text="Seconds")
    memory_used = models.IntegerField(default=0, help_text="KB")

    # NOTE: unique_together is REMOVED to allow multiple attempts

    def __str__(self):
        return f"{self.user.username} - {self.problem.title} @ {self.time_submitted} ({'AC' if self.is_accepted else 'WA'})"
