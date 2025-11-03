import logging
import subprocess
import time

import pyautogui
try:
    import pyperclip  # type: ignore
except Exception:  # pragma: no cover - opcional
    pyperclip = None  # fallback a tipeo si no está disponible

from config import (
    OPEN_TEAMS_COMMAND,
    TEAMS_CONFIRMATION_PARTICIPANTS,
    TEAMS_CONFIRMATION_POLL_INTERVAL_SECS,
    TEAMS_CONFIRMATION_FIRST_REMINDER_AFTER_SECS,
    TEAMS_CONFIRMATION_REMINDER_EVERY_SECS,
    # Imágenes especiales para controlar el flujo desde el chat
    TEAMS_FORCE_FORWARD_MAIN,
    TEAMS_FORCE_FORWARD_SECONDARY,
    TEAMS_RESTART_MAIN,
    TEAMS_RESTARTD_SECONDARY,
)
from .rpa_manager import wait_for_image, IMAGES_DIR, IMAGE_CONFIDENCE


logger = logging.getLogger(__name__)

_RUNNING = False


def _wait_for_any_image(
    image_names: list[str],
    *,
    timeout: int = 45,
    interval: int = 1,
) -> tuple[object, str]:
    """Espera a que cualquiera de las imagenes aparezca y devuelve (match, nombre_imagen)."""
    deadline = time.perf_counter() + timeout
    attempt = 1
    last_error: Exception | None = None
    paths = [(name, IMAGES_DIR / name) for name in image_names]

    logger.info(
        "Buscando cualquiera de las imagenes: %s (timeout=%ss, intervalo=%ss)",
        image_names,
        timeout,
        interval,
    )

    while time.perf_counter() < deadline:
        for name, path in paths:
            try:
                match = pyautogui.locateOnScreen(str(path), confidence=IMAGE_CONFIDENCE)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Fallo al capturar pantalla buscando '%s' (intento %s): %s",
                    path,
                    attempt,
                    exc,
                )
                match = None
            if match is not None:
                logger.info("Imagen '%s' encontrada en intento %s", name, attempt)
                return match, name

        logger.info(
            "Ninguna de las imagenes %s encontrada en intento %s; reintentando",
            image_names,
            attempt,
        )
        attempt += 1
        time.sleep(interval)

    logger.error(
        "No se encontro ninguna de las imagenes %s despues de %s intentos",
        image_names,
        attempt - 1,
    )
    raise TimeoutError(
        f"No se encontro ninguna de las imagenes {image_names} en pantalla despues de {timeout} segundos."
    ) from last_error


def _paste_text(text: str) -> None:
    """Pega texto usando el portapapeles si es posible; si no, lo tipea.

    Usa pyperclip.copy + Ctrl+V para mayor velocidad y fidelidad (p.ej., textos largos).
    """
    content = text or ""
    try:
        if pyperclip is not None:
            pyperclip.copy(content)
            time.sleep(0.02)
            pyautogui.hotkey("ctrl", "v")
            return
    except Exception:
        # Fallback a tipeo si falla el portapapeles
        logger.debug("Fallo al usar portapapeles; se vuelve a tipeo directo")
    pyautogui.typewrite(content, interval=0.01)


def _type_key_with_optional_link(key: str, link: str) -> None:
    """Escribe la KEY con hipervínculo sin usar Ctrl+K.

    Estrategia: si hay KEY y LINK, escribir/pegar "[KEY](LINK)" (Teams lo renderiza al enviar).
    Si solo hay uno, escribir/pegar el valor disponible como texto plano.
    """
    k = (key or "").strip()
    l = (link or "").strip()

    if not k and not l:
        return

    if k and l:
        _paste_text(f"[{k}]({l})")
    elif k:
        _paste_text(k)
    else:
        _paste_text(l)


