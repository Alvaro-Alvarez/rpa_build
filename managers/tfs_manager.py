import base64
import json
import logging
import os
import time
from typing import Any, Dict, Iterable, List, Optional

import requests


logger = logging.getLogger(__name__)


class TfsApiError(RuntimeError):
    """Error de la API de Azure DevOps/TFS."""


def _b64_pat(pat: str) -> str:
    token = f":{pat}".encode("utf-8")
    return base64.b64encode(token).decode("ascii")


class TfsManager:
    """Gestor para automatizar PRs, builds, revisiones y completado en Azure DevOps/TFS.

    Variables de entorno usadas por defecto (si no se pasan parámetros):
      - `ORG`: Nombre de la organización/colección
      - `PROJECT`: Nombre del proyecto
      - `REPO_ID`: ID del repositorio (GUID) o nombre
      - `BASE_URL`: URL base del servidor sin incluir organización/proyecto
                    ej.: `https://dev.azure.com` o `https://tfs.servidor/tfs`
      - `PAT`: Personal Access Token
      - `BUILD_DEFINITION_ID` (opcional): ID de definición de build por defecto
      - `TFS_POLL_INTERVAL` (opcional): Intervalo de sondeo en segundos (por defecto 10)
      - `TFS_TIMEOUT_SECS` (opcional): Timeout en segundos para esperas (por defecto 1800)

    Composición de URL:
      La raíz REST se construye como `{BASE_URL}/{ORG}/{PROJECT}` y cada ruta
      de API indicada (p. ej. `/_apis/git/...`) se concatena a esa raíz.
      Soporta tanto Azure DevOps (cloud) como TFS (on‑premise).
    """

    DEFAULT_POLL_INTERVAL = 10
    DEFAULT_TIMEOUT_SECS = 30 * 60

    def __init__(
        self,
        org: Optional[str] = None,
        project: Optional[str] = None,
        pat: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        repo_id: Optional[str] = None,
        poll_interval: Optional[int] = None,
        timeout_secs: Optional[int] = None,
        build_definition_id: Optional[int] = None,
    ) -> None:
        """Inicializa el gestor.

        Parámetros:
            org: Organización/colección (por defecto `ORG`).
            project: Proyecto (por defecto `PROJECT`).
            pat: Personal Access Token (por defecto `PAT`).
            base_url: URL base del servidor, sin org/proyecto (por defecto `BASE_URL`).
            repo_id: ID o nombre del repositorio (por defecto `REPO_ID`).
            poll_interval: Intervalo de sondeo en segundos (por defecto `TFS_POLL_INTERVAL` o 10).
            timeout_secs: Tiempo máximo de espera en segundos (por defecto `TFS_TIMEOUT_SECS` o 1800).
            build_definition_id: ID de definición de build por defecto (por defecto `BUILD_DEFINITION_ID`).
        """
        self.org = org or os.getenv("ORG") or ""
        self.project = project or os.getenv("PROJECT") or ""
        self.pat = pat or os.getenv("PAT") or ""
        self.base_url = (base_url or os.getenv("BASE_URL") or "").rstrip("/")
        self.repo_id = repo_id or os.getenv("REPO_ID") or None
        self.poll_interval = int(
            poll_interval if poll_interval is not None else os.getenv("TFS_POLL_INTERVAL", self.DEFAULT_POLL_INTERVAL)
        )
        self.timeout_secs = int(
            timeout_secs if timeout_secs is not None else os.getenv("TFS_TIMEOUT_SECS", self.DEFAULT_TIMEOUT_SECS)
        )
        build_def_env = os.getenv("BUILD_DEFINITION_ID")
        self.build_definition_id = int(build_definition_id) if build_definition_id is not None else (
            int(build_def_env) if build_def_env and build_def_env.isdigit() else None
        )

        if not (self.base_url and self.org and self.project and self.pat):
            raise ValueError(
                "Faltan configuraciones: asegure BASE_URL, ORG, PROJECT y PAT (env o parámetros)."
            )

        self._auth_header = {"Authorization": f"Basic {_b64_pat(self.pat)}"}
        self._root = f"{self.base_url}/{self.org}/{self.project}"

        # Últimos IDs conocidos para conveniencia entre llamadas
        self._last_pr_id: Optional[int] = None
        self._last_build_id: Optional[int] = None

    def _url(self, path: str) -> str:
        return f"{self._root}{path if path.startswith('/') else '/' + path}"

    def _headers(self) -> Dict[str, str]:
        return {
            **self._auth_header,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            resp = requests.request(method, url, headers=self._headers(), timeout=60, **kwargs)
        except requests.RequestException as exc:
            raise TfsApiError(f"Error de red llamando {method} {url}: {exc}") from exc

        if resp.status_code >= 400:
            detail = None
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise TfsApiError(
                f"HTTP {resp.status_code} en {method} {url}: {detail}"
            )
        return resp

    # --- Pull Requests (PR) ---
    def create_pull_request(
        self,
        repo_id: Optional[str],
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: Optional[Iterable[str]] = None,
    ) -> int:
        """Crea un Pull Request y devuelve su ID.

        Parámetros:
            repo_id: ID o nombre del repositorio. Si es None, usa `self.repo_id`.
            source_branch: Nombre de la rama origen (sin `refs/heads/`).
            target_branch: Nombre de la rama destino (sin `refs/heads/`).
            title: Título del PR.
            description: Descripción del PR.
            reviewers: Lista de IDs o emails de revisores.

        Retorna:
            ID del PR creado (int).

        Errores:
            TfsApiError: Ante errores HTTP o de validación.
        """
        repository_id = repo_id or self.repo_id
        if not repository_id:
            raise ValueError("repo_id es requerido (parámetro o env REPO_ID)")

        url = self._url(f"/_apis/git/repositories/{repository_id}/pullrequests?api-version=7.1-preview.1")
        payload: Dict[str, Any] = {
            "sourceRefName": f"refs/heads/{source_branch}",
            "targetRefName": f"refs/heads/{target_branch}",
            "title": title,
            "description": description,
        }

        if reviewers:
            norm_reviewers: List[Dict[str, Any]] = []
            for r in reviewers:
                if "@" in r:
                    norm_reviewers.append({"uniqueName": r})
                else:
                    norm_reviewers.append({"id": r})
            payload["reviewers"] = norm_reviewers

        logger.info("Creando Pull Request en repo '%s' -> %s", repository_id, url)
        resp = self._request("POST", url, data=json.dumps(payload))
        data = resp.json()
        pr_id = int(data.get("pullRequestId") or data.get("id"))
        self._last_pr_id = pr_id
        logger.info("PR creado: ID=%s", pr_id)
        return pr_id

    # --- Builds ---
    def queue_build(
        self,
        pr_id: int,
        *,
        repo_id: Optional[str] = None,
        definition_id: Optional[int] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Encola una build del merge del PR y devuelve el ID de la build.

        La build valida la referencia `refs/pull/{prId}/merge`.

        Parámetros:
            pr_id: ID del Pull Request a validar.
            repo_id: ID o nombre del repositorio (por defecto `self.repo_id`).
            definition_id: ID de la definición de build (por defecto el configurado).
            parameters: Diccionario opcional de parámetros para la definición.

        Retorna:
            ID de la build encolada (int).
        """
        repository_id = repo_id or self.repo_id
        if not repository_id:
            raise ValueError("repo_id es requerido (parámetro o env REPO_ID)")
        def_id = definition_id or self.build_definition_id
        if not def_id:
            raise ValueError("definition_id es requerido (parámetro o env BUILD_DEFINITION_ID)")

        url = self._url("/_apis/build/builds?api-version=7.1-preview.7")
        body: Dict[str, Any] = {
            "definition": {"id": def_id},
            "sourceBranch": f"refs/pull/{pr_id}/merge",
            "reason": "pullRequest",
            "repository": {
                "id": repository_id,
                "type": "TfsGit",
            },
        }
        if parameters:
            body["parameters"] = json.dumps(parameters)

        logger.info("Encolando build para PR %s (definition %s)", pr_id, def_id)
        resp = self._request("POST", url, data=json.dumps(body))
        data = resp.json()
        build_id = int(data.get("id"))
        self._last_build_id = build_id
        logger.info("Build encolada: ID=%s", build_id)
        return build_id

    def wait_for_build(
        self,
        build_id: int,
        *,
        poll_interval: Optional[int] = None,
        timeout_secs: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Consulta periódicamente el estado de la build hasta que termine.

        Parámetros:
            build_id: ID de la build a monitorear.
            poll_interval: Segundos entre sondeos (por defecto del objeto).
            timeout_secs: Máximo de segundos a esperar (por defecto del objeto).

        Retorna:
            Documento JSON final de la build.

        Errores:
            TfsApiError: Si el resultado no es `succeeded` o si expira el tiempo de espera.
        """
        interval = poll_interval or self.poll_interval
        timeout = timeout_secs or self.timeout_secs
        url = self._url(f"/_apis/build/builds/{build_id}?api-version=7.1-preview.7")

        logger.info("Esperando build %s hasta completar...", build_id)
        start = time.time()
        last_status = None
        while True:
            resp = self._request("GET", url)
            data = resp.json()
            status = data.get("status")  # notStarted | inProgress | completed
            result = data.get("result")  # succeeded | failed | partiallySucceeded | canceled

            if status != last_status:
                logger.info("Estado build %s: %s", build_id, status)
                last_status = status

            if status == "completed":
                logger.info("Build %s completada con resultado: %s", build_id, result)
                if result != "succeeded":
                    raise TfsApiError(f"Build {build_id} finalizada con estado: {result}")
                return data

            if time.time() - start > timeout:
                raise TfsApiError(f"Timeout esperando build {build_id} tras {timeout}s")

            time.sleep(interval)

    # --- Revisiones ---
    def get_reviewers(self, repo_id: Optional[str], pr_id: int) -> List[Dict[str, Any]]:
        """Devuelve la lista de revisores del PR.

        Parámetros:
            repo_id: ID o nombre del repositorio. Si es None, usa `self.repo_id`.
            pr_id: ID del Pull Request.

        Retorna:
            Lista de objetos JSON de revisores tal como los entrega la API.
        """
        repository_id = repo_id or self.repo_id
        if not repository_id:
            raise ValueError("repo_id es requerido (parámetro o env REPO_ID)")

        url = self._url(
            f"/_apis/git/repositories/{repository_id}/pullRequests/{pr_id}/reviewers?api-version=7.1-preview.1"
        )
        resp = self._request("GET", url)
        data = resp.json()
        # Algunas respuestas devuelven la lista directamente; otras la envuelven en 'value'
        reviewers = data.get("value", data)
        return reviewers  # type: ignore[return-value]

    def wait_for_reviews(
        self,
        pr_id: int,
        *,
        repo_id: Optional[str] = None,
        poll_interval: Optional[int] = None,
        timeout_secs: Optional[int] = None,
        required_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Espera hasta que todos los revisores requeridos aprueben, o alguno rechace.

        Reglas de aprobación:
          - aprobado si `vote >= 5`
          - rechazado si `vote <= -10` (se aborta inmediatamente)

        Parámetros:
            pr_id: ID del Pull Request.
            repo_id: ID del repositorio (por defecto el del objeto).
            poll_interval: Segundos entre sondeos.
            timeout_secs: Máximo de segundos a esperar.
            required_only: Si es True, solo se consideran revisores requeridos.

        Retorna:
            Lista final de revisores cuando todos aprueban.

        Errores:
            TfsApiError: Si hay rechazo o se excede el tiempo de espera.
        """
        repository_id = repo_id or self.repo_id
        if not repository_id:
            raise ValueError("repo_id es requerido (parámetro o env REPO_ID)")

        interval = poll_interval or self.poll_interval
        timeout = timeout_secs or self.timeout_secs

        logger.info("Esperando aprobaciones de revisores para PR %s...", pr_id)
        start = time.time()
        while True:
            reviewers = self.get_reviewers(repository_id, pr_id)

            # Filtrar revisores requeridos si se solicitó
            considered = [r for r in reviewers if (not required_only) or r.get("isRequired")]
            if not considered and required_only:
                logger.info("No hay revisores requeridos; consideramos todos los revisores")
                considered = reviewers

            # Evaluar votos
            votes = [int(r.get("vote", 0) or 0) for r in considered]
            if any(v <= -10 for v in votes):
                raise TfsApiError("Un revisor rechazo el PR (vote <= -10)")

            if considered and all(v >= 5 for v in votes):
                logger.info("Todos los revisores han aprobado el PR")
                return reviewers

            if time.time() - start > timeout:
                raise TfsApiError(f"Timeout esperando revisiones del PR {pr_id} tras {timeout}s")

            time.sleep(interval)

    # --- Completado ---
    def complete_pull_request(
        self,
        pr_id: int,
        *,
        repo_id: Optional[str] = None,
        delete_source_branch: bool = True,
        squash_merge: bool = True,
    ) -> Dict[str, Any]:
        """Completa un PR y opcionalmente elimina la rama de origen.

        Parámetros:
            pr_id: ID del Pull Request.
            repo_id: ID del repositorio (por defecto el del objeto).
            delete_source_branch: Si eliminar la rama de origen.
            squash_merge: Si realizar squash al hacer el merge.

        Retorna:
            Documento JSON resultante del PR.
        """
        repository_id = repo_id or self.repo_id
        if not repository_id:
            raise ValueError("repo_id es requerido (parámetro o env REPO_ID)")

        url = self._url(f"/_apis/git/repositories/{repository_id}/pullrequests/{pr_id}?api-version=7.1-preview.1")
        payload = {
            "status": "completed",
            "completionOptions": {
                "deleteSourceBranch": bool(delete_source_branch),
                "squashMerge": bool(squash_merge),
            },
        }
        logger.info("Completando PR %s (deleteSource=%s, squash=%s)", pr_id, delete_source_branch, squash_merge)
        resp = self._request("PATCH", url, data=json.dumps(payload))
        return resp.json()

    # --- Flujo completo PR/Build ---
    def run_pr_pipeline(
        self,
        *,
        source_branch: str,
        target_branch: str,
        repo_id: Optional[str] = None,
        definition_id: Optional[int] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ejecuta el flujo completo: crear PR → build → aprobaciones → completar.

        Parámetros:
            source_branch: Rama origen (sin `refs/heads/`).
            target_branch: Rama destino (sin `refs/heads/`).
            repo_id: ID/nombre de repositorio (por defecto el configurado en el objeto).
            definition_id: ID de definición de build (por defecto la configurada).
            title: Título del PR. Si None, se genera uno por defecto.
            description: Descripción del PR. Si None, se genera una por defecto.

        Retorna:
            Documento JSON del PR tras completarse.
        """
        # Preparar valores por defecto
        if title is None:
            title = f"PR automático: {source_branch} → {target_branch}"
        if description is None:
            description = (
                f"PR generado automáticamente desde '{source_branch}' hacia '{target_branch}'.\n"
                f"Validación con build del merge y completado automático."
            )

        pr_id = self.create_pull_request(
            repo_id=repo_id,
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            reviewers=None,
        )

        build_id = self.queue_build(pr_id, repo_id=repo_id, definition_id=definition_id)
        self.wait_for_build(build_id)
        self.wait_for_reviews(pr_id, repo_id=repo_id)
        return self.complete_pull_request(pr_id, repo_id=repo_id)
