from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from home.models import Contest, Problem, ContestProblem, UserProblemSession, Submission
from django.urls import reverse
import datetime

class ContestLobbyTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='teststudent', password='password123')
        
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
        Profile.objects.create(user=user, full_name="Student One", roll_no="ROLL_123")
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
        Profile.objects.create(user=user, full_name="Cheat Student", roll_no="CHEAT101")
        self.client.login(username='cheat_student', password='password123')

        # 2. Create contest
        contest = Contest.objects.create(
            name="Anti-Cheat Test Contest",
            start_time=timezone.now(),
            end_time=timezone.now() + datetime.timedelta(hours=2),
            enable_anti_cheat=True
        )

        # 3. Report first violation (Strike 1)
        url = reverse('log_violation', args=[contest.id])
        res1 = self.client.post(url, {'violation_type': 'TAB_SWITCH', 'details': 'Switched tab once'})
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1['action'], 'WARN')
        self.assertEqual(data1['current_strikes'], 1)

        # 4. Report second violation (Strike 2)
        res2 = self.client.post(url, {'violation_type': 'CLIPBOARD', 'details': 'Tried copying'})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2['action'], 'WARN')
        self.assertEqual(data2['current_strikes'], 2)

        # 5. Report third violation (Strike 3 - BAN)
        res3 = self.client.post(url, {'violation_type': 'DEVTOOLS', 'details': 'Opened inspect'})
        self.assertEqual(res3.status_code, 200)
        data3 = res3.json()
        self.assertEqual(data3['action'], 'BAN')

        # 6. Verify that logs exist in DB
        self.assertEqual(ViolationLog.objects.filter(user=user, contest=contest).count(), 3)
        participation = ContestParticipation.objects.get(user=user, contest=contest)
        self.assertTrue(participation.is_disqualified)
        
        # Verify user profile remains active (contest-specific disqualification only)
        user.refresh_from_db()
        self.assertFalse(user.profile.is_disqualified)

        # 7. Unban self and verify reset
        unban_url = reverse('unban_self', args=[contest.id])
        res_unban = self.client.get(unban_url)
        self.assertRedirects(res_unban, reverse('contest_lobby', args=[contest.id]))
        
        participation.refresh_from_db()
        self.assertFalse(participation.is_disqualified)
        self.assertEqual(ViolationLog.objects.filter(user=user, contest=contest).count(), 0)

    def test_anti_cheat_gatekeeper(self):
        from home.models import ContestParticipation
        # 1. Register user
        user = User.objects.create_user(username='banned_student', password='password123')
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

