import subprocess
from pathlib import Path
from typing import Sequence

from config import C2IS_CODE_PATH, MAIN_BRANCH

GIT_EXECUTABLE = "git"


class GitCommandError(RuntimeError):
    pass


def process_code_branch():
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch == MAIN_BRANCH:
        return

    discard_local_changes()
    run_git_command(["checkout", MAIN_BRANCH])


def discard_local_changes():
    run_git_command(["reset", "--hard"])
    run_git_command(["clean", "-fd"])


def run_git_command(command: Sequence[str], *, cwd: Path | str = C2IS_CODE_PATH) -> subprocess.CompletedProcess:
    process = subprocess.run(
        [GIT_EXECUTABLE, *command],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        raise GitCommandError(f"Fallo al ejecutar git {' '.join(command)}: {message}")

    return process
