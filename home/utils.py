import subprocess
import tempfile
import os
import shutil

def judge_problem(code: str, language, test_cases, stop_on_fail=True) -> list:
    """
    Evaluates code against a set of test cases in a single Docker container batch run.
    Returns a list of dictionaries formatted for the frontend terminal.
    """
    temp_dir = os.path.abspath(tempfile.mkdtemp()).replace('\\', '/')
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
            input_path = os.path.join(temp_dir, f"input_{tc_id}.txt")
            with open(input_path, 'w', encoding='utf-8', newline='\n') as f:
                input_data = (tc.input_data or "").replace('\r\n', '\n')
                f.write(input_data)

        # 3. Generate runner.sh
        # Compute global ceiling: hard cap at 15s. The inner per-case timeout (5s)
        # already handles individual TLEs. The outer timeout is just a safety net
        # to kill a completely runaway container (e.g. fork bombs, kernel bugs).
        per_case_limit = 5
        global_limit = 15  # hard wall

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
                f.write(f"timeout {per_case_limit} sh wrapper.sh {run_cmd} < input_{tc_id}.txt > output_{tc_id}.txt 2> error_{tc_id}.txt\n")
                f.write("RET=$?\n")
                f.write(f"echo $RET > status_{tc_id}.txt\n")
                if stop_on_fail:
                    # Exit the script immediately on any failure (TLE=124, RE=non-0, WA caught later)
                    f.write("if [ $RET -ne 0 ]; then exit 1; fi\n")
                f.write("\n")

        # 4. Ensure Docker image is pulled
        inspect_result = subprocess.run(['docker', 'image', 'inspect', language.docker_image], capture_output=True)
        if inspect_result.returncode != 0:
            print(f"[DEBUG] Pulling image {language.docker_image}...")
            subprocess.run(['docker', 'pull', language.docker_image], capture_output=True, timeout=120)

        # 5. Run Docker Batch — outer Python timeout = global_limit + 5s grace for docker startup
        docker_cmd = [
            'docker', 'run', '--rm', '-i',
            '--network', 'none',
            '--memory', '256m',
            '--cpus', '1.0',
            '-v', f'{temp_dir}:/usr/src/app',
            '-w', '/usr/src/app',
            language.docker_image,
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
                
            output_path = os.path.join(temp_dir, f"output_{tc_id}.txt")
            error_path = os.path.join(temp_dir, f"error_{tc_id}.txt")
            
            actual = ""
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8') as f:
                    actual = f.read().strip().replace('\r\n', '\n')
                    
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
                    
            expected = tc.expected_output.strip().replace('\r\n', '\n')
            
            if ret_code == 124 or ret_code == 137 or ret_code == 143:
                status = 'TLE'
                time_val = float(per_case_limit)
            elif ret_code != 0:
                status = 'RE'
            else:
                if expected == actual:
                    status = 'AC'
                else:
                    status = 'WA'
                    
            row = {
                'id': str(idx).zfill(2),
                'status': 'pass' if status == 'AC' else ('tle' if status == 'TLE' else 'fail'),
                'label': label_map.get(status, 'ERROR'),
                'stdout': actual,
                'stderr': stderr,
                'expected': expected,
                'time': f"{time_val:.3f}s",
                'mem_kb': mem_val
            }
            results.append(row)
            
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
