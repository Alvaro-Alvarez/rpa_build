import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

from config import (
    BUILD_VERSION,
    JIRA_JQL,
    JIRA_TOKEN,
    JIRA_URL,
    JIRA_USER,
    JSON_NAME,
    XLXS_NAME,
    JIRA_VALIDATE_TAGS,
    TEAMS_CONFIRMATION_PARTICIPANTS,
    get_changelog_path,
)

JIRA_SEARCH_ENDPOINT = "/rest/api/3/search/jql"
JIRA_FIELDS = "key,summary"
JIRA_FIELDS_EXT = "key,summary,assignee"
JIRA_MAX_RESULTS = 100
REQUEST_TIMEOUT = 30
EXCEL_COLUMNS = ("Key", "Summary")
EXPORT_DATE_FORMAT = "%d/%m/%Y"
JSON_ENCODING = "utf-8"
EXPORT_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def get_jira_issues(max_results: int = JIRA_MAX_RESULTS) -> Dict[str, str]:
    logger.info("Preparando consulta a Jira con un maximo de %s resultados", max_results)
    query = {
        "jql": JIRA_JQL.replace("{BUILD_VERSION}", BUILD_VERSION),
        "maxResults": max_results,
        "fields": JIRA_FIELDS,
    }
    logger.info("Ejecutando consulta JQL: %s", query["jql"])

    try:
        response = _request_jira("GET", f"{JIRA_URL}{JIRA_SEARCH_ENDPOINT}", params=query)
    except Exception:
        logger.exception("No se pudo obtener la informacion de Jira")
        raise

    logger.info("Respuesta de Jira recibida con codigo %s", response.status_code)
    data = response.json()

    issues: Dict[str, str] = {}
    for issue in data.get("issues", []):
        key = issue.get("key")
        summary = issue.get("fields", {}).get("summary", "")
        if key:
            issues[key] = summary.strip()

    if not issues:
        logger.error("Jira no devolvio issues para la consulta configurada")
        raise ValueError("Jira no devolvio issues para la consulta configurada.")

    logger.info("Se recuperaron %s issues de Jira", len(issues))
    logger.info("Issues obtenidos: %s", issues)
    return issues


def get_jira_issues_extended(max_results: int = JIRA_MAX_RESULTS) -> List[dict]:
    """
    Obtiene issues de Jira incluyendo datos del responsable (nombre y email si est谩 disponible).

    Mantiene intacto el comportamiento de get_jira_issues(); esta funci贸n es adicional
    para enriquecer la informaci贸n sin afectar la exportaci贸n existente.

    Retorna una lista de diccionarios con las claves:
      - 'key': str
      - 'summary': str
      - 'assignee_name': str (puede ser "" si no hay asignado)
      - 'assignee_email': str (puede ser "" si no est谩 disponible por pol铆ticas de Jira)
    """
    logger.info(
        "Preparando consulta extendida a Jira con un maximo de %s resultados",
        max_results,
    )
    query = {
        "jql": JIRA_JQL.replace("{BUILD_VERSION}", BUILD_VERSION),
        "maxResults": max_results,
        "fields": JIRA_FIELDS_EXT,
    }
    logger.info("Ejecutando consulta JQL (extendida): %s", query["jql"])

    try:
        response = _request_jira("GET", f"{JIRA_URL}{JIRA_SEARCH_ENDPOINT}", params=query)
    except Exception:
        logger.exception("No se pudo obtener la informacion extendida de Jira")
        raise

    logger.info("Respuesta de Jira (extendida) con codigo %s", response.status_code)
    data = response.json()

    extended: List[dict] = []
    for issue in data.get("issues", []):
        key = issue.get("key") or ""
        fields = issue.get("fields", {}) or {}
        summary = (fields.get("summary") or "").strip()
        assignee = fields.get("assignee") or {}

        # En Jira Cloud, el emailAddress puede no estar disponible por pol铆ticas de privacidad (GDPR)
        assignee_name = (assignee.get("displayName") or "").strip()
        assignee_email = (assignee.get("emailAddress") or "").strip()

        if key:
            link = f"{JIRA_URL.rstrip('/')}/browse/{key}"
            extended.append(
                {
                    "key": key,
                    "summary": summary,
                    "assignee_name": assignee_name,
                    "assignee_email": assignee_email,
                    "link": link,
                }
            )

    if not extended:
        logger.error("Jira no devolvio issues (extendidos) para la consulta configurada")
        raise ValueError("Jira no devolvio issues (extendidos) para la consulta configurada.")

    logger.info("Se recuperaron %s issues de Jira (extendidos)", len(extended))
    logger.info("Issues extendidos (sin emails si Jira los oculta): %s", extended)
    return extended


def export_issues(issues: Dict[str, str]):
    if not issues:
        logger.error("No hay issues para exportar; se aborta la exportacion")
        raise ValueError("No hay issues para exportar.")

    logger.info("Exportando issues de Jira a Excel y JSON")
    _export_to_excel(issues)
    _export_to_json(issues)
    logger.info("Exportacion de issues completada")


def _export_to_excel(issues: Dict[str, str]):
    output_path = EXPORT_DIR / XLXS_NAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Generando archivo de Excel en %s", output_path)
    df = pd.DataFrame([(key, value) for key, value in issues.items()], columns=EXCEL_COLUMNS)
    df.to_excel(output_path, index=False)
    logger.info("Archivo de Excel '%s' actualizado correctamente", output_path)


