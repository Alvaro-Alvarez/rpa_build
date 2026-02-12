import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from enums.enums import Accion
from managers import file_manager, git_manager, ia_manager, jira_manager, rpa_manager
from managers.tfs_manager import TfsManager
from config import (
    BUILD_CCSI_DIRECTORY,
    BUILDS_PACKAGE_DIRECTORY,
    BUILDS_PACKAGE_FOLDERS,
    CCSI_COMMON_ENABLED,
    CURRENT_VERSION_CCSI,
    MAIN_BRANCH,
    NEXT_VERSION_CCSI,
    TEAMS_CONFIRMATION_PARTICIPANTS,
    get_code_config,
    get_enabled_codes,
    get_enabled_codes_with_aip,
)
from logging_config import setup_logging
from managers.teams_manager import open_teams_and_send_message, wait_for_ok_confirmations

logger = logging.getLogger(__name__)


def _powershell_escape(path: Path) -> str:
    """Escapa rutas para ser utilizadas en strings de PowerShell."""
    return str(path).replace("'", "''")


def _create_shortcut(shortcut_path: Path, target_path: Path) -> None:
    """Crea o reemplaza un acceso directo de Windows apuntando a target_path."""
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    shortcut_path.unlink(missing_ok=True)
    command = (
        "$WshShell = New-Object -ComObject WScript.Shell; "
        f"$Shortcut = $WshShell.CreateShortcut('{_powershell_escape(shortcut_path)}'); "
        f"$Shortcut.TargetPath = '{_powershell_escape(target_path)}'; "
        "$Shortcut.Save();"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Error creando acceso directo {shortcut_path}: {result.stderr.strip() or result.stdout.strip()}"
        )


def start_building(actions: Iterable[Accion]) -> None:
    # _execute_action(Accion.GET_JIRA_ISSUES)
    for action in actions:
        logger.info("Ejecutando paso: %s", action.value)
        _execute_action(action)
        logger.info("Paso finalizado: %s", action.value)

