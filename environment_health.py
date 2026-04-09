import os
import shutil
import tempfile
from pathlib import Path

import requests

import config


def _status(ok: bool) -> str:
    return "ok" if ok else "error"


def _find_advanced_installer() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 22.0\bin\x86\AdvancedInstaller.com"),
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 22.0\bin\x86\advinst.exe"),
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 21.9\bin\x86\AdvancedInstaller.com"),
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 21.9\bin\x86\advinst.exe"),
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 21.8\bin\x86\AdvancedInstaller.com"),
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 21.8\bin\x86\advinst.exe"),
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 21.7\bin\x86\AdvancedInstaller.com"),
        Path(r"C:\Program Files (x86)\Caphyon\Advanced Installer 21.7\bin\x86\advinst.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _check_url(name: str, url: str) -> dict:
    try:
        response = requests.get(url, timeout=5)
        ok = response.status_code < 500
        detail = f"HTTP {response.status_code}"
    except Exception as exc:
        ok = False
        detail = str(exc)
    return {
        "category": "Red",
        "name": name,
        "status": _status(ok),
        "detail": detail,
    }


def _check_path(name: str, path_value: str | None, *, expect_file: bool | None = None) -> dict:
    raw = (path_value or "").strip()
    if not raw:
        return {
            "category": "Rutas",
            "name": name,
            "status": "warning",
            "detail": "No configurado",
        }
    path = Path(raw)
    if expect_file is True:
        ok = path.is_file()
    elif expect_file is False:
        ok = path.is_dir()
    else:
        ok = path.exists()
    return {
        "category": "Rutas",
        "name": name,
        "status": _status(ok),
        "detail": str(path),
    }


def _check_state_dir_writable() -> dict:
    state_dir = config.APP_STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=state_dir, prefix="health_", suffix=".tmp", delete=True):
            pass
        ok = True
        detail = str(state_dir)
    except Exception as exc:
        ok = False
        detail = f"{state_dir} | {exc}"
    return {
        "category": "Aplicacion",
        "name": "Directorio de estado escribible",
        "status": _status(ok),
        "detail": detail,
    }


def run_environment_health_checks() -> list[dict]:
    checks: list[dict] = []

    git_path = shutil.which("git")
    checks.append(
        {
            "category": "Software",
            "name": "Git instalado",
            "status": _status(bool(git_path)),
            "detail": git_path or "No encontrado en PATH",
        }
    )

    adv_path = _find_advanced_installer()
    checks.append(
        {
            "category": "Software",
            "name": "Advanced Installer instalado",
            "status": _status(adv_path is not None),
            "detail": str(adv_path) if adv_path else "No encontrado en rutas conocidas",
        }
    )

    checks.append(
        {
            "category": "Aplicacion",
            "name": "Assets de automatizacion",
            "status": _status((Path(__file__).resolve().parent / "assets" / "images").is_dir()),
            "detail": str(Path(__file__).resolve().parent / "assets" / "images"),
        }
    )
    checks.append(_check_state_dir_writable())
    checks.append(_check_url("Jira accesible", config.JIRA_URL))

    tfs_urls: set[str] = set()
    for code_name, code_conf in config.CODES.items():
        checks.append(
            _check_path(
                f"{code_name}: repositorio local",
                code_conf.get("code_path"),
                expect_file=False,
            )
        )
        if code_conf.get("change_log_path"):
            checks.append(
                _check_path(
                    f"{code_name}: change log",
                    code_conf.get("change_log_path"),
                    expect_file=True,
                )
            )

        for index, path_value in enumerate(code_conf.get("assembly_paths") or [], start=1):
            checks.append(
                _check_path(
                    f"{code_name}: assembly path #{index}",
                    path_value,
                    expect_file=True,
                )
            )

        for index, path_value in enumerate(code_conf.get("aip_paths") or [], start=1):
            checks.append(
                _check_path(
                    f"{code_name}: AIP path #{index}",
                    path_value,
                    expect_file=True,
                )
            )

        tfs = code_conf.get("tfs") or {}
        base_url = str(tfs.get("BASE_URL") or "").strip()
        if base_url:
            tfs_urls.add(base_url)

    for tfs_url in sorted(tfs_urls):
        checks.append(_check_url(f"TFS accesible ({tfs_url})", tfs_url))

    checks.append(
        _check_path(
            "Share package",
            config.BUILDS_PACKAGE_DIRECTORY,
            expect_file=False,
        )
    )
    checks.append(
        _check_path(
            "Share CCSI",
            config.BUILD_CCSI_DIRECTORY,
            expect_file=False,
        )
    )

    return checks
