import json
from datetime import datetime
from pathlib import Path
from typing import Dict

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
JIRA_MAX_RESULTS = 100
REQUEST_TIMEOUT = 30
EXCEL_COLUMNS = ("Key", "Summary")
EXPORT_DATE_FORMAT = "%d/%m/%Y"
JSON_ENCODING = "utf-8"


def get_jira_issues(max_results: int = JIRA_MAX_RESULTS) -> Dict[str, str]:
    query = {
        "jql": JIRA_JQL.replace("{BUILD_VERSION}", BUILD_VERSION),
        "maxResults": max_results,
        "fields": JIRA_FIELDS,
    }
    response = _request_jira("GET", f"{JIRA_URL}{JIRA_SEARCH_ENDPOINT}", params=query)
    data = response.json()

    issues = {}
    for issue in data.get("issues", []):
        key = issue.get("key")
        summary = issue.get("fields", {}).get("summary", "")
        if key:
            issues[key] = summary.strip()

    if not issues:
        raise ValueError("Jira no devolvio issues para la consulta configurada.")

    return issues


def export_issues(issues: Dict[str, str]):
    if not issues:
        raise ValueError("No hay issues para exportar.")

    _export_to_excel(issues)
    _export_to_json(issues)


def _export_to_excel(issues: Dict[str, str]):
    df = pd.DataFrame([(key, value) for key, value in issues.items()], columns=EXCEL_COLUMNS)
    df.to_excel(Path(XLXS_NAME), index=False)


def _export_to_json(issues: Dict[str, str]):
    sanitized = {key: _sanitize_summary(value) for key, value in issues.items()}
    payload = {
        "versionNumber": BUILD_VERSION,
        "versionDate": datetime.now().strftime(EXPORT_DATE_FORMAT),
        "changeLogDetails": [f"{key} - {value}" for key, value in sanitized.items()],
    }

    with Path(JSON_NAME).open("w", encoding=JSON_ENCODING) as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def _sanitize_summary(summary: str) -> str:
    return summary.replace('"', "'").replace("\n", " ").strip()


def _request_jira(method: str, url: str, **kwargs) -> requests.Response:
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
        raise RuntimeError(
            f"Error consultando Jira ({response.status_code}): {response.text}"
        )

    return response
