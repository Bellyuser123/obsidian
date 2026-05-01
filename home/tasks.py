import os
import ast
import time
import tempfile
import subprocess
from celery import shared_task
from django.utils import timezone
from .models import Submission, ContestProblem, Profile

IMAGE_MAPPING = {
    'python3': 'python:3.12-slim',
    'python': 'python:3.12-slim',
    'cpp': 'gcc:latest',
    'cpp17': 'gcc:latest',
    'cpp20': 'gcc:latest',
    'c_cpp': 'gcc:latest',
    'java': 'openjdk:11',
    'javascript': 'node:18-alpine',
    'rust': 'rust:latest'
}

def check_python_rules(code, rules):
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax Error: {e}"

    for rule in rules:
        if rule.rule_type == 'FORBIDDEN':
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == rule.keyword:
                    return False, rule.error_message
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == rule.keyword:
                            return False, rule.error_message
                elif isinstance(node, ast.ImportFrom):
                    if node.module == rule.keyword:
                        return False, rule.error_message
                elif isinstance(node, ast.Attribute) and node.attr == rule.keyword:
                    return False, rule.error_message
        elif rule.rule_type == 'MANDATORY':
            found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == rule.keyword:
                    found = True
                    break
                elif isinstance(node, ast.FunctionDef) and node.name == rule.keyword:
                    found = True
                    break
            if not found:
                return False, rule.error_message
        elif rule.rule_type == 'STRUCTURAL':
            if rule.keyword.lower() == 'recursion':
                found_recursion = False
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        for subnode in ast.walk(node):
                            if isinstance(subnode, ast.Call):
                                if isinstance(subnode.func, ast.Name) and subnode.func.id == node.name:
                                    found_recursion = True
                                    break
                if not found_recursion:
                    return False, rule.error_message

    return True, ""

def check_string_rules(code, rules):
    for rule in rules:
        if rule.rule_type == 'FORBIDDEN':
            if rule.keyword in code:
                return False, rule.error_message
        elif rule.rule_type == 'MANDATORY':
            if rule.keyword not in code:
                return False, rule.error_message
    return True, ""

@shared_task
def judge_submission(submission_id):
    try:
        submission = Submission.objects.select_related('user', 'problem', 'contest', 'language').get(id=submission_id)
    except Submission.DoesNotExist:
        return

    problem = submission.problem
    language = submission.language
    code = submission.code

    # AST / String rule checking
    rules = problem.rules.all()
    if language.slug.startswith('py'):
        passed, error = check_python_rules(code, rules)
    else:
        passed, error = check_string_rules(code, rules)

    if not passed:
        submission.status = 'CE'
        submission.error_message = error
        submission.save()
        return

    image = IMAGE_MAPPING.get(language.slug, 'python:3.12-slim')
    ext = language.extension
    
    with tempfile.TemporaryDirectory() as temp_dir:
        abs_temp_dir = os.path.abspath(temp_dir)
        filename = f"main{ext}"
        filepath = os.path.join(abs_temp_dir, filename)
        
        with open(filepath, 'w') as f:
            f.write(code)

        # Compilation step
        compile_cmd = None
        run_cmd = None
        if ext in ['.cpp', '.cc', '.cxx']:
            compile_cmd = ["g++", "-O2", f"/code/{filename}", "-o", "/code/a.out"]
            run_cmd = ["/code/a.out"]
        elif ext == '.java':
            compile_cmd = ["javac", f"/code/{filename}"]
            run_cmd = ["java", "-cp", "/code", "Solution"]
        elif ext == '.js':
            run_cmd = ["node", f"/code/{filename}"]
        elif ext == '.rs':
            compile_cmd = ["rustc", f"/code/{filename}", "-o", "/code/a.out"]
            run_cmd = ["/code/a.out"]
        else: # Default to Python
            run_cmd = ["python3", f"/code/{filename}"]

        if compile_cmd:
            comp_proc = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", "-v", f"{abs_temp_dir}:/code", image] + compile_cmd,
                capture_output=True, text=True, timeout=15
            )
            if comp_proc.returncode != 0:
                submission.status = 'CE'
                err = comp_proc.stderr.replace(f"/code/{filename}", "main" + ext).replace("/code/a.out", "a.out")
                submission.error_message = err
                submission.save()
                return

        # Execution Step
        testcases = problem.testcases.all()
        if not testcases.exists():
            submission.status = 'AC'
            submission.is_accepted = True
            submission.save()
            return
            
        max_time = 0.0
        final_status = 'AC'
        error_msg = ""
        
        for tc in testcases:
            start = time.time()
            try:
                proc = subprocess.run(
                    ["docker", "run", "--rm", "--network", "none", "--memory=256m", "--cpus=0.5", "-i", "-v", f"{abs_temp_dir}:/code:ro", image] + run_cmd,
                    input=tc.input_data,
                    capture_output=True,
                    text=True,
                    timeout=3.0
                )
                elapsed = time.time() - start
                max_time = max(max_time, elapsed)

                if proc.returncode != 0:
                    final_status = 'RE'
                    error_msg = proc.stderr.replace(f"/code/{filename}", "main" + ext)
                    break
                
                student_out = proc.stdout.strip()
                expected_out = tc.expected_output.strip()
                
                if problem.is_special_judge and problem.special_judge_script:
                    restricted_globals = {"__builtins__": {}}
                    local_vars = {
                        "output": student_out,
                        "input": tc.input_data,
                        "expected": expected_out,
                        "result": False
                    }
                    try:
                        exec(problem.special_judge_script, restricted_globals, local_vars)
                        if not local_vars.get("result", False):
                            final_status = 'WA'
                            break
                    except Exception as e:
                        final_status = 'RE'
                        error_msg = f"Special Judge Error: {str(e)}"
                        break
                else:
                    if student_out != expected_out:
                        final_status = 'WA'
                        break

            except subprocess.TimeoutExpired:
                final_status = 'TLE'
                error_msg = "Time Limit Exceeded (3.0s)"
                elapsed = 3.0
                max_time = max(max_time, elapsed)
                break

        submission.status = final_status
        submission.execution_time = round(max_time, 3)
        if error_msg:
            submission.error_message = error_msg
        
        if final_status == 'AC':
            submission.is_accepted = True

        submission.save()

        # Database Scoring Synchronization
        if final_status == 'AC':
            previous_ac = Submission.objects.filter(
                user=submission.user,
                problem=problem,
                is_accepted=True
            ).exclude(id=submission.id).exists()

            if not previous_ac:
                try:
                    cp = ContestProblem.objects.get(contest=submission.contest, problem=problem)
                    profile = submission.user.profile
                    profile.total_score += cp.points
                    profile.save()
                except ContestProblem.DoesNotExist:
                    pass
