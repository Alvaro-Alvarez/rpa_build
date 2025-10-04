from config import AIP_BACKEND, BUILD_VERSION, PREVIOUS_BUILD_VERSION, AIP_FRONTEND, AIP_APIS, AIP_TASK, AIP_TASK2
import subprocess
import pyautogui
import time

dummy_version = "1.1.1.1"
change_three_version = False

def update_aip_versions():
    change_three_version = change_three_version_number()
    update_aip_version(AIP_BACKEND)
    update_aip_version(AIP_FRONTEND)
    update_aip_version(AIP_APIS)
    update_aip_version(AIP_TASK)
    update_aip_version(AIP_TASK2)

def update_aip_version(aip_path):    
    subprocess.Popen([aip_path], shell=True)
    time.sleep(5)

    # valido que la ventana esté
    window = None
    while window is None:
        window = pyautogui.locateOnScreen("images/ai_menu.png", confidence=0.8)
        time.sleep(1)
    
    # Maximizo por las dudas
    pyautogui.hotkey("alt", "space")
    time.sleep(1)
    pyautogui.press("x")

    # Busco el campo de version
    version_field = None
    while version_field is None:
        version_field = pyautogui.locateOnScreen("images/version_field.png", confidence=0.8)
        time.sleep(1)
    
    if change_three_version:     
        # Click en el campo de version y la reemplazo   
        pyautogui.click(pyautogui.center(version_field))
        time.sleep(1)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(BUILD_VERSION)
        pyautogui.press("enter")

        # Click en otro botón para generar nuevo id
        sof_identif_field = None
        sof_identif_field = pyautogui.locateOnScreen("images/software_identification_btn.png", confidence=0.8)
        time.sleep(1)
        pyautogui.click(pyautogui.center(sof_identif_field))
        time.sleep(1)

        # Debería aparecer una ventana para generar nuevo id, le doy al botón para generar nuevo id
        generate_now_btn = None
        generate_now_btn = pyautogui.locateOnScreen("images/generate_now_btn.png", confidence=0.8)
        time.sleep(1)
        pyautogui.click(pyautogui.center(generate_now_btn))
        time.sleep(1)

        # Vuelvo a la sección de detalles del producto para dejarlo preparado para el prox .aip
        pyautogui.click(pyautogui.center(product_details_field))
        time.sleep(1)

        # Guardo y cierro la ventana
        pyautogui.hotkey("ctrl", "s")
        pyautogui.hotkey("alt", "f4")
    else:
        # Click en el campo de version y la reemplazo   
        pyautogui.click(pyautogui.center(version_field))
        time.sleep(1)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(dummy_version)
        pyautogui.press("enter")

        # Click en otro botón para generar nuevo id
        sof_identif_field = None
        sof_identif_field = pyautogui.locateOnScreen("images/software_identification_btn.png", confidence=0.8)
        time.sleep(1)
        pyautogui.click(pyautogui.center(sof_identif_field))
        time.sleep(1)

        # Debería aparecer una ventana para generar nuevo id, le doy al botón para generar nuevo id
        generate_now_btn = None
        generate_now_btn = pyautogui.locateOnScreen("images/generate_now_btn.png", confidence=0.8)
        time.sleep(1)
        pyautogui.click(pyautogui.center(generate_now_btn))
        time.sleep(1)

        # Como puse una version dummy, debo volver a cambiar la version y generar el id otra vez
        # Click en el boton de detalles del producto
        product_details_field = None
        product_details_field = pyautogui.locateOnScreen("images/product_details_btn.png", confidence=0.8)
        time.sleep(1)
        pyautogui.click(pyautogui.center(product_details_field))
        time.sleep(1)

        # Click en el campo de version y la reemplazo   
        pyautogui.click(pyautogui.center(version_field))
        time.sleep(1)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(BUILD_VERSION)
        pyautogui.press("enter")

        # Click en otro botón para generar nuevo id
        sof_identif_field = None
        sof_identif_field = pyautogui.locateOnScreen("images/software_identification_btn.png", confidence=0.8)
        time.sleep(1)
        pyautogui.click(pyautogui.center(sof_identif_field))
        time.sleep(1)

        # Debería aparecer una ventana para generar nuevo id, le doy al botón para generar nuevo id
        generate_now_btn = None
        generate_now_btn = pyautogui.locateOnScreen("images/generate_now_btn.png", confidence=0.8)
        time.sleep(1)
        pyautogui.click(pyautogui.center(generate_now_btn))
        time.sleep(1)

        # Vuelvo a la sección de detalles del producto para dejarlo preparado para el prox .aip
        pyautogui.click(pyautogui.center(product_details_field))
        time.sleep(1)

        # Guardo y cierro la ventana
        pyautogui.hotkey("ctrl", "s")
        pyautogui.hotkey("alt", "f4")


def change_three_version_number():
    v1_parts = PREVIOUS_BUILD_VERSION.split(".")
    v2_parts = BUILD_VERSION.split(".")
    v1_three = int(v1_parts[2])
    v2_three = int(v2_parts[2])
    return v1_three != v2_three