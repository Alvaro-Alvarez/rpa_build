import subprocess
from config import C2IS_CODE_PATH, MAIN_BRANCH

def process_code_branch():
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != MAIN_BRANCH:
        # Descartar cambios
        run_git_command(["reset", "--hard"])
        run_git_command(["clean", "-fd"])
        # Cambiar a dev
        run_git_command(["checkout", MAIN_BRANCH])

def run_git_command(command, cwd=C2IS_CODE_PATH):
    result = subprocess.run(["git"] + command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    else:
        print(result.stdout)
    return result