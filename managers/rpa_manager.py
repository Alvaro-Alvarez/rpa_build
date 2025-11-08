import logging
import subprocess
import time
from pathlib import Path

import pyautogui
import pygetwindow as gw
from enum import Enum

from config import (
    AIP_APIS,
    AIP_BACKEND,
    AIP_FRONTEND,
    AIP_TASK,
    AIP_TASK2,
    BUILD_VERSION,
    PREVIOUS_BUILD_VERSION,
    RPA_UI_TARGETS,
)

DUMMY_VERSION = "1.1.1.1"
IMAGE_CONFIDENCE = 0.8
IMAGE_WAIT_TIMEOUT = 45
IMAGE_WAIT_INTERVAL = 1
IMAGES_DIR = Path(__file__).resolve().parent.parent / "assets" / "images"
AIP_TARGETS = (AIP_BACKEND, AIP_FRONTEND, AIP_APIS, AIP_TASK, AIP_TASK2)
window_title = 'Advanced Installer'


logger = logging.getLogger(__name__)


class TargetMode(Enum):
    POINT = "point"
    IMG = "img"

# Build map for quick lookup from config
try:
    _UI_TARGETS_MAP = {item.get("key"): item for item in RPA_UI_TARGETS}
except Exception:
    _UI_TARGETS_MAP = {}


def _get_target_config(name: str) -> dict:
    conf = _UI_TARGETS_MAP.get(name)
    if not conf:
        raise KeyError(f"UI target '{name}' not found in config.RPA_UI_TARGETS")
    return conf


def _normalize_point(point_px) -> tuple[int, int]:
    if point_px is None:
        raise ValueError("point_px is None")
    # Accept (x,y) tuple/list or {x:.., y:..}
    if isinstance(point_px, (list, tuple)) and len(point_px) == 2:
        return int(point_px[0]), int(point_px[1])
    if isinstance(point_px, dict) and "x" in point_px and "y" in point_px:
        return int(point_px["x"]), int(point_px["y"])
    raise ValueError(f"Unsupported point_px format: {point_px!r}")


def find_click_point(name: str, *, timeout: int = IMAGE_WAIT_TIMEOUT, interval: int = IMAGE_WAIT_INTERVAL):
    conf = _get_target_config(name)
    mode = str(conf.get("mode", "img")).lower()
    if mode == TargetMode.POINT.value:
        x, y = _normalize_point(conf.get("point_px"))
        return x, y
    # fallback to image mode
    image_name = conf.get("img_name") or conf.get("image")
    if not image_name:
        raise ValueError(f"UI target '{name}' missing 'img_name' for mode=img")
    match = wait_for_image(image_name, timeout=timeout, interval=interval)
    center = pyautogui.center(match)
    return center.x, center.y


def ensure_target_ready(name: str, *, timeout: int = IMAGE_WAIT_TIMEOUT, interval: int = IMAGE_WAIT_INTERVAL):
    conf = _get_target_config(name)
    mode = str(conf.get("mode", "img")).lower()
    if mode == TargetMode.IMG.value:
        # Ensure the image is present; raise TimeoutError on failure
        wait_for_image(conf.get("img_name"), timeout=timeout, interval=interval)
    return True


def click_ui_target(name: str):
    x, y = find_click_point(name)
    pyautogui.click(x, y)
    time.sleep(1)

def update_aip_versions():
    logger.info("Comenzando actualizacion de versiones AIP")
    change_three_version = change_three_version_number()
    logger.info("Cambio en el tercer numero de version?: %s", change_three_version)
    for aip_path in AIP_TARGETS:
        logger.info("Actualizando paquete AIP: %s", aip_path)
        update_aip_version(aip_path, change_three_version)
    logger.info("Actualizacion de versiones AIP finalizada")


def update_aip_version(aip_path, change_three_version):
    logger.info("Abriendo instalador AIP: %s", aip_path)
    subprocess.Popen([aip_path], shell=True)
    time.sleep(5)

    try:
        windows = gw.getWindowsWithTitle(window_title)
    except Exception as exc:
        logger.warning("No se pudo buscar la ventana '%s': %s", window_title, exc)
    else:
        if windows:
            window = windows[0]
            try:
                should_maximize = False
                if window.isMinimized:
                    window.restore()
                    should_maximize = True
                    time.sleep(0.5)
                if not window.isActive:
                    window.activate()
                    should_maximize = True
                if should_maximize and not window.isMaximized:
                    window.maximize()
            except Exception as exc:
                logger.warning("No se pudo manipular la ventana '%s': %s", window_title, exc)
        else:
            logger.warning("No se encontro una ventana con titulo que contenga '%s'", window_title)

    try:
        logger.info("Esperando menu principal del instalador para %s", aip_path)
        wait_for_image("ai_menu.png", taskbar_image_name="adv_installer_work_task.png", taskbar_click_every=3)
    except TimeoutError as exc:
        logger.warning(
            "No se detecto la pantalla principal al abrir %s; intentando restaurar desde la barra de tareas",
            aip_path,
        )
        # Intentar encontrar el icono del instalador en la barra de tareas y hacer clic
        try:
            taskbar_icon = wait_for_image("adv_installer_work_task.png", timeout=15, interval=1)
            pyautogui.click(pyautogui.center(taskbar_icon))
            time.sleep(2)
            # Reintentar localizar el menu principal tras restaurar la ventana
            wait_for_image(
                "ai_menu.png",
                timeout=30,
                interval=1,
                taskbar_image_name="adv_installer_work_task.png",
                taskbar_click_every=3,
            )
        except TimeoutError as exc2:
            logger.error(
                "No se detecto la pantalla principal para %s incluso despues de intentar abrir desde la barra de tareas",
                aip_path,
            )
            raise RuntimeError(
                f"No se detecto la pantalla principal al abrir {aip_path} incluso despues de intentar desde la barra de tareas."
            ) from exc2

    pyautogui.hotkey("alt", "space")
    time.sleep(1)
    pyautogui.press("x")

    try:
        ensure_target_ready("version_field")
    except TimeoutError as exc:
        logger.error("No se encontro el campo de version para %s", aip_path)
        raise RuntimeError(f"No se encontro el campo de version para {aip_path}.") from exc

    logger.info("Campo de version localizado para %s", aip_path)
    if change_three_version:
        logger.info("Aplicando version final %s", BUILD_VERSION)
        apply_version(BUILD_VERSION)
        regenerate_identification()
        click_ui_target("product_details_btn")
    else:
        logger.info(
            "Aplicando version temporal %s antes de regenerar identificacion",
            DUMMY_VERSION,
        )
        apply_version(DUMMY_VERSION)
        regenerate_identification()
        click_ui_target("product_details_btn")

        try:
            ensure_target_ready("version_field")
        except TimeoutError as exc:
            logger.error("No se pudo volver a localizar el campo de version para %s", aip_path)
            raise RuntimeError(
                f"No se pudo volver a localizar el campo de version para {aip_path}."
            ) from exc

        logger.info("Aplicando version final %s despues de regenerar identificacion", BUILD_VERSION)
        apply_version(BUILD_VERSION)
        regenerate_identification()
        click_ui_target("product_details_btn")

    logger.info("Guardando y cerrando instalador para %s", aip_path)
    save_and_close()


