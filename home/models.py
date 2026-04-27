from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=100)
    roll_no = models.CharField(max_length=20, unique=True)
    total_score = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.roll_no}"


class Problem(models.Model):
    title = models.CharField(max_length=200)
    statement = models.TextField()
    input_format = models.TextField()
    output_format = models.TextField()
    constraints = models.TextField()

    # Note: Points are removed from here

    def __str__(self):
        return self.title


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
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    points = models.IntegerField(default=10)

    class Meta:
        # Prevents adding the same problem to the same contest twice
        unique_together = ('contest', 'problem')

    def __str__(self):
        return f"{self.contest.name} - {self.problem.title} ({self.points} pts)"


class TestCase(models.Model):
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='testcases')

    input_data = models.TextField(help_text="Input given to the student's program")
    expected_output = models.TextField(help_text="What the program should return")
    is_sample = models.BooleanField(default=False, help_text="Visible to students for debugging")
    explanation = models.TextField(blank=True, null=True, help_text="Explanation for sample cases")

    def __str__(self):
        return f"Case for {self.problem.title}"


class Submission(models.Model):
    """Minimal submission model to store accepted solutions for leaderboard.

    - user: the Django User who submitted
    - contest: the contest this submission belongs to
    - problem: the problem solved
    - is_accepted: whether submission was judged accepted
    - time_submitted: timestamp of submission (used for tie-breaker)
    """
    from django.contrib.auth.models import User as DjangoUser

    user = models.ForeignKey(DjangoUser, on_delete=models.CASCADE, related_name='submissions')
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name='submissions')
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='submissions')
    is_accepted = models.BooleanField(default=False)
    time_submitted = models.DateTimeField(auto_now_add=True)

    class Meta:
        # prevent duplicate accepted submissions for same user/problem
        unique_together = ('user', 'contest', 'problem')

    def __str__(self):
        return f"{self.user.username} - {self.problem.title} @ {self.time_submitted} ({'AC' if self.is_accepted else 'WA'})"