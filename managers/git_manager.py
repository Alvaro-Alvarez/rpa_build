import logging
import subprocess
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

from config import MAIN_BRANCH, BUILD_VERSION, get_code_config

GIT_EXECUTABLE = "git"

logger = logging.getLogger(__name__)


class GitCommandError(RuntimeError):
    pass


def process_code_branch():
    c2is_path = get_code_config("C2IS").get("code_path")
    logger.info("Obteniendo rama actual del repositorio Git en %s", c2is_path)
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=c2is_path).stdout.strip()
    logger.info("Rama actual: %s", branch)
    if branch == MAIN_BRANCH:
        logger.info("Ya se esta en la rama objetivo '%s'", MAIN_BRANCH)
        # Asegurarnos de tener los ultimos cambios de remoto
        run_git_command(["pull"], cwd=c2is_path)  # equivale a 'git pull' en la rama actual
        return

    logger.info("Se requiere volver a la rama '%s'", MAIN_BRANCH)
    discard_local_changes()
    run_git_command(["checkout", MAIN_BRANCH], cwd=c2is_path)
    logger.info("Cambio de rama a '%s' completado", MAIN_BRANCH)
    # Luego de cambiar a main, traer los ultimos cambios remotos
    run_git_command(["pull"], cwd=c2is_path)  # equivale a 'git pull' en la rama actual
    logger.info("Se hace pull en la rama: '%s'", MAIN_BRANCH)
    


def discard_local_changes():
    c2is_path = get_code_config("C2IS").get("code_path")
    logger.info("Descartando cambios locales en %s", c2is_path)
    run_git_command(["reset", "--hard"], cwd=c2is_path)
    run_git_command(["clean", "-fd"], cwd=c2is_path)
    logger.info("Cambios locales descartados")


def process_code_branch_for(cwd: Path | str, main_branch: str = MAIN_BRANCH):
    """Igual que process_code_branch, pero apuntando a un repositorio específico."""
    logger.info("Obteniendo rama actual del repositorio Git en %s", cwd)
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).stdout.strip()
    logger.info("Rama actual: %s", branch)
    if branch == main_branch:
        logger.info("Ya se esta en la rama objetivo '%s'", main_branch)
        run_git_command(["pull"], cwd=cwd)
        return
    logger.info("Se requiere volver a la rama '%s'", main_branch)
    discard_local_changes_for(cwd)
    run_git_command(["checkout", main_branch], cwd=cwd)
    logger.info("Cambio de rama a '%s' completado", main_branch)
    run_git_command(["pull"], cwd=cwd)
    logger.info("Se hace pull en la rama: '%s'", main_branch)


def discard_local_changes_for(cwd: Path | str):
    logger.info("Descartando cambios locales en %s", cwd)
    run_git_command(["reset", "--hard"], cwd=cwd)
    run_git_command(["clean", "-fd"], cwd=cwd)
    logger.info("Cambios locales descartados en %s", cwd)


def run_git_command(command: Sequence[str], *, cwd: Path | str) -> subprocess.CompletedProcess:
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


def _get_current_branch(cwd: Path | str) -> str:
    return run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).stdout.strip()


def _get_remote_url(cwd: Path | str, remote: str = "origin") -> str:
    return run_git_command(["remote", "get-url", remote], cwd=cwd).stdout.strip()


