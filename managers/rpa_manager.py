from pathlib import Path
import subprocess
import time

import pyautogui

from config import (
    AIP_APIS,
    AIP_BACKEND,
    AIP_FRONTEND,
    AIP_TASK,
    AIP_TASK2,
    BUILD_VERSION,
    PREVIOUS_BUILD_VERSION,
)

DUMMY_VERSION = "1.1.1.1"
IMAGE_CONFIDENCE = 0.8
IMAGE_WAIT_TIMEOUT = 45
IMAGE_WAIT_INTERVAL = 1
IMAGES_DIR = Path(__file__).resolve().parent.parent / "assets" / "images"
AIP_TARGETS = (AIP_BACKEND, AIP_FRONTEND, AIP_APIS, AIP_TASK, AIP_TASK2)


def update_aip_versions():
    change_three_version = change_three_version_number()
    for aip_path in AIP_TARGETS:
        update_aip_version(aip_path, change_three_version)


def update_aip_version(aip_path, change_three_version):
    subprocess.Popen([aip_path], shell=True)
    time.sleep(5)

    try:
        wait_for_image("ai_menu.png")
    except TimeoutError as exc:
        raise RuntimeError(f"No se detecto la pantalla principal al abrir {aip_path}.") from exc

    pyautogui.hotkey("alt", "space")
    time.sleep(1)
    pyautogui.press("x")

    try:
        version_field = wait_for_image("version_field.png")
    except TimeoutError as exc:
        raise RuntimeError(f"No se encontro el campo de version para {aip_path}.") from exc

    if change_three_version:
        apply_version(version_field, BUILD_VERSION)
        regenerate_identification()
        click_button("product_details_btn.png")
    else:
        apply_version(version_field, DUMMY_VERSION)
        regenerate_identification()
        click_button("product_details_btn.png")

        try:
            version_field = wait_for_image("version_field.png")
        except TimeoutError as exc:
            raise RuntimeError(
                f"No se pudo volver a localizar el campo de version para {aip_path}."
            ) from exc

        apply_version(version_field, BUILD_VERSION)
        regenerate_identification()
        click_button("product_details_btn.png")

    save_and_close()


def change_three_version_number():
    v1_parts = PREVIOUS_BUILD_VERSION.split(".")
    v2_parts = BUILD_VERSION.split(".")
    v1_three = int(v1_parts[2])
    v2_three = int(v2_parts[2])
    return v1_three != v2_three


def wait_for_image(image_name, *, timeout: int = IMAGE_WAIT_TIMEOUT, interval: int = IMAGE_WAIT_INTERVAL):
    image_path = IMAGES_DIR / image_name
    deadline = time.perf_counter() + timeout
    last_error = None

    while time.perf_counter() < deadline:
        try:
            match = pyautogui.locateOnScreen(str(image_path), confidence=IMAGE_CONFIDENCE)
        except pyautogui.ImageNotFoundException as exc:
            last_error = exc
            match = None

        if match is not None:
            return match

        time.sleep(interval)

    raise TimeoutError(
        f"No se encontro la imagen {image_path} en pantalla despues de {timeout} segundos."
    ) from last_error


def click_button(image_name):
    button = wait_for_image(image_name)
    pyautogui.click(pyautogui.center(button))
    time.sleep(1)


def apply_version(version_field, version):
    pyautogui.click(pyautogui.center(version_field))
    time.sleep(1)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(version)
    pyautogui.press("enter")
    time.sleep(1)


def regenerate_identification():
    click_button("software_identification_btn.png")
    click_button("generate_now_btn.png")


def save_and_close():
    pyautogui.hotkey("ctrl", "s")
    time.sleep(1)
    pyautogui.hotkey("alt", "f4")
    time.sleep(1)
