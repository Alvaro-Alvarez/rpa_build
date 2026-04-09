import importlib
import logging
import subprocess
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

import config as config_module
import managers.file_manager as file_manager_module
import managers.git_manager as git_manager_module
import managers.ia_manager as ia_manager_module
import managers.jira_manager as jira_manager_module
import managers.rpa_manager as rpa_manager_module
import managers.tfs_manager as tfs_manager_module
from enums.enums import Accion

logger = logging.getLogger(__name__)

DecisionHandler = Callable[[list[dict]], str]
StepCallback = Callable[[Accion, str, str], None]


def _powershell_escape(path: Path) -> str:
    return str(path).replace("'", "''")


def _create_shortcut(shortcut_path: Path, target_path: Path) -> None:
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


class BuildRunner:
    def __init__(
        self,
        *,
        decision_handler: DecisionHandler | None = None,
        step_callback: StepCallback | None = None,
    ) -> None:
        self._decision_handler = decision_handler
        self._step_callback = step_callback

    def _reload_runtime_modules(self) -> None:
        global config_module
        global file_manager_module
        global git_manager_module
        global ia_manager_module
        global jira_manager_module
        global rpa_manager_module
        global tfs_manager_module

        config_module = importlib.reload(config_module)
        file_manager_module = importlib.reload(file_manager_module)
        git_manager_module = importlib.reload(git_manager_module)
        ia_manager_module = importlib.reload(ia_manager_module)
        jira_manager_module = importlib.reload(jira_manager_module)
        rpa_manager_module = importlib.reload(rpa_manager_module)
        tfs_manager_module = importlib.reload(tfs_manager_module)

    def _notify_step(self, action: Accion, status: str, message: str = "") -> None:
        if self._step_callback is not None:
            self._step_callback(action, status, message)

    def start_building(self, actions: Iterable[Accion]) -> None:
        self._reload_runtime_modules()
        for action in actions:
            logger.info("Ejecutando paso: %s", action.value)
            self._notify_step(action, "running", "Ejecutando")
            try:
                self._execute_action(action)
            except Exception as exc:
                self._notify_step(action, "error", str(exc))
                logger.info("Paso finalizado con error: %s", action.value)
                raise
            self._notify_step(action, "success", "Finalizado")
            logger.info("Paso finalizado: %s", action.value)

    def _request_decision(self, action: Accion, issues_extended: list[dict]) -> str:
        self._notify_step(action, "waiting", f"Esperando decision ({len(issues_extended)} incidencias)")
        if self._decision_handler is None:
            return "ok"
        decision = (self._decision_handler(issues_extended) or "ok").strip().lower()
        if decision not in {"ok", "force", "restart"}:
            raise ValueError(f"Decision invalida recibida: {decision}")
        return decision

    def _execute_action(self, action: Accion) -> None:
        match action:
            case Accion.GET_JIRA_ISSUES:
                while True:
                    issues_extended = jira_manager_module.get_jira_issues_validate_tags()
                    if issues_extended:
                        decision = self._request_decision(action, issues_extended)
                    else:
                        decision = "ok"

                    if decision == "restart":
                        logger.warning("Se solicito reinicio; reiniciando paso GET_JIRA_ISSUES.")
                        self._notify_step(action, "running", "Reiniciando paso")
                        continue
                    if decision == "force":
                        logger.warning("Se forzo el avance; continuando sin validaciones adicionales.")

                    issues = jira_manager_module.get_jira_issues()
                    jira_manager_module.export_issues(issues)

                    if not ia_manager_module.valid_json():
                        logger.error("Validacion de JSON fallo")
                        raise ValueError("El json de issues de jira no esta bien formateado.")
                    break

            case Accion.UPDATE_CHANGE_LOG:
                c2is_path = config_module.get_code_config("C2IS").get("code_path")
                git_manager_module.process_code_branch_for(c2is_path, config_module.MAIN_BRANCH)
                file_manager_module.update_change_log()

            case Accion.UPDATE_ASSEMBLY_VERSIONS:
                for _name, conf in config_module.get_enabled_codes():
                    git_manager_module.process_code_branch_for(
                        conf.get("code_path"),
                        conf.get("main_branch", config_module.MAIN_BRANCH),
                    )
                file_manager_module.update_assembly_versions()

            case Accion.UPDATE_AIP_VERSIONS:
                codes_with_aip = config_module.get_enabled_codes_with_aip()
                if not codes_with_aip:
                    logger.info("No hay codigos habilitados con paquetes AIP para actualizar; se omite el paso.")
                    self._notify_step(action, "success", "Sin paquetes AIP configurados")
                    return
                for _name, conf in codes_with_aip:
                    git_manager_module.process_code_branch_for(
                        conf.get("code_path"),
                        conf.get("main_branch", config_module.MAIN_BRANCH),
                    )
                rpa_manager_module.update_aip_versions()

            case Accion.UPLOAD_CODE_AND_PR:
                import os

                branches: list[tuple[str, dict, str]] = []
                codes_to_process = list(config_module.get_enabled_codes())
                if not codes_to_process:
                    logger.info("No hay codigos habilitados para publicar cambios.")
                    self._notify_step(action, "success", "Sin codigos habilitados")
                    return

                for code_name, conf in codes_to_process:
                    code_path = conf.get("code_path")
                    base_branch = conf.get("main_branch", config_module.MAIN_BRANCH)
                    git_manager_module.process_code_branch_for(code_path, base_branch)
                    build_branch = git_manager_module.create_and_checkout_build_branch_for(code_path, base_branch)
                    current_branch = git_manager_module.commit_and_push_all_changes_for(
                        code_path,
                        skip_files=(".gitignore",),
                    )
                    branches.append((code_name, conf, current_branch or build_branch))

                for code_name, conf, branch in branches:
                    tfs = (conf.get("tfs") or {}).copy()
                    build_definition_id = tfs.get("BUILD_DEFINITION_ID")
                    poll_interval = tfs.get("TFS_POLL_INTERVAL")
                    timeout_secs = tfs.get("TFS_TIMEOUT_SECS")

                    if tfs.get("BUILD_DEFINITION_IDS"):
                        os.environ["BUILD_DEFINITION_IDS"] = str(tfs.get("BUILD_DEFINITION_IDS"))
                    elif tfs.get("BUILD_DEFINITION_ID") is not None:
                        os.environ["BUILD_DEFINITION_ID"] = str(tfs.get("BUILD_DEFINITION_ID"))

                    manager = tfs_manager_module.TfsManager(
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
                    manager.run_pr_pipeline(
                        source_branch=branch,
                        target_branch=conf.get("main_branch", config_module.MAIN_BRANCH),
                        repo_id=str(tfs.get("REPO_ID") or ""),
                    )
                    logger.info("Pipeline de PR completado para %s", code_name)

            case Accion.BUILD_PACKAGE:
                today_folder_name = datetime.now().strftime("%Y%m%d")
                package_root = Path(config_module.BUILDS_PACKAGE_DIRECTORY) / today_folder_name
                logger.info("Creando estructura de build package en %s", package_root)
                package_root.mkdir(parents=True, exist_ok=True)
                for folder_name in config_module.BUILDS_PACKAGE_FOLDERS:
                    target_folder = package_root / folder_name
                    target_folder.mkdir(parents=True, exist_ok=True)
                    logger.debug("Carpeta creada/asegurada: %s", target_folder)

                if config_module.CCSI_COMMON_ENABLED:
                    ccsi_folder_name = f"V{config_module.NEXT_VERSION_CCSI}"
                    ccsi_target_folder = Path(config_module.BUILD_CCSI_DIRECTORY) / ccsi_folder_name
                    ccsi_target_folder.mkdir(parents=True, exist_ok=True)
                    logger.info("Carpeta CCSI creada/asegurada: %s", ccsi_target_folder)
                else:
                    ccsi_folder_name = f"V{config_module.CURRENT_VERSION_CCSI}"
                    ccsi_target_folder = Path(config_module.BUILD_CCSI_DIRECTORY) / ccsi_folder_name
                    if not ccsi_target_folder.exists():
                        raise FileNotFoundError(f"No se encontro la carpeta CCSI esperada: {ccsi_target_folder}")
                    logger.info("Utilizando carpeta CCSI existente: %s", ccsi_target_folder)

                shortcut_path = package_root / f"{ccsi_folder_name}.lnk"
                logger.info("Creando acceso directo hacia %s en %s", ccsi_target_folder, shortcut_path)
                _create_shortcut(shortcut_path, ccsi_target_folder)

            case _:
                raise ValueError(f"Accion desconocida: {action}")