def change_three_version_number():
    v1_parts = PREVIOUS_BUILD_VERSION.split(".")
    v2_parts = BUILD_VERSION.split(".")
    v1_three = int(v1_parts[2])
    v2_three = int(v2_parts[2])
    logger.info(
        "Comparando tercer numero de version: anterior=%s (%s) vs actual=%s (%s)",
        PREVIOUS_BUILD_VERSION,
        v1_three,
        BUILD_VERSION,
        v2_three,
    )
    return v1_three != v2_three


def wait_for_image(
    image_name,
    *,
    timeout: int = IMAGE_WAIT_TIMEOUT,
    interval: int = IMAGE_WAIT_INTERVAL,
    taskbar_image_name=None,
    taskbar_click_every: int = 5,
):
    image_path = IMAGES_DIR / image_name
    deadline = time.perf_counter() + timeout
    last_error = None
    attempt = 1

    logger.info(
        "Buscando imagen '%s' (intentos cada %s s, tiempo maximo %s s)",
        image_path,
        interval,
        timeout,
    )

    while time.perf_counter() < deadline:
        try:
            match = pyautogui.locateOnScreen(str(image_path), confidence=IMAGE_CONFIDENCE)
        except Exception as exc:  # Captura errores de captura de pantalla (p.ej., OSError: screen grab failed)
            last_error = exc
            match = None
            # En caso de fallo de captura, registrar y continuar reintentando hasta el timeout
            logger.warning(
                "Fallo al capturar pantalla buscando '%s' (intento %s): %s",
                image_path,
                attempt,
                exc,
            )

        if match is not None:
            logger.info("Imagen '%s' encontrada en el intento %s", image_path, attempt)
            return match

        # Intento auxiliar: si se proporciono un icono de barra de tareas, intentamos traer la ventana al frente
        if taskbar_image_name and attempt % max(1, taskbar_click_every) == 0:
            taskbar_image_path = IMAGES_DIR / taskbar_image_name
            try:
                tb_match = pyautogui.locateOnScreen(str(taskbar_image_path), confidence=IMAGE_CONFIDENCE)
            except Exception as exc_tb:
                logger.warning(
                    "Fallo al capturar pantalla buscando icono de barra de tareas '%s' (intento %s): %s",
                    taskbar_image_path,
                    attempt,
                    exc_tb,
                )
                tb_match = None
            if tb_match is not None:
                logger.info("Icono de barra de tareas '%s' encontrado; haciendo clic para restaurar", taskbar_image_path)
                pyautogui.click(pyautogui.center(tb_match))
                time.sleep(1)

        logger.info("Imagen '%s' no encontrada en el intento %s; reintentando", image_path, attempt)
        attempt += 1
        time.sleep(interval)

    logger.error(
        "No se encontro la imagen '%s' en pantalla despues de %s intentos",
        image_path,
        attempt - 1,
    )
    raise TimeoutError(
        f"No se encontro la imagen {image_path} en pantalla despues de {timeout} segundos."
    ) from last_error


def click_button(image_name):
    logger.info("Buscando boton '%s' para hacer clic", image_name)
    button = wait_for_image(image_name)
    pyautogui.click(pyautogui.center(button))
    logger.info("Se hizo clic en el boton '%s'", image_name)
    time.sleep(1)


def apply_version(version):
    logger.info("Aplicando version '%s'", version)
    click_ui_target("version_field")
    time.sleep(1)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(version)
    pyautogui.press("enter")
    time.sleep(1)
    logger.info("Version '%s' aplicada correctamente", version)


def regenerate_identification():
    logger.info("Regenerando identificacion de software")
    click_ui_target("software_identification_btn")
    click_ui_target("generate_now_btn")
    logger.info("Regeneracion de identificacion completada")


def save_and_close():
    logger.info("Guardando cambios y cerrando el instalador")
    pyautogui.hotkey("ctrl", "s")
    time.sleep(1)
    pyautogui.hotkey("alt", "f4")
    time.sleep(1)
    logger.info("Instalador cerrado correctamente")






