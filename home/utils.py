import subprocess
import tempfile
import os
import shutil

def judge_problem(code: str, language, test_cases, stop_on_fail=True) -> list:
    """
    Evaluates code against a set of test cases in a single Docker container batch run.
    Returns a list of dictionaries formatted for the frontend terminal.
    """
    from django.conf import settings
    runner = getattr(settings, 'CONTAINER_RUNNER', 'podman')
    
    # Use /dev/shm (tmpfs RAM disk) if on Linux and exists, otherwise system temp
    temp_parent = '/dev/shm' if os.path.exists('/dev/shm') else None
    temp_dir = os.path.abspath(tempfile.mkdtemp(dir=temp_parent)).replace('\\', '/')
    results = []
    
    label_map = {
        'AC': 'PASSED',
        'WA': 'WRONG ANSWER',
        'TLE': 'TIME LIMIT',
        'RE': 'RUNTIME ERROR',
        'CE': 'COMPILE ERROR'
    }

    try:
        # 1. Write user code
        filename = f"solution{language.extension}"
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(code.replace('\r\n', '\n'))
            
        # 2. Write all input files
        for tc in test_cases:
            tc_id = str(tc.id)
            tc_input_format = getattr(tc, 'input_format', 'EDITOR')
            if tc_input_format == 'UPLOAD':
                tc_input_filename = getattr(tc, 'input_filename', None) or 'input.txt'
                # Reconstruct and validate path traversal
                target_path = os.path.abspath(os.path.join(temp_dir, tc_input_filename))
                real_temp_dir = os.path.abspath(temp_dir)
                if not target_path.startswith(real_temp_dir + os.sep) and target_path != real_temp_dir:
                    raise ValueError(f"Path traversal detected in input filename: {tc_input_filename}")
                
                # Write uploaded file content to unique path that runner.sh will copy
                upload_input_path = os.path.join(temp_dir, f"input_{tc_id}_upload.txt")
                input_file = getattr(tc, 'input_file', None)
                if input_file:
                    try:
                        with input_file.open('rb') as src:
                            content = src.read()
                        with open(upload_input_path, 'wb') as dst:
                            dst.write(content)
                    except Exception as e:
                        # Fallback empty write if read fails
                        with open(upload_input_path, 'wb') as dst:
                            dst.write(b"")
                else:
                    # Fallback to input_data if input_file is not set
                    with open(upload_input_path, 'w', encoding='utf-8', newline='\n') as f:
                        input_data = (tc.input_data or "").replace('\r\n', '\n')
                        f.write(input_data)
            else:
                input_path = os.path.join(temp_dir, f"input_{tc_id}.txt")
                with open(input_path, 'w', encoding='utf-8', newline='\n') as f:
                    input_data = (tc.input_data or "").replace('\r\n', '\n')
                    f.write(input_data)

        # 3. Generate runner.sh
        # Compute dynamic per-case time limit. Fallback to 2.5s.
        per_case_limit = 2.5
        if test_cases and hasattr(test_cases[0], 'problem') and hasattr(test_cases[0].problem, 'time_limit'):
            if test_cases[0].problem.time_limit is not None:
                per_case_limit = float(test_cases[0].problem.time_limit)
        
        # Compute global ceiling limit
        global_limit = max(15, int(per_case_limit * len(test_cases) + 5))

        # Wrapper script for precise time & peak memory measurement
        wrapper_path = os.path.join(temp_dir, 'wrapper.py')
        with open(wrapper_path, 'w', encoding='utf-8') as f:
            f.write('''import sys, subprocess, time, resource
cmd = sys.argv[1:]
start = time.perf_counter()
try:
    p = subprocess.Popen(cmd)
    p.wait()
    end = time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    mem_kb = usage.ru_maxrss
    print(f"\\n---STATS---\\nTIME:{end-start:.3f}\\nMEM:{mem_kb}", file=sys.stderr)
    sys.exit(p.returncode)
except Exception:
    print(f"\\n---STATS---\\nTIME:0.000\\nMEM:0", file=sys.stderr)
    sys.exit(1)
''')

        # Shell wrapper for robust language fallback when Python is not available
        wrapper_sh_path = os.path.join(temp_dir, 'wrapper.sh')
        with open(wrapper_sh_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write('''#!/bin/sh
CMD="$@"

# Check for python3 or python
if command -v python3 >/dev/null 2>&1; then
    exec python3 wrapper.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python wrapper.py "$@"
fi

# Fallback shell timing and peak memory cgroup read
START_S=$(date +%s 2>/dev/null || echo 0)
START_N=$(date +%s%N 2>/dev/null || echo 0)

$CMD
RET=$?

END_S=$(date +%s 2>/dev/null || echo 0)
END_N=$(date +%s%N 2>/dev/null || echo 0)

case "$START_N" in
    *N* | "" | "0")
        ELAPSED_S=$(( END_S - START_S ))
        TIME_VAL="${ELAPSED_S}.000"
        ;;
    *)
        ELAPSED_MS=$(( (END_N - START_N) / 1000000 ))
        TIME_VAL=$(printf "%d.%03d" $((ELAPSED_MS / 1000)) $((ELAPSED_MS % 1000)))
        ;;
esac

MEM_KB=0
if [ -f /sys/fs/cgroup/memory/memory.max_usage_in_bytes ]; then
    MEM_BYTES=$(cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes)
    MEM_KB=$(( MEM_BYTES / 1024 ))
elif [ -f /sys/fs/cgroup/memory.peak ]; then
    MEM_BYTES=$(cat /sys/fs/cgroup/memory.peak)
    MEM_KB=$(( MEM_BYTES / 1024 ))
fi

echo "" >&2
echo "---STATS---" >&2
echo "TIME:$TIME_VAL" >&2
echo "MEM:$MEM_KB" >&2

exit $RET
''')

        runner_path = os.path.join(temp_dir, 'runner.sh')
        with open(runner_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write("#!/bin/sh\n")

            # Compilation phase
            if language.compile_command:
                compile_cmd = language.compile_command.replace('{filename}', filename)
                f.write(f"{compile_cmd} > compile_out.txt 2>&1\n")
                f.write("if [ $? -ne 0 ]; then\n")
                f.write("    echo '1' > compile_status.txt\n")
                f.write("    exit 1\n")
                f.write("fi\n")
            f.write("echo '0' > compile_status.txt\n\n")

            # Execution phase
            run_cmd = language.run_command.replace('{filename}', filename)
            for tc in test_cases:
                tc_id = str(tc.id)
                tc_input_format = getattr(tc, 'input_format', 'EDITOR')
                tc_input_filename = getattr(tc, 'input_filename', None)
                tc_output_format = getattr(tc, 'output_format', 'EDITOR')
                tc_output_filename = getattr(tc, 'output_filename', None)

                # If input is UPLOAD, copy it to the container's expected location
                if tc_input_format == 'UPLOAD' and tc_input_filename:
                    f.write(f"cp input_{tc_id}_upload.txt {tc_input_filename}\n")

                # Run command
                if tc_input_format == 'EDITOR':
                    f.write(f"timeout {per_case_limit} sh wrapper.sh {run_cmd} < input_{tc_id}.txt > output_{tc_id}.txt 2> error_{tc_id}.txt\n")
                else:
                    # Input is UPLOAD format: ignore/no stdin redirection
                    f.write(f"timeout {per_case_limit} sh wrapper.sh {run_cmd} < /dev/null > output_{tc_id}.txt 2> error_{tc_id}.txt\n")
                
                f.write("RET=$?\n")
                f.write(f"echo $RET > status_{tc_id}.txt\n")

                # Clean up copied input file
                if tc_input_format == 'UPLOAD' and tc_input_filename:
                    f.write(f"rm -f {tc_input_filename}\n")

                # For UPLOAD output, move the generated output file to a unique name
                if tc_output_format == 'UPLOAD' and tc_output_filename:
                    f.write(f"if [ -f {tc_output_filename} ]; then mv {tc_output_filename} output_{tc_id}_upload.txt; fi\n")

                if stop_on_fail:
                    # Exit the script immediately on any failure (TLE=124, RE=non-0, WA caught later)
                    f.write("if [ $RET -ne 0 ]; then exit 1; fi\n")
                f.write("\n")

        # 4. Ensure container image is pulled
        image_name = language.docker_image
        parts = image_name.split('/')
        if len(parts) == 1:
            # Single-word name (e.g. 'gcc:latest') -> official docker library image
            image_name = f"docker.io/library/{image_name}"
        elif '.' not in parts[0] and ':' not in parts[0] and parts[0] != 'localhost':
            # E.g. 'library/gcc:latest' or 'ubuntu/nginx' -> prefix docker.io/
            image_name = f"docker.io/{image_name}"

        inspect_result = subprocess.run([runner, 'image', 'inspect', image_name], capture_output=True)
        if inspect_result.returncode != 0:
            print(f"[DEBUG] Pulling image {image_name}...")
            subprocess.run([runner, 'pull', image_name], capture_output=True, timeout=120)

        # 5. Run Container Batch — outer Python timeout = global_limit + 5s grace for container startup
        vol_suffix = ':z' if runner == 'podman' else ''
        docker_cmd = [
            runner, 'run', '--rm', '-i',
            '--network', 'none',
            '--memory', '256m',
            '--cpus', '1.0',
            '-v', f'{temp_dir}:/usr/src/app{vol_suffix}',
            '-w', '/usr/src/app',
            image_name,
            '/bin/sh', '-c', f'timeout {global_limit} /bin/sh runner.sh'
        ]

        print(f"[DEBUG] Executing Batch (global_limit={global_limit}s): {' '.join(docker_cmd)}")
        subprocess.run(docker_cmd, capture_output=True, timeout=global_limit + 5)

        # 6. Parse Results
        compile_status_path = os.path.join(temp_dir, 'compile_status.txt')
        if os.path.exists(compile_status_path):
            with open(compile_status_path, 'r', encoding='utf-8') as f:
                compile_status = f.read().strip()
            if compile_status != '0':
                compile_out = ""
                compile_out_path = os.path.join(temp_dir, 'compile_out.txt')
                if os.path.exists(compile_out_path):
                    with open(compile_out_path, 'r', encoding='utf-8') as f:
                        compile_out = f.read().strip()
                
                # Fast fail all test cases as CE
                for idx, tc in enumerate(test_cases, 1):
                    results.append({
                        'id': str(idx).zfill(2),
                        'status': 'fail',
                        'label': 'COMPILE ERROR',
                        'stdout': '',
                        'stderr': compile_out,
                        'expected': tc.expected_output.strip(),
                        'time': '0.0s'
                    })
                return results

        # Iterate over test cases and check outputs
        for idx, tc in enumerate(test_cases, 1):
            tc_id = str(tc.id)
            status_path = os.path.join(temp_dir, f"status_{tc_id}.txt")
            
            # If status file doesn't exist, the container aborted early (RE/TLE in a previous case)
            if not os.path.exists(status_path):
                break
                
            with open(status_path, 'r', encoding='utf-8') as f:
                ret_code = int(f.read().strip())
                
            tc_output_format = getattr(tc, 'output_format', 'EDITOR')
            tc_output_filename = getattr(tc, 'output_filename', None)
            
            output_path = os.path.join(temp_dir, f"output_{tc_id}.txt")
            error_path = os.path.join(temp_dir, f"error_{tc_id}.txt")

            actual = ""
            is_rule_violation = False
            violation_msg = ""

            if tc_output_format == 'EDITOR':
                if os.path.exists(output_path):
                    with open(output_path, 'r', encoding='utf-8') as f:
                        actual = f.read().strip().replace('\r\n', '\n')
            else:
                # UPLOAD format
                # Security Check: verify that the student's program did not forge symbolic links
                # pointing outside the sandbox boundary.
                out_filename_path = os.path.join(temp_dir, tc_output_filename) if tc_output_filename else None
                out_upload_path = os.path.join(temp_dir, f"output_{tc_id}_upload.txt")
                
                # Check for symlink
                if (out_filename_path and os.path.islink(out_filename_path)) or os.path.islink(out_upload_path):
                    is_rule_violation = True
                    violation_msg = "Security Rule Violation: Symbolic link detected."
                else:
                    # If valid, extract its contents
                    if os.path.exists(out_upload_path):
                        with open(out_upload_path, 'r', encoding='utf-8') as f:
                            actual = f.read().strip().replace('\r\n', '\n')
                    else:
                        actual = "" # output file was not generated

            stderr = ""
            time_val = 0.0
            mem_val = 0
            if os.path.exists(error_path):
                with open(error_path, 'r', encoding='utf-8') as f:
                    err_raw = f.read().strip().replace('\r\n', '\n')
                    err_lines = err_raw.split('\n')
                    
                try:
                    if len(err_lines) >= 3 and err_lines[-3] == '---STATS---':
                        time_val = float(err_lines[-2].split(':')[1])
                        mem_val = int(err_lines[-1].split(':')[1])
                        stderr = '\n'.join(err_lines[:-3]).strip()
                    else:
                        stderr = err_raw
                except:
                    stderr = err_raw
                    
            expected = ""
            if tc_output_format == 'UPLOAD':
                output_file = getattr(tc, 'output_file', None)
                if output_file:
                    try:
                        with output_file.open('rb') as f:
                            expected_bytes = f.read()
                        expected = expected_bytes.decode('utf-8', errors='ignore').strip().replace('\r\n', '\n')
                    except Exception as e:
                        expected = ""
                else:
                    expected = getattr(tc, 'expected_output', '').strip().replace('\r\n', '\n')
            else:
                expected = getattr(tc, 'expected_output', '').strip().replace('\r\n', '\n')
            
            if is_rule_violation:
                status = 'RE'
                stderr = violation_msg
                label = 'RULE VIOLATION'
            elif ret_code == 124 or ret_code == 137 or ret_code == 143:
                status = 'TLE'
                time_val = float(per_case_limit)
                label = 'TIME LIMIT'
            elif ret_code != 0:
                status = 'RE'
                label = 'RUNTIME ERROR'
            else:
                if expected == actual:
                    status = 'AC'
                    label = 'PASSED'
                else:
                    status = 'WA'
                    label = 'WRONG ANSWER'
                    
            row = {
                'id': str(idx).zfill(2),
                'status': 'pass' if status == 'AC' else ('tle' if status == 'TLE' else 'fail'),
                'label': label,
                'stdout': actual,
                'stderr': stderr,
                'expected': expected,
                'time': f"{time_val:.3f}s",
                'mem_kb': mem_val
            }
            results.append(row)
            
            if is_rule_violation:
                # Abort execution of remaining test cases instantly
                break

            if stop_on_fail and status != 'AC':
                break

    except subprocess.TimeoutExpired:
        # If the overall 45s timeout hits, the last running testcase gets a TLE.
        # Actually, let's just append a TLE to the end of whatever we have so far.
        idx = len(results) + 1
        tc = test_cases[idx - 1] if idx <= len(test_cases) else None
        if tc:
            results.append({
                'id': str(idx).zfill(2),
                'status': 'tle',
                'label': 'TIME LIMIT',
                'stdout': '',
                'stderr': 'Global 45s execution limit exceeded.',
                'expected': tc.expected_output.strip() if tc else '',
                'time': '45.0s'
            })
    except Exception as e:
        print(f"[DEBUG] Exception in judge_problem: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        
    return results
