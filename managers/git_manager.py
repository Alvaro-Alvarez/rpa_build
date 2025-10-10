import logging
import subprocess
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

from config import C2IS_CODE_PATH, MAIN_BRANCH, BUILD_VERSION

GIT_EXECUTABLE = "git"

logger = logging.getLogger(__name__)


class GitCommandError(RuntimeError):
    pass


def process_code_branch():
    logger.info("Obteniendo rama actual del repositorio Git en %s", C2IS_CODE_PATH)
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    logger.info("Rama actual: %s", branch)
    if branch == MAIN_BRANCH:
        logger.info("Ya se esta en la rama objetivo '%s'", MAIN_BRANCH)
        return

    logger.info("Se requiere volver a la rama '%s'", MAIN_BRANCH)
    discard_local_changes()
    run_git_command(["checkout", MAIN_BRANCH])
    logger.info("Cambio de rama a '%s' completado", MAIN_BRANCH)


def discard_local_changes():
    logger.info("Descartando cambios locales en %s", C2IS_CODE_PATH)
    run_git_command(["reset", "--hard"])
    run_git_command(["clean", "-fd"])
    logger.info("Cambios locales descartados")


def run_git_command(command: Sequence[str], *, cwd: Path | str = C2IS_CODE_PATH) -> subprocess.CompletedProcess:
    logger.info("Ejecutando comando Git: %s", " ".join([GIT_EXECUTABLE, *command]))
    process = subprocess.run(
        [GIT_EXECUTABLE, *command],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        logger.error("Error al ejecutar git %s: %s", " ".join(command), message)
        raise GitCommandError(f"Fallo al ejecutar git {' '.join(command)}: {message}")

    logger.info("Comando git '%s' ejecutado correctamente", " ".join(command))
    return process


def _format_build_branch_name(version: str = BUILD_VERSION) -> str:
    return f"build_{version.replace('.', '_')}"


def _get_current_branch() -> str:
    return run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def _get_remote_url(remote: str = "origin") -> str:
    return run_git_command(["remote", "get-url", remote]).stdout.strip()


def _run_external(command: Sequence[str]) -> subprocess.CompletedProcess:
    logger.info("Ejecutando comando externo: %s", " ".join(command))
    process = subprocess.run(
        list(command),
        cwd=C2IS_CODE_PATH,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        logger.error("Error al ejecutar comando externo %s: %s", " ".join(command), message)
        raise RuntimeError(f"Fallo al ejecutar {' '.join(command)}: {message}")
    logger.info("Comando externo '%s' ejecutado correctamente", " ".join(command))
    return process


def create_and_checkout_build_branch(base_branch: str = MAIN_BRANCH) -> str:
    """Crea y hace checkout a una nueva rama de build.

    - Nombre: build_<BUILD_VERSION con '.' -> '_'> (ej: build_1_14_4_00)
    - Base: rama indicada (por defecto MAIN_BRANCH)

    Devuelve el nombre de la nueva rama.
    """
    new_branch = _format_build_branch_name(BUILD_VERSION)

    logger.info("Creando/moviendo a la rama de build '%s' basada en '%s'", new_branch, base_branch)

    # Asegurar que la rama base existe localmente
    run_git_command(["fetch", "--all", "--prune"])  # no falla si no hay remotos

    # Si la rama ya existe, solo cambiamos. Si no, la creamos desde base_branch.
    try:
        run_git_command(["rev-parse", "--verify", new_branch])
        logger.info("La rama '%s' ya existe localmente. Haciendo checkout...", new_branch)
        run_git_command(["checkout", new_branch])
    except GitCommandError:
        # Cambiar a base_branch para tener una referencia consistente al crear
        run_git_command(["checkout", base_branch])
        # Crear nueva rama desde base_branch
        run_git_command(["checkout", "-b", new_branch, base_branch])
    logger.info("Cambio de rama a '%s' completado", new_branch)
    return new_branch


def commit_and_push_all_changes(commit_message: str | None = None, remote: str = "origin") -> str:
    """Agrega todos los cambios, hace commit y push a la rama actual.

    - Crea upstream si no existe (`-u origin <branch>`)
    - Si no hay cambios, no hace commit y solo intenta publicar la rama.

    Devuelve el nombre de la rama actual.
    """
    branch = _get_current_branch()
    logger.info("Preparando commit de cambios en la rama '%s'", branch)

    status = run_git_command(["status", "--porcelain"]).stdout.strip()
    if status:
        run_git_command(["add", "-A"])
        message = commit_message or f"chore(build): publicar cambios para {BUILD_VERSION}"
        run_git_command(["commit", "-m", message])
        logger.info("Commit realizado: %s", message)
    else:
        logger.info("No hay cambios pendientes para commitear")

    # Push con upstream
    try:
        run_git_command(["push", "-u", remote, branch])
    except GitCommandError as e:
        # Si ya tiene upstream, intentar push simple
        logger.info("Fallo push con upstream. Intentando 'git push' simple: %s", e)
        run_git_command(["push"])

    logger.info("Push realizado a '%s/%s'", remote, branch)
    return branch


def create_pull_request_to_main(title: str | None = None, body: str | None = None, remote: str = "origin") -> str:
    """Crea un Pull Request desde la rama actual hacia MAIN_BRANCH para TFS.

    Construye y devuelve la URL de creación de PR en TFS (on‑prem) basada en el remoto.
    """
    source_branch = _get_current_branch()
    if source_branch == MAIN_BRANCH:
        raise GitCommandError("No se puede crear PR desde la rama principal hacia sí misma")

    remote_url = _get_remote_url(remote)
    logger.info("Construyendo URL de creación de PR para TFS...")
    pr_url = _build_pr_url(remote_url, source_branch, MAIN_BRANCH)
    logger.info("Cree el PR manualmente en: %s", pr_url)
    return pr_url


def _build_pr_url(remote_url: str, source_branch: str, target_branch: str) -> str:
    """Construye la URL de creación de PR para TFS/Azure DevOps (on‑prem o similar).

    Para remotos con patrón `.../_git/...` genera:
    `.../_git/<repo>/pullrequestcreate?sourceRef=refs/heads/<source>&targetRef=refs/heads/<target>`
    En otros casos, devuelve el remoto como referencia.
    """
    url = remote_url[:-4] if remote_url.endswith(".git") else remote_url
    if "/_git/" in url:
        return (
            f"{url}/pullrequestcreate?"
            f"sourceRef={quote('refs/heads/' + source_branch)}&"
            f"targetRef={quote('refs/heads/' + target_branch)}"
        )
    return url