def open_teams_and_send_message(
    issues_extended: list[dict],
    header_retries: int = 3,
) -> None:
    """Abre (o enfoca) Microsoft Teams, valida la carga y envia un mensaje formateado.

    Mensaje: por cada issue en ``issues_extended``
    "[KEY](LINK) - SUMMARY - ASSIGNEE_NAME" en una linea, luego Enter para el siguiente.

    Flujo:
    - Si existe el icono en la barra de tareas (teams_taskbar.png), hacer clic para enfocar.
    - De lo contrario, abrir la app usando OPEN_TEAMS_COMMAND.
    - Esperar unos segundos y validar cabecera de Teams (teams_header.png) con reintentos.
    - Hacer clic en el chat objetivo (dev_team_chat_teams.png).
    - Hacer clic en la barra de mensajes (chat_teams_unfocused.png), escribir y enviar Enter.
    """

    global _RUNNING
    if _RUNNING:
        logger.warning("Flujo de Teams ya en ejecucion; se omite invocacion duplicada")
        return
    _RUNNING = True
    try:
        logger.info(
            "Iniciando flujo de Microsoft Teams usando OPEN_TEAMS_COMMAND=%s",
            OPEN_TEAMS_COMMAND,
        )

        taskbar_img = IMAGES_DIR / "teams_taskbar.png"

        # 1) Intentar detectar Teams ya abierto en la barra de tareas
        logger.info("Verificando si Teams ya esta abierto (barra de tareas)")
        try:
            tb_match = pyautogui.locateOnScreen(str(taskbar_img), confidence=IMAGE_CONFIDENCE)
        except Exception as exc:
            logger.warning("Fallo al capturar pantalla para barra de tareas de Teams: %s", exc)
            tb_match = None

        if tb_match is not None:
            logger.info("Icono de Teams en barra de tareas encontrado; haciendo clic para enfocar")
            pyautogui.click(pyautogui.center(tb_match))
        else:
            # 2) Abrir aplicacion si no estaba abierta, usando comando
            logger.info("Teams no detectado en barra de tareas; abriendo via comando")
            try:
                # OPEN_TEAMS_COMMAND suele requerir shell=True (e.g., 'start "" "msteams:"')
                subprocess.Popen(OPEN_TEAMS_COMMAND, shell=True)
            except Exception as exc:
                logger.error(
                    "No se pudo iniciar Microsoft Teams con el comando '%s': %s",
                    OPEN_TEAMS_COMMAND,
                    exc,
                )
                raise

        # 3) Esperar carga inicial
        logger.info("Esperando carga inicial de Teams")
        time.sleep(3)

        # 4) Validar cabecera de Teams con reintentos
        logger.info("Validando apertura de Teams mediante 'teams_header.png'")
        last_exc: Exception | None = None
        for attempt in range(1, max(1, int(header_retries)) + 1):
            try:
                wait_for_image(
                    "teams_header.png",
                    timeout=30,
                    interval=1,
                    taskbar_image_name="teams_taskbar.png",
                    taskbar_click_every=5,
                )
                logger.info("Cabecera de Teams detectada (intento %s)", attempt)
                break
            except TimeoutError as exc:
                last_exc = exc
                logger.warning("No se detecto cabecera de Teams en intento %s; reintentando", attempt)
                time.sleep(2)
        else:
            logger.error(
                "No fue posible confirmar la apertura de Teams tras %s intentos",
                header_retries,
            )
            raise TimeoutError("No se pudo validar la apertura de Microsoft Teams") from last_exc

        # 5) Abrir el chat objetivo (imagen de ancla en la lista de chats)
        logger.info("Buscando chat objetivo: 'dev_team_chat_teams.png'")
        chat_target = wait_for_image("dev_team_chat_teams.png", timeout=45, interval=1)
        pyautogui.click(pyautogui.center(chat_target))
        time.sleep(1)

        # 6) Ubicar barra de mensajes del chat y activarla (unfocused/focused/focused con pipe)
        chat_bar_candidates = [
            "chat_teams_unfocused.png",
            "chat_teams_focused.png",
            "chat_teams_focused_with_pipe.png",
        ]
        logger.info("Buscando barra de mensajes del chat con alguna de: %s", chat_bar_candidates)
        chat_bar_match, used_image = _wait_for_any_image(chat_bar_candidates, timeout=45, interval=1)
        logger.info("Barra de chat detectada usando '%s'", used_image)
        pyautogui.click(pyautogui.center(chat_bar_match))
        time.sleep(0.5)

        # 7) Construir mensaje a partir de issues_extended y enviar
        logger.info("Construyendo mensaje con issues extendidos para Teams")
        triples: list[tuple[str, str, str, str]] = []  # (key, link, summary, assignee)
        for it in issues_extended or []:
            key = (it.get("key") or "").strip()
            link = (it.get("link") or "").strip()
            summary = (it.get("summary") or "").strip()
            assignee_name = (it.get("assignee_name") or "").strip()

            triples.append((key, link, summary, assignee_name))

        logger.info("Escribiendo y enviando mensaje en Teams (%s lineas)", len(triples))
        if not triples:
            # Sin prefijo; mensaje directo en caso de no haber issues
            pyautogui.typewrite("Sin issues para mostrar", interval=0.02)
        else:
            # Sin prefijo; empezar directo con la lista de issues
            for idx, (key, link, summary, assignee_name) in enumerate(triples):
                # Escribir KEY y, si hay link, convertirlo en hipervinculo real (Ctrl+K)
                if key or link:
                    _type_key_with_optional_link(key, link)
                # Separador antes del summary
                pyautogui.typewrite(" - ", interval=0.01)

                # Pegar SUMMARY desde el portapapeles si es posible
                _paste_text(summary)
                time.sleep(0.05)

                # Separador y RESPONSABLE
                pyautogui.typewrite(" - ", interval=0.01)
                _paste_text(assignee_name)

                if idx < len(triples) - 1:
                    # Doble salto de linea sin enviar
                    for _ in range(2):
                        try:
                            pyautogui.keyDown("shift")
                            pyautogui.press("enter")
                        finally:
                            pyautogui.keyUp("shift")
                        time.sleep(0.1)
        # Enviar el mensaje al final
        pyautogui.press("enter")

        # 8) Enviar mensaje de seguimiento
        try:
            time.sleep(0.6)
            logger.info("Enviando mensaje de seguimiento de validación de Jiras")
            pyautogui.typewrite(
                "Robobuild: Por favor, todos deben validar que esten o no sus jiras trabajados, para confirmar esrcibir 'ok!', tal como el ejemplo",
                interval=0.02,
            )
            pyautogui.press("enter")
            time.sleep(0.3)
        except Exception as exc:
            logger.warning("Fallo al enviar mensaje de seguimiento de validación: %s", exc)
        time.sleep(0.5)
        logger.info("Mensaje enviado correctamente a traves de Teams")

        # Fin del flujo
        logger.info("Flujo de Teams finalizado")
    finally:
        _RUNNING = False