def _run_external(command: Sequence[str], *, cwd: Path | str | None = None) -> subprocess.CompletedProcess:
    logger.info("Ejecutando comando externo: %s", " ".join(command))
    process = subprocess.run(
        list(command),
        cwd=cwd or get_code_config("C2IS").get("code_path"),
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
    # new_branch = 'test_robobuild_1'
    new_branch = _format_build_branch_name(BUILD_VERSION)

    logger.info("Creando/moviendo a la rama de build '%s' basada en '%s'", new_branch, base_branch)

    # Asegurar que la rama base existe localmente
    c2is_path = get_code_config("C2IS").get("code_path")
    run_git_command(["fetch", "--all", "--prune"], cwd=c2is_path)  # no falla si no hay remotos

    # Si la rama ya existe, solo cambiamos. Si no, la creamos desde base_branch.
    try:
        run_git_command(["rev-parse", "--verify", new_branch], cwd=c2is_path)
        logger.info("La rama '%s' ya existe localmente. Haciendo checkout...", new_branch)
        run_git_command(["checkout", new_branch], cwd=c2is_path)
    except GitCommandError:
        # Cambiar a base_branch para tener una referencia consistente al crear
        run_git_command(["checkout", base_branch], cwd=c2is_path)
        # Crear nueva rama desde base_branch
        run_git_command(["checkout", "-b", new_branch, base_branch], cwd=c2is_path)
    logger.info("Cambio de rama a '%s' completado", new_branch)
    return new_branch


def create_and_checkout_build_branch_for(cwd: Path | str, base_branch: str = MAIN_BRANCH) -> str:
    """Crea y hace checkout a la rama de build en el repo indicado por 'cwd'."""
    new_branch = _format_build_branch_name(BUILD_VERSION)
    logger.info("Creando/moviendo a la rama de build '%s' basada en '%s' en %s", new_branch, base_branch, cwd)
    run_git_command(["fetch", "--all", "--prune"], cwd=cwd)
    try:
        run_git_command(["rev-parse", "--verify", new_branch], cwd=cwd)
        logger.info("La rama '%s' ya existe localmente. Haciendo checkout...", new_branch)
        run_git_command(["checkout", new_branch], cwd=cwd)
    except GitCommandError:
        run_git_command(["checkout", base_branch], cwd=cwd)
        run_git_command(["checkout", "-b", new_branch, base_branch], cwd=cwd)
    logger.info("Cambio de rama a '%s' completado en %s", new_branch, cwd)
    return new_branch


def commit_and_push_all_changes(commit_message: str | None = None, remote: str = "origin") -> str:
    """Agrega todos los cambios, hace commit y push a la rama actual.

    - Crea upstream si no existe (`-u origin <branch>`)
    - Si no hay cambios, no hace commit y solo intenta publicar la rama.

    Devuelve el nombre de la rama actual.
    """
    c2is_path = get_code_config("C2IS").get("code_path")
    branch = _get_current_branch(c2is_path)
    logger.info("Preparando commit de cambios en la rama '%s'", branch)

    status = run_git_command(["status", "--porcelain"], cwd=c2is_path).stdout.strip()
    if status:
        run_git_command(["add", "-A"], cwd=c2is_path)
        message = commit_message or f"chore(build): publicar cambios para {BUILD_VERSION}"
        run_git_command(["commit", "-m", message], cwd=c2is_path)
        logger.info("Commit realizado: %s", message)
    else:
        logger.info("No hay cambios pendientes para commitear")

    # Push con upstream
    try:
        run_git_command(["push", "-u", remote, branch], cwd=c2is_path)
    except GitCommandError as e:
        # Si ya tiene upstream, intentar push simple
        logger.info("Fallo push con upstream. Intentando 'git push' simple: %s", e)
        run_git_command(["push"], cwd=c2is_path)

    logger.info("Push realizado a '%s/%s'", remote, branch)
    return branch


def commit_and_push_all_changes_for(
    cwd: Path | str,
    commit_message: str | None = None,
    remote: str = "origin",
    skip_files: Sequence[str] | None = None,
) -> str:
    """Agrega, commitea y hace push de cambios en el repo indicado por 'cwd'.

    Permite omitir archivos específicos al preparar el commit mediante `skip_files`.
    """
    branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).stdout.strip()
    logger.info("Preparando commit de cambios en la rama '%s' (%s)", branch, cwd)
    status = run_git_command(["status", "--porcelain"], cwd=cwd).stdout.strip()
    if status:
        run_git_command(["add", "-A"], cwd=cwd)
        if skip_files:
            for skip_file in skip_files:
                if not skip_file:
                    continue
                try:
                    file_status = run_git_command(
                        ["status", "--porcelain", "--", skip_file], cwd=cwd
                    ).stdout.strip()
                except GitCommandError:
                    continue
                if not file_status:
                    continue
                logger.info("Omitiendo archivo %s del commit en %s", skip_file, cwd)
                try:
                    run_git_command(["reset", "HEAD", "--", skip_file], cwd=cwd)
                except GitCommandError as exc:
                    logger.warning(
                        "No se pudo quitar %s del staging en %s: %s", skip_file, cwd, exc
                    )
        staged = run_git_command(["diff", "--cached", "--name-only"], cwd=cwd).stdout.strip()
        if staged:
            message = commit_message or f"chore(build): publicar cambios para {BUILD_VERSION}"
            run_git_command(["commit", "-m", message], cwd=cwd)
            logger.info("Commit realizado: %s", message)
        else:
            logger.info("No hay cambios pendientes para commitear en %s despues de omitir archivos", cwd)
    else:
        logger.info("No hay cambios pendientes para commitear en %s", cwd)
    try:
        run_git_command(["push", "-u", remote, branch], cwd=cwd)
    except GitCommandError as e:
        logger.info("Fallo push con upstream. Intentando 'git push' simple en %s: %s", cwd, e)
        run_git_command(["push"], cwd=cwd)
    logger.info("Push realizado a '%s/%s' (%s)", remote, branch, cwd)
    return branch


def create_pull_request_to_main(title: str | None = None, body: str | None = None, remote: str = "origin") -> str:
    """Crea un Pull Request desde la rama actual hacia MAIN_BRANCH para TFS.

    Construye y devuelve la URL de creación de PR en TFS (on‑prem) basada en el remoto.
    """
    c2is_path = get_code_config("C2IS").get("code_path")
    source_branch = _get_current_branch(c2is_path)
    if source_branch == MAIN_BRANCH:
        raise GitCommandError("No se puede crear PR desde la rama principal hacia sí misma")

    remote_url = _get_remote_url(c2is_path, remote)
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
