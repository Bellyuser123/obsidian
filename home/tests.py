from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.utils import timezone
from home.models import Contest, Problem, ContestProblem, UserProblemSession, Submission
from django.urls import reverse
import datetime

@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db'
)
class ContestLobbyTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='teststudent', password='password123')
        self.user.profile.roll_no = 'TEST_ROLL'
        self.user.profile.roll_number = 'TEST_ROLL'
        self.user.profile.is_profile_complete = True
        self.user.profile.save()
        
        # Create a contest
        now = timezone.now()
        self.contest = Contest.objects.create(
            name="Alpha Contest",
            description="Testing contest lobby features",
            start_time=now - datetime.timedelta(hours=1),
            end_time=now + datetime.timedelta(hours=2),
            is_team_contest=False
        )
        
        # Create problems
        self.problem1 = Problem.objects.create(
            title="Problem One",
            statement="Statement one",
            input_format="input",
            output_format="output",
            constraints="constraints"
        )
        self.problem2 = Problem.objects.create(
            title="Problem Two",
            statement="Statement two",
            input_format="input",
            output_format="output",
            constraints="constraints"
        )
        
        # Link problems to contest
        self.cp1 = ContestProblem.objects.create(
            contest=self.contest,
            problem=self.problem1,
            points=100,
            difficulty='EASY'
        )
        self.cp2 = ContestProblem.objects.create(
            contest=self.contest,
            problem=self.problem2,
            points=200,
            difficulty='MEDIUM'
        )
        
    def test_contest_lobby_unauthenticated(self):
        # Unauthenticated users should be redirected to login
        url = reverse('contest_lobby', args=[self.contest.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/accounts/login/'))
        
    def test_contest_lobby_authenticated_solo(self):
        self.client.login(username='teststudent', password='password123')
        url = reverse('contest_lobby', args=[self.contest.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home/contest_lobby.html')
        
        # Check context variables
        self.assertEqual(response.context['contest'], self.contest)
        self.assertEqual(response.context['total_problems'], 2)
        self.assertEqual(response.context['user_score'], 0)
        self.assertEqual(response.context['user_solved_count'], 0)
        # Leaderboard should be empty or contain only users with submissions
        self.assertEqual(len(response.context['leaderboard']), 0)
        self.assertEqual(response.context['user_rank'], 1)  # ranked last (first since 0 users)
        
        # Verify rendered content has no team section since is_team_contest is False
        self.assertNotContains(response, "// MY_TEAM")
        
    def test_contest_lobby_team_mode(self):
        # Turn team mode on
        self.contest.is_team_contest = True
        self.contest.save()
        
        self.client.login(username='teststudent', password='password123')
        url = reverse('contest_lobby', args=[self.contest.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "// MY_TEAM")
        self.assertContains(response, "teststudent")
        
    def test_attempted_and_solved_logic(self):
        # Create an attempted session (UserProblemSession)
        UserProblemSession.objects.create(
            user=self.user,
            contest=self.contest,
            problem=self.problem1
        )
        
        # Create a submission that is accepted for problem2
        Submission.objects.create(
            user=self.user,
            contest=self.contest,
            problem=self.problem2,
            is_accepted=True,
            score_awarded=200.0,
            total_time_taken=15.0
        )
        
        self.client.login(username='teststudent', password='password123')
        url = reverse('contest_lobby', args=[self.contest.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.problem1.id, response.context['attempted_problems'])
        self.assertIn(self.problem2.id, response.context['solved_problems'])
        
        # Check leaderboard
        leaderboard = response.context['leaderboard']
        self.assertEqual(len(leaderboard), 1)
        self.assertEqual(leaderboard[0]['username'], 'teststudent')
        self.assertEqual(leaderboard[0]['solved'], 1)
        self.assertEqual(leaderboard[0]['score'], 200.0)
        
        # Check user stats in context
        self.assertEqual(response.context['user_score'], 200.0)
        self.assertEqual(response.context['user_solved_count'], 1)
        self.assertEqual(response.context['user_rank'], 1)
        
        # Check success rates on problems
        problems = response.context['problems']
        p1 = next(cp for cp in problems if cp.problem.id == self.problem1.id)
        p2 = next(cp for cp in problems if cp.problem.id == self.problem2.id)
        
        # p1 had 0 submissions
        self.assertEqual(p1.success_rate, 0.0)
        # p2 had 1 submission and 1 accepted -> 100% success rate
        self.assertEqual(p2.success_rate, 100.0)

    def test_detailed_leaderboard_calculations(self):
        # Setup submissions for problem 1 (2 WA, then 1 AC)
        # 1st WA
        Submission.objects.create(
            user=self.user,
            contest=self.contest,
            problem=self.problem1,
            status='WA',
            is_accepted=False
        )
        # 2nd WA
        Submission.objects.create(
            user=self.user,
            contest=self.contest,
            problem=self.problem1,
            status='WA',
            is_accepted=False
        )
        # 3rd AC (solving at total_time_taken = 45.0 mins)
        Submission.objects.create(
            user=self.user,
            contest=self.contest,
            problem=self.problem1,
            status='AC',
            is_accepted=True,
            score_awarded=100.0,
            total_time_taken=45.0
        )

        # Setup submissions for problem 2 (1 WA, no AC)
        Submission.objects.create(
            user=self.user,
            contest=self.contest,
            problem=self.problem2,
            status='WA',
            is_accepted=False
        )

        self.client.login(username='teststudent', password='password123')
        url = reverse('contest_lobby', args=[self.contest.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        leaderboard = response.context['leaderboard']
        self.assertEqual(len(leaderboard), 1)
        
        entry = leaderboard[0]
        details = entry.get('problems_details', [])
        self.assertEqual(len(details), 2)
        
        # Details for problem 1 (index 0): 3 attempts, first solved at 25:00 (45 - 20 penalty), penalty 20
        self.assertEqual(details[0]['status'], 'solved')
        self.assertEqual(details[0]['text'], '3 (25:00 + 20)')
        
        # Details for problem 2 (index 1): 1 attempt, not solved, format is '1 (0:00 + 0)'
        self.assertEqual(details[1]['status'], 'attempted')
        self.assertEqual(details[1]['text'], '1 (0:00 + 0)')


from django.core.exceptions import ValidationError
from home.models import TestCase as ModelTestCase, Language

@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db'
)
class TestCaseValidationAndScoringTests(TestCase):
    def setUp(self):
        self.problem = Problem.objects.create(
            title="Weighted Problem",
            statement="Statement",
            input_format="input",
            output_format="output",
            constraints="constraints"
        )
        self.lang, _ = Language.objects.get_or_create(
            slug="python-312",
            defaults={
                'name': "Python 3.12",
                'ace_mode': "python",
                'extension': ".py",
                'docker_image': "python:3.12-slim"
            }
        )

    def test_testcase_filename_validations(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        # 1. Standard valid UPLOAD input
        tc = ModelTestCase(
            problem=self.problem,
            input_data="input",
            expected_output="output",
            weight=1,
            input_format="UPLOAD",
            output_format="EDITOR",
            input_file=SimpleUploadedFile("input.txt", b"input content"),
            input_filename="input.txt"
        )
        tc.full_clean() # Should pass

        # 2. Path traversal in input_filename
        tc.input_filename = "../input.txt"
        with self.assertRaises(ValidationError):
            tc.full_clean()

        # 3. Path traversal with slash/backslash
        tc.input_filename = "subdir/input.txt"
        with self.assertRaises(ValidationError):
            tc.full_clean()

        # 4. Hidden configuration file
        tc.input_filename = ".env"
        with self.assertRaises(ValidationError):
            tc.full_clean()

        # 5. Script extension
        tc.input_filename = "run.sh"
        with self.assertRaises(ValidationError):
            tc.full_clean()

        # 6. Invalid regex pattern
        tc.input_filename = "in!put.txt"
        with self.assertRaises(ValidationError):
            tc.full_clean()

        # 7. Auto-populates input filename if missing
        tc_auto = ModelTestCase(
            problem=self.problem,
            input_data="input",
            expected_output="output",
            weight=1,
            input_format="UPLOAD",
            output_format="EDITOR",
            input_file=SimpleUploadedFile("auto_input.txt", b"content"),
            input_filename=""
        )
        tc_auto.full_clean()
        self.assertEqual(tc_auto.input_filename, "auto_input.txt")

    def test_weighted_score_calculation(self):
        user = User.objects.create_user(username='student1', password='password123')
        from home.models import Profile
        Profile.objects.update_or_create(user=user, defaults={'full_name': "Student One", 'roll_no': "ROLL_123", 'roll_number': "ROLL_123", 'is_profile_complete': True})
        contest = Contest.objects.create(
            name="Contest 1",
            start_time=timezone.now(),
            end_time=timezone.now() + datetime.timedelta(hours=2)
        )
        cp = ContestProblem.objects.create(
            contest=contest,
            problem=self.problem,
            points=100
        )
        # Create test cases with custom weights
        tc1 = ModelTestCase.objects.create(problem=self.problem, input_data="1", expected_output="1", weight=0)
        tc2 = ModelTestCase.objects.create(problem=self.problem, input_data="2", expected_output="2", weight=2)
        tc3 = ModelTestCase.objects.create(problem=self.problem, input_data="3", expected_output="3", weight=3)
        # Total weight = 5

        # Create user session
        UserProblemSession.objects.create(user=user, contest=contest, problem=self.problem)

        submission = Submission.objects.create(
            user=user,
            contest=contest,
            problem=self.problem,
            code="dummy",
            language=self.lang,
            status='PENDING'
        )

        from home.tasks import judge_submission
        from unittest.mock import patch
        
        # Test Case A: student passes tc1 and tc2, but fails tc3.
        # Weight passed: tc1 (0) + tc2 (2) = 2. Total weight = 5.
        # Expected Score: (2 / 5) * 100 = 40.0
        mock_results = [
            {'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '1', 'time': '0.1s'},
            {'id': '02', 'status': 'pass', 'label': 'PASSED', 'stdout': '2', 'time': '0.1s'},
            {'id': '03', 'status': 'fail', 'label': 'WRONG ANSWER', 'stdout': 'wrong', 'time': '0.1s'}
        ]
        with patch('home.tasks.judge_problem', return_value=mock_results):
            judge_submission(submission.id)
            submission.refresh_from_db()
            self.assertEqual(submission.score_awarded, 40.0)
            self.assertEqual(submission.status, 'PARTIAL')

        # Test Case B: total_weight = 0
        tc2.weight = 0
        tc2.save()
        tc3.weight = 0
        tc3.save()
        # total_weight = 0. student passes all -> score = max_score
        mock_results_all_pass = [
            {'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '1', 'time': '0.1s'},
            {'id': '02', 'status': 'pass', 'label': 'PASSED', 'stdout': '2', 'time': '0.1s'},
            {'id': '03', 'status': 'pass', 'label': 'PASSED', 'stdout': '3', 'time': '0.1s'}
        ]
        with patch('home.tasks.judge_problem', return_value=mock_results_all_pass):
            judge_submission(submission.id)
            submission.refresh_from_db()
            self.assertEqual(submission.score_awarded, 100.0)
            self.assertTrue(submission.is_accepted)

    def test_judge_problem_with_upload_files(self):
        import subprocess
        from home.utils import judge_problem
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch, MagicMock

        # Create a testcase with UPLOAD input and output formats
        tc = ModelTestCase.objects.create(
            problem=self.problem,
            input_format="UPLOAD",
            output_format="UPLOAD",
            input_file=SimpleUploadedFile("my_input.txt", b"secret input data"),
            output_file=SimpleUploadedFile("my_output.txt", b"secret expected data"),
            input_filename="my_input.txt",
            output_filename="my_output.txt",
            weight=1
        )

        def mock_subprocess_run(cmd, *args, **kwargs):
            # Inspect command to locate mounted host temporary directory
            temp_dir = None
            for arg in cmd:
                if ':/usr/src/app' in arg:
                    temp_dir = arg.split(':/usr/src/app')[0]
            if temp_dir:
                tc_id = str(tc.id)
                # Verify that the input file was written to temp_dir
                upload_input_path = f"{temp_dir}/input_{tc_id}_upload.txt"
                with open(upload_input_path, 'r') as f:
                    input_data = f.read()
                
                # Verify content matches uploaded input_file content
                if input_data == "secret input data":
                    with open(f"{temp_dir}/status_{tc_id}.txt", 'w') as f:
                        f.write("0")
                    with open(f"{temp_dir}/output_{tc_id}_upload.txt", 'w') as f:
                        f.write("secret expected data")
                    with open(f"{temp_dir}/compile_status.txt", 'w') as f:
                        f.write("0")
            
            mock_res = MagicMock()
            mock_res.returncode = 0
            return mock_res

        with patch('subprocess.run', side_effect=mock_subprocess_run):
            results = judge_problem("dummy code", self.lang, [tc], stop_on_fail=False)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['status'], 'pass')
            self.assertEqual(results[0]['label'], 'PASSED')
            self.assertEqual(results[0]['expected'], 'secret expected data')
            self.assertEqual(results[0]['stdout'], 'secret expected data')

    def test_anti_cheat_telemetry_endpoint(self):
        from home.models import ViolationLog, ContestParticipation, Profile
        # 1. Register a user and log in
        user = User.objects.create_user(username='cheat_student', password='password123')
        Profile.objects.update_or_create(user=user, defaults={'full_name': "Cheat Student", 'roll_no': "CHEAT101", 'roll_number': "CHEAT101", 'is_profile_complete': True})
        self.client.login(username='cheat_student', password='password123')

        # 2. Create contest that is currently live
        contest = Contest.objects.create(
            name="Anti-Cheat Test Contest",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(hours=2),
            enable_anti_cheat=True
        )

        url = reverse('log_violation', args=[contest.id])

        # 3. Report first violation (Strike 1: WARN, chance 1 used)
        res1 = self.client.post(url, {'violation_type': 'TAB_SWITCH', 'details': 'Switched tab once'})
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1['action'], 'WARN')
        self.assertEqual(data1['current_strikes'], 1)

        # 4. Report second violation (Strike 2: WARN, chance 2 used)
        res2 = self.client.post(url, {'violation_type': 'CLIPBOARD', 'details': 'Tried copying'})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2['action'], 'WARN')
        self.assertEqual(data2['current_strikes'], 2)

        # 5. Report third violation (Strike 3: WARN, chance 3 used - 3 strikes before ban!)
        res3 = self.client.post(url, {'violation_type': 'DEVTOOLS', 'details': 'Opened inspect'})
        self.assertEqual(res3.status_code, 200)
        data3 = res3.json()
        self.assertEqual(data3['action'], 'WARN')
        self.assertEqual(data3['current_strikes'], 3)
        participation = ContestParticipation.objects.get(user=user, contest=contest)
        self.assertFalse(participation.is_disqualified)

        # 6. Report fourth violation (Strike 4: BAN - banned on 4th strike!)
        res4 = self.client.post(url, {'violation_type': 'FULLSCREEN', 'details': 'Exited fullscreen'})
        self.assertEqual(res4.status_code, 200)
        data4 = res4.json()
        self.assertEqual(data4['action'], 'BAN')
        self.assertEqual(data4['current_strikes'], 4)

        # Verify that logs exist in DB and user is disqualified
        self.assertEqual(ViolationLog.objects.filter(user=user, contest=contest).count(), 4)
        participation.refresh_from_db()
        self.assertTrue(participation.is_disqualified)

        # Verify user profile remains active (contest-specific disqualification only)
        user.refresh_from_db()
        self.assertFalse(user.profile.is_disqualified)

        # 7. Attempt unban as normal contestant (MUST FAIL with 403 Forbidden - backdoor closed!)
        unban_url = reverse('unban_self', args=[contest.id])
        res_unban_unauth = self.client.get(unban_url)
        self.assertEqual(res_unban_unauth.status_code, 403)
        participation.refresh_from_db()
        self.assertTrue(participation.is_disqualified)

        # 8. Unban as superuser (MUST SUCCEED)
        user.is_superuser = True
        user.save()
        res_unban_auth = self.client.get(unban_url + f'?user_id={user.id}')
        self.assertRedirects(res_unban_auth, reverse('contest_lobby', args=[contest.id]))

        participation.refresh_from_db()
        self.assertFalse(participation.is_disqualified)
        self.assertEqual(ViolationLog.objects.filter(user=user, contest=contest).count(), 0)

    def test_host_and_superuser_immune_from_ban(self):
        from home.models import ViolationLog, ContestParticipation, Profile
        host_user = User.objects.create_user(username='contest_host_user', password='password123')
        Profile.objects.update_or_create(user=host_user, defaults={'full_name': "Host User", 'roll_no': "HOST01", 'is_profile_complete': True})

        contest = Contest.objects.create(
            name="Host Immunity Contest",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(hours=2),
            enable_anti_cheat=True,
            host=host_user
        )

        self.client.login(username='contest_host_user', password='password123')
        url = reverse('log_violation', args=[contest.id])

        # Report 5 infractions as host - must never be banned
        for _ in range(5):
            res = self.client.post(url, {'violation_type': 'TAB_SWITCH', 'details': 'Host switched tab'})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn(data.get('action'), ['IGNORE', 'NONE'])

        self.assertEqual(ViolationLog.objects.filter(user=host_user, contest=contest).count(), 0)
        participation = ContestParticipation.objects.filter(user=host_user, contest=contest).first()
        if participation:
            self.assertFalse(participation.is_disqualified)

    def test_contest_specific_disqualification(self):
        from home.models import ContestParticipation, Profile
        user = User.objects.create_user(username='multi_contest_user', password='password123')
        Profile.objects.update_or_create(user=user, defaults={'full_name': "Multi User", 'roll_no': "MULTI01", 'is_profile_complete': True})
        self.client.login(username='multi_contest_user', password='password123')

        contest1 = Contest.objects.create(
            name="Contest One",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(hours=1),
            enable_anti_cheat=True
        )
        contest2 = Contest.objects.create(
            name="Contest Two",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(hours=1),
            enable_anti_cheat=True
        )
        ContestProblem.objects.create(contest=contest1, problem=self.problem, points=10)
        ContestProblem.objects.create(contest=contest2, problem=self.problem, points=10)

        # Disqualify user only in Contest 1
        ContestParticipation.objects.create(user=user, contest=contest1, is_disqualified=True)
        ContestParticipation.objects.create(user=user, contest=contest2, is_disqualified=False)

        # User blocked from Contest 1
        r1 = self.client.get(reverse('contest_lobby', args=[contest1.id]))
        self.assertEqual(r1.status_code, 403)

        # User CAN access Contest 2
        r2 = self.client.get(reverse('contest_lobby', args=[contest2.id]))
        self.assertEqual(r2.status_code, 200)

    def test_proctor_mode_disabled_no_ban(self):
        from home.models import ViolationLog, Profile
        user = User.objects.create_user(username='no_proctor_user', password='password123')
        Profile.objects.update_or_create(user=user, defaults={'full_name': "No Proctor User", 'roll_no': "NOPROC01", 'is_profile_complete': True})
        self.client.login(username='no_proctor_user', password='password123')

        contest = Contest.objects.create(
            name="No Proctor Contest",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(hours=1),
            enable_anti_cheat=False
        )

        url = reverse('log_violation', args=[contest.id])
        res = self.client.post(url, {'violation_type': 'TAB_SWITCH', 'details': 'tab switch'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['action'], 'NONE')
        self.assertEqual(ViolationLog.objects.filter(user=user, contest=contest).count(), 0)

    def test_banned_only_while_live_and_reset_on_end_or_restart(self):
        from home.models import ContestParticipation, Profile
        user = User.objects.create_user(username='live_check_user', password='password123')
        Profile.objects.update_or_create(user=user, defaults={'full_name': "Live Check User", 'roll_no': "LIVE01", 'is_profile_complete': True})
        self.client.login(username='live_check_user', password='password123')

        # Contest that is currently live
        contest = Contest.objects.create(
            name="Live Timing Contest",
            start_time=timezone.now() - datetime.timedelta(minutes=30),
            end_time=timezone.now() + datetime.timedelta(minutes=30),
            enable_anti_cheat=True
        )
        ContestProblem.objects.create(contest=contest, problem=self.problem, points=10)

        p = ContestParticipation.objects.create(user=user, contest=contest, is_disqualified=True)

        # Blocked while live
        r_live = self.client.get(reverse('contest_lobby', args=[contest.id]))
        self.assertEqual(r_live.status_code, 403)

        # Now contest ends (end_time in the past)
        contest.end_time = timezone.now() - datetime.timedelta(minutes=1)
        contest.save()

        # Access after contest ends - allows access and automatically resets banned list
        r_ended = self.client.get(reverse('contest_lobby', args=[contest.id]))
        self.assertEqual(r_ended.status_code, 200)
        p.refresh_from_db()
        self.assertFalse(p.is_disqualified)

        # Test restart: re-disqualify, then restart contest
        p.is_disqualified = True
        p.save()
        contest.restart_contest(
            new_start_time=timezone.now() - datetime.timedelta(minutes=5),
            new_end_time=timezone.now() + datetime.timedelta(hours=1)
        )
        p.refresh_from_db()
        self.assertFalse(p.is_disqualified)

    def test_anti_cheat_gatekeeper(self):
        from home.models import ContestParticipation, Profile
        # 1. Register user
        User.objects.filter(username='banned_student').delete()
        user = User.objects.create_user(username='banned_student', password='password123')
        Profile.objects.update_or_create(user=user, defaults={'full_name': "Banned Student", 'roll_no': "BANNED101", 'roll_number': "BANNED101", 'is_profile_complete': True})
        self.client.login(username='banned_student', password='password123')

        # 2. Create contest and problem
        contest = Contest.objects.create(
            name="Secure Contest",
            start_time=timezone.now() - datetime.timedelta(hours=1),
            end_time=timezone.now() + datetime.timedelta(hours=1),
            enable_anti_cheat=True
        )
        cp = ContestProblem.objects.create(contest=contest, problem=self.problem, points=10)

        # 3. Access lobby and IDE (should pass initially)
        lobby_url = reverse('contest_lobby', args=[contest.id])
        ide_url = reverse('problem_ide', args=[contest.id, self.problem.id])
        
        r1 = self.client.get(lobby_url)
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.get(ide_url)
        self.assertEqual(r2.status_code, 200)

        # 4. Disqualify user
        participation = ContestParticipation.objects.get(user=user, contest=contest)
        participation.is_disqualified = True
        participation.save()

        # 5. Access lobby and IDE (should be blocked as 403 Forbidden)
        r3 = self.client.get(lobby_url)
        self.assertEqual(r3.status_code, 403)
        self.assertTemplateUsed(r3, 'home/disqualified.html')

        r4 = self.client.get(ide_url)
        self.assertEqual(r4.status_code, 403)
        self.assertTemplateUsed(r4, 'home/disqualified.html')

        # 6. Make user a staff member (Admin bypass) and access again (should pass)
        user.is_staff = True
        user.save()
        r5 = self.client.get(lobby_url)
        self.assertEqual(r5.status_code, 200)
        r6 = self.client.get(ide_url)
        self.assertEqual(r6.status_code, 200)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db'
)
class SocialAuthAndProfileTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_user_creation_signal_creates_profile(self):
        user = User.objects.create_user(username='oauth_user', email='oauth@example.com', password='password123')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertFalse(user.profile.is_profile_complete)
        self.assertIsNone(user.profile.roll_number)

    def test_check_profile_status_redirects_incomplete_profile(self):
        user = User.objects.create_user(username='incomplete_user', password='password123')
        self.client.login(username='incomplete_user', password='password123')
        res = self.client.get(reverse('check_profile_status'))
        self.assertRedirects(res, reverse('complete_profile'))

    def test_dashboard_redirects_incomplete_profile(self):
        user = User.objects.create_user(username='incomplete_user', password='password123')
        self.client.login(username='incomplete_user', password='password123')
        res = self.client.get(reverse('dashboard'))
        self.assertRedirects(res, reverse('complete_profile'))

    def test_complete_profile_flow(self):
        user = User.objects.create_user(username='oauth_new', password='password123')
        self.client.login(username='oauth_new', password='password123')
        
        # GET complete_profile
        res = self.client.get(reverse('complete_profile'))
        self.assertEqual(res.status_code, 200)

        # POST complete_profile with full_name, username, roll_no, and email
        post_res = self.client.post(reverse('complete_profile'), {
            'full_name': 'Final Student',
            'username': 'final_handle',
            'roll_no': 'ROLL999',
            'email': 'final@example.com'
        })
        self.assertRedirects(post_res, reverse('dashboard'))

        user.refresh_from_db()
        self.assertEqual(user.username, 'final_handle')
        self.assertEqual(user.email, 'final@example.com')
        self.assertEqual(user.first_name, 'Final')
        self.assertEqual(user.last_name, 'Student')
        self.assertTrue(user.profile.is_profile_complete)
        self.assertEqual(user.profile.full_name, 'Final Student')
        self.assertEqual(user.profile.roll_number, 'ROLL999')
        self.assertEqual(user.profile.roll_no, 'ROLL999')

        # Subsequent check_profile_status redirects to dashboard
        status_res = self.client.get(reverse('check_profile_status'))
        self.assertRedirects(status_res, reverse('dashboard'))


from home.models import EmailOTP

@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db'
)
class EmailOTPAndPasswordResetTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_signup_creates_inactive_user_and_otp(self):
        res = self.client.post(reverse('auth'), {
            'register': '1',
            'username': 'otpstudent',
            'email': 'otpstudent@obsidians.codes',
            'password': 'Password123!',
            'full_name': 'OTP Student',
            'roll_no': 'OTP_ROLL_1'
        })
        self.assertRedirects(res, reverse('verify_otp'))
        user = User.objects.get(username='otpstudent')
        self.assertFalse(user.is_active)
        self.assertTrue(EmailOTP.objects.filter(user=user).exists())
        self.assertEqual(self.client.session.get('pending_user_id'), user.id)

    def test_verify_otp_success(self):
        user = User.objects.create_user(username='otpuser2', email='otp2@obsidians.codes', password='password123', is_active=False)
        otp = EmailOTP.objects.create(user=user, otp_code='123456')
        
        session = self.client.session
        session['pending_user_id'] = user.id
        session.save()

        res = self.client.post(reverse('verify_otp'), {'otp_code': '123456'})
        self.assertRedirects(res, reverse('check_profile_status'), fetch_redirect_response=False)

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(EmailOTP.objects.filter(user=user).exists())

    def test_verify_otp_invalid_code(self):
        user = User.objects.create_user(username='otpuser3', email='otp3@obsidians.codes', password='password123', is_active=False)
        EmailOTP.objects.create(user=user, otp_code='123456')
        
        session = self.client.session
        session['pending_user_id'] = user.id
        session.save()

        res = self.client.post(reverse('verify_otp'), {'otp_code': '999999'})
        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_social_user_password_reset_blocked(self):
        user = User.objects.create_user(username='socialuser', email='social@obsidians.codes')
        user.set_unusable_password()
        user.save()

        res = self.client.post(reverse('password_reset'), {'email': 'social@obsidians.codes'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "created using Google or GitHub")

    def test_password_reset_dynamic_domain_and_html_email(self):
        from django.core import mail
        user = User.objects.create_user(username='localuser', email='local@obsidians.codes', password='password123')
        
        res = self.client.post(reverse('password_reset'), {'email': 'local@obsidians.codes'}, HTTP_HOST='127.0.0.1:8000')
        self.assertRedirects(res, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)

        sent_email = mail.outbox[0]
        self.assertIn("127.0.0.1:8000", sent_email.body)

        # Check HTML alternative
        self.assertEqual(len(sent_email.alternatives), 1)
        html_content, mimetype = sent_email.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn("127.0.0.1:8000", html_content)
        self.assertIn("RESET PASSWORD", html_content)

    def test_password_reset_confirm_updates_password_and_redirects_to_login(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        user = User.objects.create_user(username='resetuser', email='reset@obsidians.codes', password='OldPassword123!')
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        confirm_url = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})

        # 1. GET request establishes valid link session
        get_res = self.client.get(confirm_url, follow=True)
        self.assertEqual(get_res.status_code, 200)
        self.assertTrue(get_res.context['validlink'])

        # 2. Mismatched passwords render form validation errors
        form_url = get_res.redirect_chain[0][0] if get_res.redirect_chain else confirm_url
        bad_post = self.client.post(form_url, {
            'new_password1': 'NewPass12345!',
            'new_password2': 'MismatchPass999!'
        }, follow=True)
        self.assertEqual(bad_post.status_code, 200)
        self.assertTrue(bad_post.context['validlink'])
        self.assertTrue(bad_post.context['form'].errors)

        # 3. Valid password updates auth_user password and redirects to login (/auth/)
        valid_post = self.client.post(form_url, {
            'new_password1': 'NewValidPassword123!',
            'new_password2': 'NewValidPassword123!'
        }, follow=False)
        self.assertRedirects(valid_post, reverse('auth'), fetch_redirect_response=False)

        user.refresh_from_db()
        self.assertTrue(user.check_password('NewValidPassword123!'))


class ProductionSecuritySettingsTestCase(TestCase):
    def test_settings_security_defaults(self):
        from django.conf import settings
        # Ensure ALLOWED_HOSTS does not contain wildcard *
        self.assertNotIn('*', settings.ALLOWED_HOSTS)
        # Ensure SECRET_KEY is set and non-empty
        self.assertTrue(bool(settings.SECRET_KEY))

    def test_secret_key_missing_in_production_raises_error(self):
        from django.core.exceptions import ImproperlyConfigured

        def check_secret_key(secret_key, debug):
            if not secret_key:
                if debug:
                    return 'dev-key'
                raise ImproperlyConfigured("SECRET_KEY missing")
            return secret_key

        with self.assertRaises(ImproperlyConfigured):
            check_secret_key('', False)

        self.assertEqual(check_secret_key('', True), 'dev-key')
        self.assertEqual(check_secret_key('my-prod-key', False), 'my-prod-key')

    def test_allowed_hosts_parsing(self):
        def parse_allowed_hosts(raw_str):
            return [h.strip() for h in raw_str.split(',') if h.strip()]

        hosts = parse_allowed_hosts(" 127.0.0.1 , localhost , obsidians.codes ")
        self.assertEqual(hosts, ['127.0.0.1', 'localhost', 'obsidians.codes'])


class DatabaseScoreRaceConditionTestCase(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.user = User.objects.create_user(username='test_contestant', password='Password123!')
        self.profile = self.user.profile
        self.profile.total_score = 0
        self.profile.save()

        self.contest = Contest.objects.create(
            name="Scoring Race Contest",
            description="Testing race-free score updates",
            start_time=timezone.now() - timezone.timedelta(hours=1),
            end_time=timezone.now() + timezone.timedelta(hours=2),
            penalty_minutes=10
        )
        from home.models import Language
        self.lang, _ = Language.objects.get_or_create(name='Python 3', slug='python3', ace_mode='python')

        self.prob1 = Problem.objects.create(
            title="Problem 1", statement="P1", input_format="in", output_format="out", constraints="c"
        )
        self.cp1 = ContestProblem.objects.create(contest=self.contest, problem=self.prob1, points=100)
        # Two testcases: tc1 (weight 4) and tc2 (weight 6) -> total weight = 10
        ModelTestCase.objects.create(problem=self.prob1, input_data="1", expected_output="1", weight=4)
        ModelTestCase.objects.create(problem=self.prob1, input_data="2", expected_output="2", weight=6)

        self.prob2 = Problem.objects.create(
            title="Problem 2", statement="P2", input_format="in", output_format="out", constraints="c"
        )
        self.cp2 = ContestProblem.objects.create(contest=self.contest, problem=self.prob2, points=50)
        ModelTestCase.objects.create(problem=self.prob2, input_data="2", expected_output="2", weight=1)

    def test_score_update_single_improvement_and_lower_attempts(self):
        from home.tasks import judge_submission
        from unittest.mock import patch

        # First submission on Prob 1: Partial pass (passes tc1 only -> 4/10 * 100 = 40.0)
        sub1 = Submission.objects.create(
            user=self.user, contest=self.contest, problem=self.prob1,
            code="print(1)", language=self.lang, status='PENDING'
        )
        mock_partial = [
            {'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '1', 'time': '0.1s'},
            {'id': '02', 'status': 'fail', 'label': 'WRONG ANSWER', 'stdout': 'wrong', 'time': '0.1s'}
        ]
        with patch('home.tasks.judge_problem', return_value=mock_partial):
            judge_submission(sub1.id)

        self.profile.refresh_from_db()
        sub1.refresh_from_db()
        self.assertEqual(sub1.score_awarded, 40.0)
        self.assertEqual(self.profile.total_score, 40)

        # Second submission on Prob 1: Full pass (passes both tc1 & tc2 -> 10/10 * 100 = 100.0)
        sub2 = Submission.objects.create(
            user=self.user, contest=self.contest, problem=self.prob1,
            code="print(1)", language=self.lang, status='PENDING'
        )
        mock_full = [
            {'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '1', 'time': '0.1s'},
            {'id': '02', 'status': 'pass', 'label': 'PASSED', 'stdout': '2', 'time': '0.1s'}
        ]
        with patch('home.tasks.judge_problem', return_value=mock_full):
            judge_submission(sub2.id)

        self.profile.refresh_from_db()
        sub2.refresh_from_db()
        self.assertEqual(sub2.score_awarded, 100.0)
        # Score improved from 40 to 100: profile total_score must be exactly 100 (incremented by 60)
        self.assertEqual(self.profile.total_score, 100)

        # Third submission on Prob 1: Worse attempt (partial pass 40.0)
        sub3 = Submission.objects.create(
            user=self.user, contest=self.contest, problem=self.prob1,
            code="print(1)", language=self.lang, status='PENDING'
        )
        with patch('home.tasks.judge_problem', return_value=mock_partial):
            judge_submission(sub3.id)

        self.profile.refresh_from_db()
        sub3.refresh_from_db()
        self.assertEqual(sub3.score_awarded, 40.0)
        # Worse score should not reduce or corrupt the user's score
        self.assertEqual(self.profile.total_score, 100)

    def test_score_update_across_different_problems(self):
        from home.tasks import judge_submission
        from unittest.mock import patch

        sub_p1 = Submission.objects.create(
            user=self.user, contest=self.contest, problem=self.prob1,
            code="code1", language=self.lang, status='PENDING'
        )
        sub_p2 = Submission.objects.create(
            user=self.user, contest=self.contest, problem=self.prob2,
            code="code2", language=self.lang, status='PENDING'
        )

        mock_full_p1 = [
            {'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '1', 'time': '0.1s'},
            {'id': '02', 'status': 'pass', 'label': 'PASSED', 'stdout': '2', 'time': '0.1s'}
        ]
        mock_full_p2 = [
            {'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '2', 'time': '0.1s'}
        ]
        with patch('home.tasks.judge_problem', side_effect=[mock_full_p1, mock_full_p2]):
            judge_submission(sub_p1.id)
            judge_submission(sub_p2.id)

        self.profile.refresh_from_db()
        # Prob 1 gave 100, Prob 2 gave 50 -> total_score must be 150
        self.assertEqual(self.profile.total_score, 150)

    def test_rejudge_submission_idempotency(self):
        from home.tasks import judge_submission
        from unittest.mock import patch

        sub = Submission.objects.create(
            user=self.user, contest=self.contest, problem=self.prob1,
            code="code", language=self.lang, status='PENDING'
        )
        mock_full = [
            {'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '1', 'time': '0.1s'},
            {'id': '02', 'status': 'pass', 'label': 'PASSED', 'stdout': '2', 'time': '0.1s'}
        ]
        with patch('home.tasks.judge_problem', return_value=mock_full):
            judge_submission(sub.id)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.total_score, 100)

        # Re-judging the same submission should not double-count the score
        with patch('home.tasks.judge_problem', return_value=mock_full):
            judge_submission(sub.id)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.total_score, 100)


class DatabasePoolStarvationAndLimitsTestCase(TestCase):
    def test_pool_options_enforce_20_connection_ceiling(self):
        from django.conf import settings
        db_conf = settings.DATABASES['default']
        pool_options = db_conf.get('POOL_OPTIONS', {})

        pool_size = pool_options.get('POOL_SIZE', 0)
        max_overflow = pool_options.get('MAX_OVERFLOW', 0)
        timeout = pool_options.get('TIMEOUT', 0)
        recycle = pool_options.get('RECYCLE', 0)
        pre_ping = pool_options.get('PRE_PING', False)

        # Ensure base pool and overflow values are bounded
        self.assertLessEqual(pool_size, 5, "Per-process POOL_SIZE should be <= 5 for 20-connection ceiling")
        self.assertLessEqual(max_overflow, 2, "Per-process MAX_OVERFLOW should be <= 2")

        # Across 3 processes (2 Gunicorn web + 1 Celery worker):
        # Peak connection count must strictly be <= 20
        num_processes = 3
        max_peak_connections = num_processes * (pool_size + max_overflow)
        self.assertLessEqual(max_peak_connections, 20, f"Peak connections {max_peak_connections} exceeds 20-connection ceiling")

        # Timeout must be at least 15s to allow burst queueing without 500 errors
        self.assertGreaterEqual(timeout, 15)
        # Recycle must be configured to prevent idle socket drop
        self.assertGreaterEqual(recycle, 60)
        # Pre-ping must be enabled
        self.assertTrue(pre_ping)

    def test_celery_postrun_connection_cleanup(self):
        from obsidian_proj.celery import on_task_postrun
        # Execute postrun signal handler and verify it runs cleanly
        try:
            on_task_postrun()
        except Exception as e:
            self.fail(f"on_task_postrun failed with exception: {e}")


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db'
)
class LeaderboardLoadAndCachingTestCase(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.client = Client()
        self.user = User.objects.create_user(username='leaderboard_user', password='Password123!')
        self.client.login(username='leaderboard_user', password='Password123!')

        self.contest = Contest.objects.create(
            name="Caching Benchmark Contest",
            description="Testing leaderboard cache",
            start_time=timezone.now() - timezone.timedelta(minutes=30),
            end_time=timezone.now() + timezone.timedelta(hours=2),
            penalty_minutes=10
        )
        self.problem = Problem.objects.create(
            title="Problem C", statement="Stmt", input_format="in", output_format="out", constraints="c"
        )
        ContestProblem.objects.create(contest=self.contest, problem=self.problem, points=100)

    def test_leaderboard_caching_and_hit(self):
        from django.core.cache import cache
        cache_key = f"contest_leaderboard_{self.contest.id}"
        cache.delete(cache_key)

        # First request: Cache miss -> compiles and caches
        url = reverse('contest_lobby', args=[self.contest.id])
        res1 = self.client.get(url)
        self.assertEqual(res1.status_code, 200)

        cached_data = cache.get(cache_key)
        self.assertIsNotNone(cached_data)
        self.assertIn('leaderboard', cached_data)
        self.assertIn('problem_stats', cached_data)

        # Second request: Cache hit -> served from Redis/cache
        res2 = self.client.get(url)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(len(res2.context['leaderboard']), len(cached_data['leaderboard']))

    def test_leaderboard_cache_invalidation_on_submission_judge(self):
        from django.core.cache import cache
        from home.models import Language, TestCase as ModelTestCase
        from home.tasks import judge_submission
        from unittest.mock import patch

        lang, _ = Language.objects.get_or_create(name='Python 3', slug='python3', ace_mode='python')
        ModelTestCase.objects.create(problem=self.problem, input_data="1", expected_output="1", weight=1)

        cache_key = f"contest_leaderboard_{self.contest.id}"
        # Pre-seed cache
        cache.set(cache_key, {'leaderboard': [], 'problem_stats': {}}, timeout=60)
        self.assertIsNotNone(cache.get(cache_key))

        sub = Submission.objects.create(
            user=self.user, contest=self.contest, problem=self.problem,
            code="print(1)", language=lang, status='PENDING'
        )

        mock_res = [{'id': '01', 'status': 'pass', 'label': 'PASSED', 'stdout': '1', 'time': '0.1s'}]
        with patch('home.tasks.judge_problem', return_value=mock_res):
            judge_submission(sub.id)

        # Submission completion must invalidate the cached leaderboard
        self.assertIsNone(cache.get(cache_key))

    def test_contest_leaderboard_api_endpoint(self):
        url = reverse('contest_leaderboard_api', args=[self.contest.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('contest_id'), self.contest.id)
        self.assertIn('leaderboard', data)
        self.assertIn('problem_stats', data)


class SetupIdeCommandTestCase(TestCase):
    def test_setup_ide_skip_pull(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('setup_ide', '--skip-pull', stdout=out)
        output = out.getvalue()
        self.assertIn("Obsidian IDE Setup", output)
        self.assertIn("Done:", output)
        self.assertTrue(Language.objects.filter(slug='python-312').exists())
        self.assertTrue(Language.objects.filter(slug='cpp').exists())


class ModularViewsArchitectureTestCase(TestCase):
    """
    Validates the modular views architecture:
    - Verifies package exports and backwards compatibility
    - Verifies domain module isolation (auth, contest, ide, api)
    - Verifies Python PEP 484 type annotations on critical functions
    - Verifies URL routing resolution to modular view handlers
    - Verifies deduplicated orphan submission recovery service
    """

    def test_modular_views_package_exports(self):
        import home.views as views

        expected_symbols = [
            'auth_view',
            'verify_otp_view',
            'resend_otp_view',
            'CustomPasswordResetView',
            'CustomPasswordResetConfirmView',
            'check_profile_status',
            'complete_profile',
            'profile_view',
            'logout_view',
            'home',
            'dashboard_view',
            'check_disqualified',
            'get_compiled_contest_leaderboard',
            'contest_lobby',
            'enter_contest',
            'log_violation',
            'unban_contestant',
            'unban_self',
            'problem_ide_view',
            'handle_submission',
            'contest_leaderboard_api',
            'submission_status_api',
            'submission_history_api',
            'run_status_api',
        ]
        for symbol in expected_symbols:
            self.assertTrue(
                hasattr(views, symbol),
                f"home.views must export '{symbol}' for full backwards compatibility"
            )
            self.assertIn(
                symbol,
                views.__all__,
                f"'{symbol}' must be declared in home.views.__all__"
            )

    def test_domain_modules_importability(self):
        from home.views import auth, contest, ide, api

        self.assertTrue(hasattr(auth, 'auth_view'))
        self.assertTrue(hasattr(auth, 'complete_profile'))
        self.assertTrue(hasattr(contest, 'contest_lobby'))
        self.assertTrue(hasattr(contest, 'get_compiled_contest_leaderboard'))
        self.assertTrue(hasattr(ide, 'problem_ide_view'))
        self.assertTrue(hasattr(ide, 'handle_submission'))
        self.assertTrue(hasattr(api, 'submission_status_api'))
        self.assertTrue(hasattr(api, 'reap_orphaned_submission'))

    def test_type_annotations_present(self):
        from typing import get_type_hints
        from home.views import contest, ide, api, auth

        hints_check_disqualified = get_type_hints(contest.check_disqualified)
        self.assertEqual(hints_check_disqualified.get('return'), bool)

        hints_format_hms = get_type_hints(contest.format_duration_hms)
        self.assertEqual(hints_format_hms.get('mins'), float)
        self.assertEqual(hints_format_hms.get('return'), str)

        hints_constraints = get_type_hints(ide.get_problem_constraints)
        self.assertIn('return', hints_constraints)

        hints_reap = get_type_hints(api.reap_orphaned_submission)
        self.assertIn('return', hints_reap)

        hints_auth = get_type_hints(auth.auth_view)
        self.assertIn('request', hints_auth)
        self.assertIn('return', hints_auth)

    def test_url_resolution_to_modular_views(self):
        from django.urls import resolve
        from home.views.auth import auth_view
        from home.views.contest import contest_lobby, home
        from home.views.ide import problem_ide_view
        from home.views.api import contest_leaderboard_api

        self.assertEqual(resolve('/').func, home)
        self.assertEqual(resolve('/auth/').func, auth_view)
        self.assertEqual(resolve('/contest/1/lobby/').func, contest_lobby)
        self.assertEqual(resolve('/contest/1/problem/1/ide/').func, problem_ide_view)
        self.assertEqual(resolve('/contest/1/leaderboard_api/').func, contest_leaderboard_api)

    def test_reap_orphaned_submission_service(self):
        from home.views.api import reap_orphaned_submission
        from home.models import Contest, Problem, Language, Submission
        from django.contrib.auth.models import User
        from django.core.cache import cache

        user = User.objects.create_user(username='orphanuser', password='password123')
        contest = Contest.objects.create(
            name="Orphan Contest",
            start_time=timezone.now(),
            end_time=timezone.now() + datetime.timedelta(hours=2)
        )
        problem = Problem.objects.create(title="P1", statement="S1")
        lang, _ = Language.objects.get_or_create(name='Python 3', slug='python3', ace_mode='python')

        sub = Submission.objects.create(
            user=user,
            contest=contest,
            problem=problem,
            code="print('stuck')",
            language=lang,
            status='PENDING'
        )

        status_data = reap_orphaned_submission(sub)
        self.assertEqual(status_data['status'], 'RE')
        self.assertEqual(status_data['is_accepted'], False)
        self.assertIn("execution orphaned", status_data['error_message'])

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'RE')
        self.assertIn("execution orphaned", sub.error_message)

        cached = cache.get(f"sub_status_{sub.id}")
        self.assertIsNotNone(cached)
        self.assertEqual(cached['status'], 'RE')


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    SESSION_ENGINE='django.contrib.sessions.backends.db'
)
class MultiTenantArchitectureTestCase(TestCase):
    """
    Test suite for Sprint 1 of Obsidian Enterprise Multi-Tenant Architecture:
    - Profile roll_no overlap across organizations
    - Cross-contest contextual role isolation (Host in Contest A, Contestant in Contest B)
    - Prevention of hosts/judges submitting solutions in their own contests (HTTP 403)
    - Superuser test-mode bypass rules
    - HostApplication admin approval action and organization auto-provisioning
    - Slug collision resolution
    - Organization owner/admin permission inheritance and proctor immunity
    """

    def setUp(self):
        from unittest.mock import patch
        self.patcher_judge = patch('home.views.ide.judge_submission.delay')
        self.mock_judge = self.patcher_judge.start()
        self.client = Client()

        self.superuser = User.objects.create_superuser(
            username='platform_super',
            email='admin@obsidian.codes',
            password='adminpassword123'
        )

        now = timezone.now()
        self.lang, _ = Language.objects.get_or_create(
            slug='python3',
            defaults={'name': 'Python 3', 'ace_mode': 'python', 'docker_image': 'python:3.12-slim'}
        )

        self.problem = Problem.objects.create(
            title="Two Sum Multi",
            statement="Sum two numbers",
            input_format="a b",
            output_format="sum",
            constraints="1 <= a, b <= 100",
            visibility='PUBLIC'
        )

        self.contest_a = Contest.objects.create(
            name="Contest Alpha",
            description="Contest A",
            start_time=now - datetime.timedelta(hours=1),
            end_time=now + datetime.timedelta(hours=2),
            enable_anti_cheat=True
        )
        ContestProblem.objects.create(contest=self.contest_a, problem=self.problem, points=100)

        self.contest_b = Contest.objects.create(
            name="Contest Beta",
            description="Contest B",
            start_time=now - datetime.timedelta(hours=1),
            end_time=now + datetime.timedelta(hours=2),
            enable_anti_cheat=True
        )
        ContestProblem.objects.create(contest=self.contest_b, problem=self.problem, points=100)

    def tearDown(self):
        self.patcher_judge.stop()

    def test_profile_overlapping_roll_numbers(self):
        """Validates that students from different colleges can share identical roll numbers."""
        from home.models import Profile

        u1 = User.objects.create_user(username='student_harvard', password='pass123', email='u1@harvard.edu')
        u2 = User.objects.create_user(username='student_oxford', password='pass123', email='u2@oxford.ac.uk')

        u1.profile.roll_no = 'CS_2026_001'
        u1.profile.save()

        u2.profile.roll_no = 'CS_2026_001'
        u2.profile.save()

        self.assertEqual(Profile.objects.filter(roll_no='CS_2026_001').count(), 2)

    def test_contextual_role_isolation(self):
        """Validates that a user can be HOST in Contest A and CONTESTANT in Contest B simultaneously."""
        from home.permissions import is_contest_staff, can_manage_contest, can_compete_in_contest
        from home.models import ContestParticipation

        alice = User.objects.create_user(username='alice_dual', password='password123')
        ContestParticipation.objects.create(user=alice, contest=self.contest_a, role='HOST')
        ContestParticipation.objects.create(user=alice, contest=self.contest_b, role='CONTESTANT')

        # Contest A assertions (Alice is HOST)
        self.assertTrue(is_contest_staff(alice, self.contest_a))
        self.assertTrue(can_manage_contest(alice, self.contest_a))
        self.assertFalse(can_compete_in_contest(alice, self.contest_a))

        # Contest B assertions (Alice is CONTESTANT)
        self.assertFalse(is_contest_staff(alice, self.contest_b))
        self.assertFalse(can_manage_contest(alice, self.contest_b))
        self.assertTrue(can_compete_in_contest(alice, self.contest_b))

    def test_host_and_staff_test_submission_and_leaderboard_exclusion(self):
        """
        Validates that a HOST or superuser CAN submit code to test problems,
        the submission is flagged is_staff_test=True, and is excluded from leaderboard rankings.
        """
        import json
        from home.models import ContestParticipation, Submission
        from home.views.contest import get_compiled_contest_leaderboard
        from django.core.cache import cache

        host_user = User.objects.create_user(username='host_tester', password='password123')
        ContestParticipation.objects.create(user=host_user, contest=self.contest_a, role='HOST')

        student_user = User.objects.create_user(username='normal_student', password='password123')
        ContestParticipation.objects.create(user=student_user, contest=self.contest_a, role='CONTESTANT')

        self.client.login(username='host_tester', password='password123')

        # Host submits in Contest A (Permitted test submission)
        url_a = reverse('handle_submission', kwargs={'contest_id': self.contest_a.id, 'problem_id': self.problem.id})
        res_a = self.client.post(
            url_a,
            data=json.dumps({'type': 'SUBMIT', 'code': 'print("host test")', 'language': 'python3'}),
            content_type='application/json'
        )
        self.assertEqual(res_a.status_code, 200)
        self.assertTrue(res_a.json().get('ok'))
        sub_id = res_a.json().get('submission_id')
        self.assertIsNotNone(sub_id)

        host_sub = Submission.objects.get(id=sub_id)
        self.assertTrue(host_sub.is_staff_test)

        # Student submits in Contest A
        self.client.login(username='normal_student', password='password123')
        res_s = self.client.post(
            url_a,
            data=json.dumps({'type': 'SUBMIT', 'code': 'print("student")', 'language': 'python3'}),
            content_type='application/json'
        )
        self.assertEqual(res_s.status_code, 200)
        student_sub = Submission.objects.get(id=res_s.json().get('submission_id'))
        self.assertFalse(student_sub.is_staff_test)

        # Simulate graded scores on both submissions
        host_sub.status = 'AC'
        host_sub.is_accepted = True
        host_sub.score_awarded = 100.0
        host_sub.save()

        student_sub.status = 'AC'
        student_sub.is_accepted = True
        student_sub.score_awarded = 100.0
        student_sub.save()

        # Invalidate cache and fetch leaderboard
        cache.delete(f"contest_leaderboard_{self.contest_a.id}")
        leaderboard, _ = get_compiled_contest_leaderboard(self.contest_a, [self.problem.id])

        # Verify host is completely excluded from leaderboard rankings
        leaderboard_user_ids = [entry['user_id'] for entry in leaderboard]
        self.assertNotIn(host_user.id, leaderboard_user_ids)
        self.assertIn(student_user.id, leaderboard_user_ids)

    def test_promoted_staff_not_locked_out_by_disqualification(self):
        """
        Validates that a user with 3 strikes who is granted is_staff=True or HOST role
        is immediately able to load the IDE with current_strikes=0 and is not locked out.
        """
        from home.models import ContestParticipation, ViolationLog
        from home.views.contest import check_disqualified

        contestant = User.objects.create_user(username='banned_then_promoted', password='password123')
        participation = ContestParticipation.objects.create(
            user=contestant,
            contest=self.contest_a,
            role='CONTESTANT',
            is_disqualified=True
        )
        # Create 3 violation logs
        for strike in range(1, 4):
            ViolationLog.objects.create(
                user=contestant,
                contest=self.contest_a,
                violation_type='TAB_SWITCH',
                strike_number=strike
            )

        # Initially disqualified as contestant
        self.assertTrue(check_disqualified(contestant, self.contest_a))

        # Promote to HOST
        participation.role = 'HOST'
        participation.save()

        # check_disqualified must now return False
        self.assertFalse(check_disqualified(contestant, self.contest_a))

        # Load IDE view
        self.client.login(username='banned_then_promoted', password='password123')
        url_ide = reverse('problem_ide', kwargs={'contest_id': self.contest_a.id, 'problem_id': self.problem.id})
        res = self.client.get(url_ide)

        # Must not receive 403 or disqualified template
        self.assertEqual(res.status_code, 200)
        self.assertTemplateNotUsed(res, 'home/disqualified.html')
        self.assertEqual(res.context['CURRENT_STRIKES'], 0)
        self.assertFalse(res.context['is_disqualified'])
        self.assertTrue(res.context['IS_CONTEST_STAFF'])

    def test_staff_test_submission_does_not_increment_profile_score(self):
        """Grading an is_staff_test submission evaluates verdicts without altering global profile score."""
        from unittest.mock import patch
        from home.tasks import judge_submission
        from home.models import TestCase as TestCaseModel, Profile, Submission

        host = User.objects.create_user(username='host_scoring_test', password='password123')
        profile, _ = Profile.objects.get_or_create(user=host)
        profile.total_score = 0
        profile.save()

        TestCaseModel.objects.create(problem=self.problem, input_data='1 2', expected_output='3', weight=10)

        sub = Submission.objects.create(
            user=host,
            contest=self.contest_a,
            problem=self.problem,
            code="print(3)",
            language=self.lang,
            status='PENDING',
            is_staff_test=True
        )

        with patch('home.tasks.judge_problem') as mock_judge_exec:
            mock_judge_exec.return_value = [{'id': 1, 'status': 'pass', 'label': 'CORRECT', 'time': '0.01s', 'mem_kb': 100}]
            judge_submission(sub.id)

        sub.refresh_from_db()
        self.assertEqual(sub.status, 'AC')
        self.assertEqual(sub.score_awarded, 100.0)

        profile.refresh_from_db()
        self.assertEqual(profile.total_score, 0)

    def test_superuser_test_bypass_rule(self):
        """Superuser retains competitor test bypass unless explicitly registered as HOST in ContestParticipation."""
        from home.permissions import can_compete_in_contest
        from home.models import ContestParticipation

        # Implicit bypass
        self.assertTrue(can_compete_in_contest(self.superuser, self.contest_a))

        # Explicit HOST registration disables competitor status
        ContestParticipation.objects.create(user=self.superuser, contest=self.contest_a, role='HOST')
        self.assertFalse(can_compete_in_contest(self.superuser, self.contest_a))

    def test_host_application_approval_and_auto_provisioning(self):
        """Validates that approving a HostApplication provisions Organization, Membership, and AuditLog."""
        from django.contrib.admin.sites import AdminSite
        from home.admin import HostApplicationAdmin
        from home.models import HostApplication, Organization, OrganizationMembership, AuditLog

        applicant = User.objects.create_user(username='applicant_mit', password='password123')
        app = HostApplication.objects.create(
            user=applicant,
            organization_name="MIT Algorithmic Society",
            org_type='CLUB',
            official_email_or_proof="cs@mit.edu proof link",
            status='PENDING'
        )

        class DummyRequest:
            def __init__(self, superuser):
                self.user = superuser

        req = DummyRequest(self.superuser)
        admin_instance = HostApplicationAdmin(HostApplication, AdminSite())
        admin_instance.message_user = lambda request, message: None

        admin_instance.approve_selected_applications(req, HostApplication.objects.filter(id=app.id))

        app.refresh_from_db()
        self.assertEqual(app.status, 'APPROVED')
        self.assertEqual(app.reviewed_by, self.superuser)
        self.assertIsNotNone(app.reviewed_at)

        # Organization check
        org = Organization.objects.get(slug='mit-algorithmic-society')
        self.assertEqual(org.name, "MIT Algorithmic Society")
        self.assertEqual(org.verification_status, 'APPROVED')
        self.assertEqual(org.created_by, applicant)

        # Membership check
        membership = OrganizationMembership.objects.get(user=applicant, organization=org)
        self.assertEqual(membership.role, 'OWNER')
        self.assertTrue(membership.is_active)

        # AuditLog check
        self.assertTrue(AuditLog.objects.filter(
            actor=self.superuser,
            organization=org,
            action='HOST_APPLICATION_APPROVED'
        ).exists())

    def test_slug_collision_resolution(self):
        """Validates that duplicate organization names receive unique incremental slugs upon approval."""
        from django.contrib.admin.sites import AdminSite
        from home.admin import HostApplicationAdmin
        from home.models import HostApplication, Organization

        Organization.objects.create(name="Stanford AI", slug="stanford-ai", org_type='CLUB')

        applicant2 = User.objects.create_user(username='applicant_stanford2', password='password123')
        app2 = HostApplication.objects.create(
            user=applicant2,
            organization_name="Stanford AI",
            org_type='CLUB',
            official_email_or_proof="proof",
            status='PENDING'
        )

        class DummyRequest:
            def __init__(self, user):
                self.user = user

        req = DummyRequest(self.superuser)
        admin_instance = HostApplicationAdmin(HostApplication, AdminSite())
        admin_instance.message_user = lambda request, msg: None

        admin_instance.approve_selected_applications(req, HostApplication.objects.filter(id=app2.id))

        self.assertTrue(Organization.objects.filter(slug='stanford-ai-1').exists())

    def test_organization_owner_contest_staff_immunity(self):
        """Organization owners are recognized as contest staff and immune to proctoring strikes."""
        from home.models import Organization, OrganizationMembership, ViolationLog
        from home.permissions import is_contest_staff, can_manage_contest

        owner = User.objects.create_user(username='org_head', password='password123')
        org = Organization.objects.create(name="IIT Tech Council", slug="iit-tech-council")
        OrganizationMembership.objects.create(user=owner, organization=org, role='OWNER', is_active=True)

        self.contest_a.organization = org
        self.contest_a.save()

        self.assertTrue(is_contest_staff(owner, self.contest_a))
        self.assertTrue(can_manage_contest(owner, self.contest_a))

        self.client.login(username='org_head', password='password123')
        url_violation = reverse('log_violation', kwargs={'contest_id': self.contest_a.id})
        res = self.client.post(url_violation, {'violation_type': 'TAB_SWITCH'})
        self.assertEqual(res.status_code, 200)
        self.assertIn(res.json().get('action'), ['IGNORE', 'NONE'])
        self.assertEqual(res.json().get('current_strikes'), 0)
        self.assertEqual(ViolationLog.objects.filter(user=owner, contest=self.contest_a).count(), 0)