def _focus_main_chat_and_bar() -> None:
    """Enfoca el chat principal y la barra de mensajes del chat en Teams."""
    # Intentar confirmar que Teams está visible (si falla, seguimos y buscamos el chat de todos modos)
    try:
        wait_for_image(
            "teams_header.png",
            timeout=15,
            interval=1,
            taskbar_image_name="teams_taskbar.png",
            taskbar_click_every=5,
        )
    except TimeoutError:
        pass

    # Seleccionar el chat principal y luego la barra de mensajes
    chat_target = wait_for_image("dev_team_chat_teams.png", timeout=45, interval=1)
    pyautogui.click(pyautogui.center(chat_target))
    time.sleep(0.6)

    chat_bar_candidates = [
        "chat_teams_unfocused.png",
        "chat_teams_focused.png",
        "chat_teams_focused_with_pipe.png",
    ]
    chat_bar_match, _ = _wait_for_any_image(chat_bar_candidates, timeout=30, interval=1)
    pyautogui.click(pyautogui.center(chat_bar_match))
    time.sleep(0.3)


def _send_chat_message(text: str) -> None:
    _focus_main_chat_and_bar()
    _paste_text(text)
    pyautogui.press("enter")
    time.sleep(0.3)


def _is_any_image_visible(image_names: list[str]) -> bool:
    """Chequea de forma no bloqueante si alguna de las imágenes está visible en pantalla."""
    for name in image_names:
        path = IMAGES_DIR / name
        try:
            match = pyautogui.locateOnScreen(str(path), confidence=IMAGE_CONFIDENCE)
        except Exception:
            match = None
        if match is not None:
            return True
    return False


def _format_missing_names(missing: list[str]) -> str:
    if not missing:
        return ""
    return ", ".join(missing)