def _execute_action(action: Accion) -> None:
    match action:
        case Accion.GET_JIRA_ISSUES:
            issues_extended = jira_manager.get_jira_issues_validate_tags()
            if issues_extended:
                open_teams_and_send_message(issues_extended)
                # Esperar confirmaciones solo de responsables presentes en los jiras
                responsible_keys = {(it.get("assignee_jira_key") or "").strip() for it in issues_extended}
                responsible_keys.discard("")
                participants_to_wait = [
                    p for p in TEAMS_CONFIRMATION_PARTICIPANTS
                    if (p.get("jira_key") or "").strip() in responsible_keys
                ]
                # Fallback por nombre si no hubo match por key
                if not participants_to_wait:
                    responsible_names = {(it.get("assignee_name") or "").strip() for it in issues_extended}
                    responsible_names.discard("")
                    participants_to_wait = [
                        p for p in TEAMS_CONFIRMATION_PARTICIPANTS
                        if (p.get("name") or "").strip() in responsible_names
                    ]
                decision = wait_for_ok_confirmations(participants=participants_to_wait) if participants_to_wait else "ok"
            else:
                decision = "ok"
            if decision == "restart":
                logger.warning("Se solicito reinicio desde Teams; reiniciando paso GET_JIRA_ISSUES.")
                _execute_action(Accion.GET_JIRA_ISSUES)
                return
            if decision == "force":
                logger.warning("Se forzo el avance desde Teams; continuando sin todas las confirmaciones.")
            issues = jira_manager.get_jira_issues()
            jira_manager.export_issues(issues)

            if not ia_manager.valid_json():
                logger.error("Validacion de JSON fallo")
                raise ValueError("El json de issues de jira no esta bien formateado.")
        case Accion.UPDATE_CHANGE_LOG:
            # Asegurar que C2IS (único que modifica change log) esté en main
            c2is_path = get_code_config("C2IS").get("code_path")
            git_manager.process_code_branch_for(c2is_path, MAIN_BRANCH)
            file_manager.update_change_log()
        case Accion.UPDATE_ASSEMBLY_VERSIONS:
            # Asegurar rama main en cada código habilitado antes de modificar archivos
            for _name, conf in get_enabled_codes():
                git_manager.process_code_branch_for(conf.get("code_path"), conf.get("main_branch", MAIN_BRANCH))
            file_manager.update_assembly_versions()
        case Accion.UPDATE_AIP_VERSIONS:
            codes_with_aip = get_enabled_codes_with_aip()
            if not codes_with_aip:
                logger.info("No hay códigos habilitados con paquetes AIP para actualizar; se omite el paso.")
                return
            # Asegurar rama main solo en los códigos que tienen AIPs configurados
            for _name, conf in codes_with_aip:
                git_manager.process_code_branch_for(conf.get("code_path"), conf.get("main_branch", MAIN_BRANCH))
            rpa_manager.update_aip_versions()
        case Accion.UPLOAD_CODE_AND_PR:
            # Crear rama, commitear, pushear y generar PR para todos los códigos habilitados
            import os
            branches: list[tuple[str, dict, str]] = []  # (code_name, conf, branch)
            codes_to_process = list(get_enabled_codes())
            if not codes_to_process:
                logger.info("No hay códigos habilitados para publicar cambios.")
                return

            for code_name, conf in codes_to_process:
                code_path = conf.get("code_path")
                base_branch = conf.get("main_branch", MAIN_BRANCH)
                git_manager.process_code_branch_for(code_path, base_branch)
                build_branch = git_manager.create_and_checkout_build_branch_for(code_path, base_branch)
                current_branch = git_manager.commit_and_push_all_changes_for(
                    code_path, skip_files=(".gitignore",)
                )
                branches.append((code_name, conf, current_branch or build_branch))

            for code_name, conf, branch in branches:
                tfs = (conf.get("tfs") or {}).copy()
                build_definition_id = tfs.get("BUILD_DEFINITION_ID")
                poll_interval = tfs.get("TFS_POLL_INTERVAL")
                timeout_secs = tfs.get("TFS_TIMEOUT_SECS")
                # Preparar variables por código
                if tfs.get("BUILD_DEFINITION_IDS"):
                    os.environ["BUILD_DEFINITION_IDS"] = str(tfs.get("BUILD_DEFINITION_IDS"))
                elif tfs.get("BUILD_DEFINITION_ID") is not None:
                    os.environ["BUILD_DEFINITION_ID"] = str(tfs.get("BUILD_DEFINITION_ID"))
                # Instanciar gestor con parámetros específicos
                tm = TfsManager(
                    org=str(tfs.get("ORG") or ""),
                    project=str(tfs.get("PROJECT") or ""),
                    pat=str(tfs.get("PAT") or ""),
                    base_url=str(tfs.get("BASE_URL") or ""),
                    repo_id=str(tfs.get("REPO_ID") or ""),
                    build_definition_id=int(build_definition_id) if build_definition_id not in (None, "") else None,
                    poll_interval=int(poll_interval) if poll_interval not in (None, "") else None,
                    timeout_secs=int(timeout_secs) if timeout_secs not in (None, "") else None,
                    git_api_version=str(tfs.get("TFS_GIT_API_VERSION") or ""),
                    build_api_version=str(tfs.get("TFS_BUILD_API_VERSION") or ""),
                )
                tm.run_pr_pipeline(source_branch=branch, target_branch=conf.get("main_branch", MAIN_BRANCH), repo_id=str(tfs.get("REPO_ID") or ""))
            # TfsManager().run_pr_pipeline(source_branch='test_robobuild_1' or 'test_robobuild_1', target_branch=MAIN_BRANCH)
        case Accion.BUILD_PACKAGE:
            today_folder_name = datetime.now().strftime("%Y%m%d")
            package_root = Path(BUILDS_PACKAGE_DIRECTORY) / today_folder_name
            logger.info("Creando estructura de build package en %s", package_root)
            package_root.mkdir(parents=True, exist_ok=True)
            for folder_name in BUILDS_PACKAGE_FOLDERS:
                target_folder = package_root / folder_name
                target_folder.mkdir(parents=True, exist_ok=True)
                logger.debug("Carpeta creada/asegurada: %s", target_folder)
            if CCSI_COMMON_ENABLED:
                ccsi_folder_name = f"V{NEXT_VERSION_CCSI}"
                ccsi_target_folder = Path(BUILD_CCSI_DIRECTORY) / ccsi_folder_name
                ccsi_target_folder.mkdir(parents=True, exist_ok=True)
                logger.info("Carpeta CCSI creada/asegurada: %s", ccsi_target_folder)
            else:
                ccsi_folder_name = f"V{CURRENT_VERSION_CCSI}"
                ccsi_target_folder = Path(BUILD_CCSI_DIRECTORY) / ccsi_folder_name
                if not ccsi_target_folder.exists():
                    raise FileNotFoundError(f"No se encontro la carpeta CCSI esperada: {ccsi_target_folder}")
                logger.info("Utilizando carpeta CCSI existente: %s", ccsi_target_folder)
            shortcut_path = package_root / f"{ccsi_folder_name}.lnk"
            logger.info("Creando acceso directo hacia %s en %s", ccsi_target_folder, shortcut_path)
            _create_shortcut(shortcut_path, ccsi_target_folder)
        case _:
            raise ValueError(f"Accion desconocida: {action}")


def _parse_actions(argv: list[str]) -> list[Accion]:
    if not argv:
        return list(Accion)

    actions: list[Accion] = []
    for raw_arg in argv:
        arg = raw_arg.strip().lower()
        if arg in ("all", "todo"):
            actions.extend(list(Accion))
            continue
        try:
            actions.append(Accion(arg))
        except ValueError:
            raise ValueError(f"Accion desconocida: {raw_arg}") from None
    return actions


def main() -> None:
    setup_logging()

    try:
        actions = _parse_actions(sys.argv[1:])
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    logger.info("Ejecucion iniciada con pasos: %s", [action.value for action in actions])
    try:
        start_building(actions)
    except Exception:
        logger.exception("Proceso de build fallo")
        raise
    logger.info("Ejecucion finalizada sin errores")


if __name__ == "__main__":
    main()

