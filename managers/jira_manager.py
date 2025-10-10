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
    Obtiene issues de Jira incluyendo datos del responsable (nombre y email si está disponible).

    Mantiene intacto el comportamiento de get_jira_issues(); esta función es adicional
    para enriquecer la información sin afectar la exportación existente.

    Retorna una lista de diccionarios con las claves:
      - 'key': str
      - 'summary': str
      - 'assignee_name': str (puede ser "" si no hay asignado)
      - 'assignee_email': str (puede ser "" si no está disponible por políticas de Jira)
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

        # En Jira Cloud, el emailAddress puede no estar disponible por políticas de privacidad (GDPR)
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
