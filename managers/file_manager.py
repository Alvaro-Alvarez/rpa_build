import json
import logging
from pathlib import Path

from config import (
    BUILD_VERSION,
    JSON_NAME,
    PREVIOUS_BUILD_VERSION,
    get_enabled_codes,
    get_changelog_path,
)

CHANGE_LOG_READ_ENCODING = "utf-8-sig"
CHANGE_LOG_WRITE_ENCODING = "utf-8"
ISSUES_ENCODING = "utf-8"
ASSEMBLY_ENCODING = "utf-8"

def _collect_assembly_paths() -> tuple[str, ...]:
    paths: list[str] = []
    for _name, conf in get_enabled_codes():
        paths.extend(conf.get("assembly_paths") or [])
    return tuple(paths)

ASSEMBLY_PATHS = _collect_assembly_paths()
ROOT_DIR = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT_DIR / JSON_NAME

logger = logging.getLogger(__name__)


def update_change_log():
    change_log_path = get_changelog_path()
    logger.info("Actualizando change log desde '%s' con issues de '%s'", change_log_path, JSON_NAME)
    issues_json = _read_json(JSON_PATH, encoding=ISSUES_ENCODING)
    change_log_json = _read_json(Path(change_log_path), encoding=CHANGE_LOG_READ_ENCODING)

    changelog_data = change_log_json.get("changelogData")
    if not isinstance(changelog_data, list):
        logger.error("El change log no contiene una lista 'changelogData'")
        raise ValueError("El change log debe contener una lista 'changelogData'.")

    logger.info("Insertando nueva entrada en el change log")
    changelog_data.insert(0, issues_json)
    _write_json(Path(change_log_path), change_log_json, encoding=CHANGE_LOG_WRITE_ENCODING)
    logger.info("Change log actualizado correctamente")


def update_assembly_versions():
    logger.info("Actualizando versiones en archivos AssemblyInfo")
    for assembly_path in ASSEMBLY_PATHS:
        logger.info("Actualizando archivo AssemblyInfo: %s", assembly_path)
        update_assembly(Path(assembly_path))
    logger.info("Actualizacion de AssemblyInfo completada")


def update_assembly(assembly_path: Path):
    if not assembly_path.exists():
        logger.error("No se encontro el archivo AssemblyInfo: %s", assembly_path)
        raise FileNotFoundError(f"No se encontro el archivo AssemblyInfo: {assembly_path}")

    logger.info("Leyendo contenido de %s", assembly_path)
    content = assembly_path.read_text(encoding=ASSEMBLY_ENCODING)
    if PREVIOUS_BUILD_VERSION not in content:
        logger.error(
            "La version anterior %s no se encontro en %s",
            PREVIOUS_BUILD_VERSION,
            assembly_path,
        )
        raise ValueError(
            f"La version anterior {PREVIOUS_BUILD_VERSION} no aparece en {assembly_path}."
        )

    updated_content = content.replace(PREVIOUS_BUILD_VERSION, BUILD_VERSION)
    assembly_path.write_text(updated_content, encoding=ASSEMBLY_ENCODING)
    logger.info(
        "Version actualizada de %s: %s -> %s",
        assembly_path,
        PREVIOUS_BUILD_VERSION,
        BUILD_VERSION,
    )


def _read_json(path: Path, *, encoding: str):
    logger.info("Leyendo archivo JSON: %s", path)
    with path.open("r", encoding=encoding) as file:
        return json.load(file)


def _write_json(path: Path, payload, *, encoding: str):
    logger.info("Escribiendo archivo JSON: %s", path)
    with path.open("w", encoding=encoding) as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
    logger.info("Archivo JSON '%s' escrito correctamente", path)
