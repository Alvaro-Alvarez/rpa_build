import logging
import sys
from pathlib import Path

from build_runner import BuildRunner
from enums.enums import Accion
from logging_config import setup_logging

logger = logging.getLogger(__name__)
JIRA_VALIDATION_REPORT_PATH = Path(__file__).resolve().parent / "jira_validation_issues.tmp.txt"


def _write_validation_issues_report(issues_extended: list[dict]) -> Path:
    lines: list[str] = [
        "Robobuild - Detalle de inconsistencias detectadas en Jira",
        "",
        "Motivo general: falta el tag DevTeam o el campo FixVersion esta incompleto.",
        "",
    ]

    for index, item in enumerate(issues_extended, start=1):
        key = (item.get("key") or "").strip()
        summary = (item.get("summary") or "").strip()
        assignee = (item.get("assignee_name") or "").strip()
        link = (item.get("link") or "").strip()
        lines.extend(
            [
                f"{index}. Key: {key or '-'}",
                f"   Summary: {summary or '-'}",
                f"   Assignee: {assignee or '-'}",
                f"   Link: {link or '-'}",
                "",
            ]
        )

    JIRA_VALIDATION_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return JIRA_VALIDATION_REPORT_PATH


def _report_validation_issues_to_console(issues_extended: list[dict]) -> None:
    report_path = _write_validation_issues_report(issues_extended)
    summary = (
        "Se detectaron inconsistencias en Jira vinculadas a tags o FixVersion. "
        f"El detalle quedo registrado en: {report_path}"
    )
    commands = "Comandos disponibles para continuar: ok, force, restart."
    logger.warning(summary)
    logger.info(commands)
    print(summary)
    print(commands)


def _get_console_decision(issues_extended: list[dict]) -> str:
    _report_validation_issues_to_console(issues_extended)
    prompt = "Ingresa un comando [ok/force/restart]: "
    valid = {"ok", "force", "restart"}

    while True:
        try:
            raw_value = input(prompt)
        except EOFError as exc:
            raise RuntimeError(
                "No hay entrada interactiva disponible para confirmar el paso GET_JIRA_ISSUES."
            ) from exc

        decision = raw_value.strip().lower()
        if not decision:
            decision = "ok"
        if decision in valid:
            logger.info("Decision recibida por consola: %s", decision)
            return decision

        logger.warning("Comando invalido ingresado por consola: %s", raw_value)
        print("Comando invalido. Usa: ok, force o restart.")


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
    runner = BuildRunner(decision_handler=_get_console_decision)
    try:
        runner.start_building(actions)
    except Exception:
        logger.exception("Proceso de build fallo")
        raise
    logger.info("Ejecucion finalizada sin errores")


if __name__ == "__main__":
    main()