def wait_for_ok_confirmations(
    participants: list[dict] | None = None,
    *,
    poll_interval_secs: int | None = None,
    first_reminder_after_secs: int | None = None,
    reminder_every_secs: int | None = None,
) -> str:
    """Espera hasta que todos los participantes habilitados confirmen con "ok!".

    La detección se realiza buscando en pantalla las capturas indicadas para cada persona.
    Envía recordatorios al chat listando las personas que falten después de 10m (configurable)
    y luego repite recordatorios con la periodicidad indicada hasta que todos confirmen.

    También permite controlar el flujo desde el chat con imágenes especiales:
    - Forzar avance (continuar aunque falten "ok!")
    - Reiniciar (cancelar y volver a comenzar el paso)
    Devuelve uno de: "ok", "force", "restart".
    """
    plist = participants if participants is not None else TEAMS_CONFIRMATION_PARTICIPANTS
    poll = poll_interval_secs if poll_interval_secs is not None else TEAMS_CONFIRMATION_POLL_INTERVAL_SECS
    first_rem = (
        first_reminder_after_secs
        if first_reminder_after_secs is not None
        else TEAMS_CONFIRMATION_FIRST_REMINDER_AFTER_SECS
    )
    repeat_rem = (
        reminder_every_secs
        if reminder_every_secs is not None
        else TEAMS_CONFIRMATION_REMINDER_EVERY_SECS
    )

    # Preparar mapa de pendientes: {nombre: ruta_imagen}
    pending: dict[str, str] = {
        (p.get("name") or "").strip(): (p.get("image") or "").strip()
        for p in (plist or [])
        if p.get("enabled", True) and (p.get("name") and p.get("image"))
    }

    if not pending:
        logger.info("No hay participantes habilitados para validar; continuando flujo")
        return "ok"

    logger.info(
        "Esperando confirmaciones de: %s",
        list(pending.keys()),
    )

    start = time.perf_counter()
    next_reminder_at = start + max(0, int(first_rem))

    while pending:
        # 1) Antes de chequear participantes, ver si se solicitó reinicio o forzar avance
        try:
            force_forward_visible = _is_any_image_visible([
                TEAMS_FORCE_FORWARD_MAIN,
                TEAMS_FORCE_FORWARD_SECONDARY,
            ])
            restart_visible = _is_any_image_visible([
                TEAMS_RESTART_MAIN,
                TEAMS_RESTARTD_SECONDARY,
            ])
        except Exception as exc:
            logger.debug("Fallo al chequear imágenes de control de flujo: %s", exc)
            force_forward_visible = False
            restart_visible = False

        if restart_visible:
            logger.warning("Se detectó petición de reinicio desde el chat; reiniciando paso.")
            return "restart"
        if force_forward_visible:
            logger.warning("Se detectó petición de forzar avance desde el chat; continuando sin esperar más confirmaciones.")
            return "force"
        # Revisar todos los pendientes
        to_remove: list[str] = []
        for name, img_name in pending.items():
            img_path = IMAGES_DIR / img_name
            try:
                match = pyautogui.locateOnScreen(str(img_path), confidence=IMAGE_CONFIDENCE)
            except Exception as exc:
                logger.debug("Fallo locateOnScreen para %s (%s): %s", name, img_path, exc)
                match = None

            if match is not None:
                logger.info("Confirmación detectada para '%s' (%s)", name, img_name)
                to_remove.append(name)

        for name in to_remove:
            pending.pop(name, None)

        if not pending:
            break

        now = time.perf_counter()
        if now >= next_reminder_at:
            missing_names = list(pending.keys())
            logger.info("Enviando recordatorio; faltan: %s", missing_names)
            try:
                _send_chat_message(
                    f"Por favor validar los jiras: {_format_missing_names(missing_names)}"
                )
            except Exception as exc:
                logger.warning("No se pudo enviar recordatorio en Teams: %s", exc)
            # Programar siguiente recordatorio
            next_reminder_at = now + max(5, int(repeat_rem))

        time.sleep(max(1, int(poll)))

    logger.info("Todos los participantes confirmaron 'ok!'. Continuando.")
    return "ok"
