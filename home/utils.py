import subprocess
import tempfile
import os
import shutil

def run_in_docker(code: str, language, input_data: str) -> dict:
    """
    Executes the given code inside a docker container and returns the output.
    Returns a dict with 'status' and optional 'output' or 'error'.
    """
    input_data = input_data or ""
    temp_dir = os.path.abspath(tempfile.mkdtemp()).replace('\\', '/')
    
    try:
        # Write user code
        filename = f"solution{language.extension}"
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(code)
            
        # Ensure Docker image is pulled
        inspect_result = subprocess.run(['docker', 'image', 'inspect', language.docker_image], capture_output=True)
        if inspect_result.returncode != 0:
            print(f"[DEBUG] Pulling image {language.docker_image}...")
            subprocess.run(['docker', 'pull', language.docker_image], capture_output=True, timeout=120)
            
        # Prepare commands
        # Enforce execution timeout inside the container
        run_cmd = f"timeout 5 {language.run_command.replace('{filename}', filename)}"
        
        if language.compile_command:
            compile_cmd = language.compile_command.replace('{filename}', filename)
            full_cmd = f"{compile_cmd} && {run_cmd}"
        else:
            full_cmd = run_cmd
        
        # Build Docker command
        docker_cmd = [
            'docker', 'run', '--rm', '-i',
            '--network', 'none',
            '--memory', '256m',
            '--cpus', '1.0',
            '-v', f'{temp_dir}:/usr/src/app',
            '-w', '/usr/src/app',
            language.docker_image,
            '/bin/sh', '-c', full_cmd
        ]
        
        # Run process
        print(f"[DEBUG] Executing: {' '.join(docker_cmd)}")
        result = subprocess.run(
            docker_cmd,
            input=input_data.encode('utf-8'),
            capture_output=True,
            timeout=45
        )
        
        stderr = result.stderr.decode('utf-8').strip()
        stdout = result.stdout.decode('utf-8').strip()
        
        print("--- DOCKER STDOUT ---")
        print(stdout)
        print("--- DOCKER STDERR ---")
        print(stderr)
        print("---------------------")
        
        if result.returncode != 0:
            if result.returncode in (124, 137, 143):
                return {'status': 'TLE'}
            return {'status': 'RE', 'error': stderr or stdout or "Unknown runtime error"}
            
        return {'status': 'SUCCESS', 'output': stdout}
        
    except subprocess.TimeoutExpired:
        return {'status': 'TLE'}
    except Exception as e:
        print(f"[DEBUG] Exception in run_in_docker: {str(e)}")
        return {'status': 'RE', 'error': str(e)}
    finally:
        # Clean up
        shutil.rmtree(temp_dir, ignore_errors=True)