def _export_to_json(issues: Dict[str, str]):
    sanitized = {key: _sanitize_summary(value) for key, value in issues.items()}
    payload = {
        "versionNumber": BUILD_VERSION,
        "versionDate": datetime.now().strftime(EXPORT_DATE_FORMAT),
        "changeLogDetails": [f"{key} - {value}" for key, value in sanitized.items()],
    }

    output_path = EXPORT_DIR / JSON_NAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding=JSON_ENCODING) as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
    logger.info("Archivo JSON '%s' actualizado correctamente", output_path.resolve())


def _sanitize_summary(summary: str) -> str:
    return summary.replace('"', "'").replace("\n", " ").strip()


def _request_jira(method: str, url: str, **kwargs) -> requests.Response:
    logger.info("Realizando peticion %s a Jira: %s", method, url)
    headers = {"Accept": "application/json"}
    user_headers = kwargs.pop("headers", {})
    headers.update(user_headers)

    response = requests.request(
        method,
        url,
        headers=headers,
        auth=HTTPBasicAuth(JIRA_USER, JIRA_TOKEN),
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )

    if response.status_code >= 400:
        logger.error("Error consultando Jira (%s): %s", response.status_code, response.text)
        raise RuntimeError(
            f"Error consultando Jira ({response.status_code}): {response.text}"
        )

    logger.info("Peticion a Jira completada correctamente")
    return response


def get_jira_issues_validate_tags(max_results: int = JIRA_MAX_RESULTS) -> List[dict]:
    """
    Nueva consulta a Jira usando JIRA_VALIDATE_TAGS con reemplazos din谩micos:
      - {PARTICIPANTS}: jira_key de todos los participantes (incluidos deshabilitados)
      - {FIX_NUMBER_ONE}: primeros 2 n煤meros de BUILD_VERSION (x.xx)
      - {FIX_NUMBER_TWO}: primeros 3 n煤meros (x.xx.x)
      - {FIX_NUMBER_THREE}: versi贸n completa (4 n煤meros)
      - {LAST_BUILD_DATE}: versionDate del 铆ndice 0 del JSON CHANGE_LOG_PATH

    Devuelve lista de dicts: key, summary, assignee_name, assignee_email, link.
    """
    logger.info(
        "Preparando consulta de validaci贸n de tags en Jira (max %s)", max_results
    )

    # Participantes (todas las jira_key, incluso deshabilitados)
    participants_keys: list[str] = []
    for p in TEAMS_CONFIRMATION_PARTICIPANTS or []:
        key = (p.get("jira_key") or "").strip()
        if key:
            participants_keys.append(key)
    participants_replacement = ", ".join(participants_keys)

    # Versiones FIX_NUMBER_*
    vparts = (BUILD_VERSION or "").split(".")
    while len(vparts) < 4:
        vparts.append("0")
    fix_one = ".".join(vparts[:2])
    fix_two = ".".join(vparts[:3])
    fix_three = ".".join(vparts[:4])

    # Fecha del 鷏timo build desde el change log (posici髇 0))
    try:
        cl_path = Path(get_changelog_path())
        with cl_path.open("r", encoding="utf-8") as f:
            content = json.load(f)
        last_build_date_raw = (content.get("changelogData") or [{}])[0].get("versionDate") or ""
        # Formatear fecha a YYYY-MM-DD
        last_build_date = _to_ymd(last_build_date_raw)
    except Exception:
        logger.exception(
            "No se pudo leer versionDate[0] desde el change log: %s", get_changelog_path()
        )
        return []

    jql = (
        JIRA_VALIDATE_TAGS
        .replace("{PARTICIPANTS}", participants_replacement)
        .replace("{FIX_NUMBER_ONE}", fix_one)
        .replace("{FIX_NUMBER_TWO}", fix_two)
        .replace("{FIX_NUMBER_THREE}", fix_three)
        .replace("{LAST_BUILD_DATE}", str(last_build_date or ""))
    )

    query = {
        "jql": jql,
        "maxResults": max_results,
        "fields": JIRA_FIELDS_EXT,
    }
    logger.info("Ejecutando consulta JQL (validaci贸n): %s", query["jql"])

    try:
        response = _request_jira("GET", f"{JIRA_URL}{JIRA_SEARCH_ENDPOINT}", params=query)
    except Exception:
        logger.exception("No se pudo obtener la informacion de Jira (validaci贸n)")
        raise

    logger.info("Respuesta de Jira (validaci贸n) con codigo %s", response.status_code)
    data = response.json()

    results: List[dict] = []
    for issue in data.get("issues", []):
        key = issue.get("key") or ""
        fields = issue.get("fields", {}) or {}
        summary = (fields.get("summary") or "").strip()
        assignee = fields.get("assignee") or {}

        assignee_name = (assignee.get("displayName") or "").strip()
        assignee_email = (assignee.get("emailAddress") or "").strip()
        assignee_jira_key = (assignee.get("accountId") or "").strip()

        if key:
            link = f"{JIRA_URL.rstrip('/')}/browse/{key}"
            results.append(
                {
                    "key": key,
                    "summary": summary,
                    "assignee_name": assignee_name,
                    "assignee_email": assignee_email,
                    "assignee_jira_key": assignee_jira_key,
                    "link": link,
                }
            )

    logger.info("Se recuperaron %s issues de Jira (validaci贸n)", len(results))
    return results


def _to_ymd(date_str: str) -> str:
    """Intenta convertir una fecha en texto a formato YYYY-MM-DD.

    Soporta formatos comunes: dd/mm/YYYY, dd-mm-YYYY, YYYY-MM-DD, YYYY/MM/DD.
    Si no reconoce el formato, devuelve el texto original.
    """
    s = (date_str or "").strip()
    if not s:
        return s
    # ya en ISO simple
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    # fallback: devolver original
    return s

