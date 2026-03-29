from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=100)
    roll_no = models.CharField(max_length=20, unique=True)
    total_score = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.roll_no}"