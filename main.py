import logging
import sys
from typing import Iterable

from enums.enums import Accion
from managers import file_manager, git_manager, ia_manager, jira_manager, rpa_manager
from managers.tfs_manager import TfsManager
from config import MAIN_BRANCH
from logging_config import setup_logging
from managers.teams_manager import open_teams_and_send_message

logger = logging.getLogger(__name__)


def start_building(actions: Iterable[Accion]) -> None:
    for action in actions:
        logger.info("Ejecutando paso: %s", action.value)
        _execute_action(action)
        logger.info("Paso finalizado: %s", action.value)

def _execute_action(action: Accion) -> None:
    match action:
        case Accion.GET_JIRA_ISSUES:
            issues_extended = jira_manager.get_jira_issues_extended()
            open_teams_and_send_message(issues_extended)
            # TODO: Manejar validacion y renintento en Teams, si valida, sigue, sino reinicia
            issues = jira_manager.get_jira_issues()
            jira_manager.export_issues(issues)

            if not ia_manager.valid_json():
                logger.error("Validacion de JSON fallo")
                raise ValueError("El json de issues de jira no esta bien formateado.")
        # case Accion.UPDATE_CHANGE_LOG:
        #     git_manager.process_code_branch()
        #     file_manager.update_change_log()
        # case Accion.UPDATE_ASSEMBLY_VERSIONS:
        #     file_manager.update_assembly_versions()
        # case Accion.UPDATE_AIP_VERSIONS:
        #     rpa_manager.update_aip_versions()
        # case Accion.UPLOAD_CODE_AND_PR:
        #     build_branch = git_manager.create_and_checkout_build_branch()
        #     current_branch = git_manager.commit_and_push_all_changes()
        #     # TODO: validar funcionamiento y reinicio total si es necesario
        #     TfsManager().run_pr_pipeline(source_branch=current_branch or build_branch, target_branch=MAIN_BRANCH)
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
