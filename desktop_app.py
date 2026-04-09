import importlib
import json
import logging
import math
import sys
import threading
from pathlib import Path

import config as config_module
from PySide6 import QtCore, QtGui, QtWidgets

from build_runner import BuildRunner
from environment_health import run_environment_health_checks
from enums.enums import Accion
from logging_config import setup_logging

APP_TITLE = "CitySensAI Build"
CONFIG_OVERRIDES_PATH = config_module.CONFIG_OVERRIDES_PATH
PIPELINE_LAYOUT_PATH = config_module.APP_STATE_DIR / "pipeline_layout.json"

ACTION_META: dict[Accion, dict[str, str]] = {
    Accion.GET_JIRA_ISSUES: {
        "title": "1. Validar Jira",
        "subtitle": "Revisa inconsistencias en tags y FixVersion antes de exportar el changelog.",
    },
    Accion.UPDATE_CHANGE_LOG: {
        "title": "2. Actualizar Change Log",
        "subtitle": "Actualiza el changelog de C2IS con el JSON generado desde Jira.",
    },
    Accion.UPDATE_ASSEMBLY_VERSIONS: {
        "title": "3. Actualizar Assembly Versions",
        "subtitle": "Sube la version de los AssemblyInfo en los codigos habilitados.",
    },
    Accion.UPDATE_AIP_VERSIONS: {
        "title": "4. Actualizar AIP Versions",
        "subtitle": "Abre Advanced Installer y actualiza versiones de instaladores.",
    },
    Accion.UPLOAD_CODE_AND_PR: {
        "title": "5. Publicar Codigo y PR",
        "subtitle": "Crea rama, hace commit, push y dispara PR/builds en TFS.",
    },
    Accion.BUILD_PACKAGE: {
        "title": "6. Armar Paquete",
        "subtitle": "Crea la estructura de despliegue y el acceso directo de CCSI.",
    },
}

GENERAL_FIELDS = [
    {"name": "BUILD_VERSION", "label": "Version Build", "help": "Version objetivo principal usada por el flujo general del build.", "multiline": False},
    {"name": "PREVIOUS_BUILD_VERSION", "label": "Version Build Anterior", "help": "Version anterior esperada para reemplazos en AssemblyInfo y versiones globales.", "multiline": False},
    {"name": "CURRENT_VERSION_CCSI", "label": "Version Actual CCSI", "help": "Version actual/base de CCSI usada por el flujo de instaladores y package.", "multiline": False},
    {"name": "NEXT_VERSION_CCSI", "label": "Version Nueva CCSI", "help": "Version nueva/objetivo de CCSI.", "multiline": False},
    {"name": "MAIN_BRANCH", "label": "Rama Principal", "help": "Rama base contra la que se sincronizan los repos y se abren PRs.", "multiline": False},
    {"name": "JIRA_URL", "label": "Jira URL", "help": "Base URL del Jira consultado por el proceso.", "multiline": False},
    {"name": "JIRA_USER", "label": "Jira User", "help": "Usuario usado para autenticar contra Jira.", "multiline": False},
    {"name": "JIRA_TOKEN", "label": "Jira Token", "help": "Token de acceso de Jira.", "multiline": False},
    {"name": "JIRA_JQL", "label": "Jira JQL", "help": "Consulta base para obtener los issues de la build.", "multiline": True},
    {"name": "JIRA_VALIDATE_TAGS", "label": "Jira Validate Tags", "help": "Consulta que detecta issues incompletos antes de continuar.", "multiline": True},
    {"name": "OPEN_AI_KEY", "label": "Clave OpenAI", "help": "Clave usada por la integracion auxiliar de IA.", "multiline": False},
    {"name": "BUILDS_PACKAGE_DIRECTORY", "label": "Directorio Package", "help": "Share donde se arma la carpeta de despliegue principal.", "multiline": False},
    {"name": "BUILD_CCSI_DIRECTORY", "label": "Directorio CCSI", "help": "Share donde se encuentra o crea la carpeta de version de CCSI.", "multiline": False},
]

CODE_FIELD_HELP = {
    "enabled": "Activa o desactiva este codigo dentro del flujo.",
    "code_path": "Ruta local al repositorio del codigo.",
    "main_branch": "Rama principal usada para sincronizar y abrir PRs.",
    "versions.current": "Version base o actual del codigo.",
    "versions.next": "Version nueva u objetivo del codigo.",
    "change_log_path": "Ruta al change log. Solo aplica si este codigo mantiene changelog.",
    "assembly_paths": "Archivos AssemblyInfo.cs que se deben actualizar. Una ruta por linea.",
    "aip_paths": "Instaladores .aip asociados al codigo. Una ruta por linea.",
    "tfs.BASE_URL": "URL base del servidor TFS/Azure DevOps.",
    "tfs.ORG": "Coleccion u organizacion de TFS.",
    "tfs.PROJECT": "Proyecto de TFS.",
    "tfs.REPO_ID": "Identificador del repositorio en TFS.",
    "tfs.PAT": "Personal Access Token del proyecto TFS.",
    "tfs.BUILD_DEFINITION_ID": "Definicion principal de build.",
    "tfs.BUILD_DEFINITION_IDS": "Lista de definiciones separadas por coma para validar el PR.",
    "tfs.TFS_POLL_INTERVAL": "Intervalo de polling en segundos.",
    "tfs.TFS_TIMEOUT_SECS": "Timeout total de espera para builds/revisiones.",
    "tfs.TFS_GIT_API_VERSION": "Version de API Git usada contra TFS.",
    "tfs.TFS_BUILD_API_VERSION": "Version de API Build usada contra TFS.",
}


class LogEmitter(QtCore.QObject):
    message = QtCore.Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self._emitter = emitter
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        self._emitter.message.emit(message)


class LogWindow(QtWidgets.QMainWindow):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Logs en vivo")
        self.resize(980, 640)

        self.logs_edit = QtWidgets.QPlainTextEdit()
        self.logs_edit.setReadOnly(True)
        self.logs_edit.setMaximumBlockCount(4000)
        self.setCentralWidget(self.logs_edit)

    def append_log(self, message: str) -> None:
        scrollbar = self.logs_edit.verticalScrollBar()
        old_value = scrollbar.value()
        should_autoscroll = scrollbar.maximum() > 0 and old_value >= max(0, scrollbar.maximum() - 20)
        self.logs_edit.appendPlainText(message)
        if should_autoscroll:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(old_value)


class ConfigWindow(QtWidgets.QMainWindow):
    def __init__(self, config_editor: "ConfigEditorWidget", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuracion")
        self.resize(1100, 820)
        self.setCentralWidget(config_editor)


class EnvironmentHealthWorker(QtCore.QObject):
    finished = QtCore.Signal(object)

    @QtCore.Slot()
    def run(self) -> None:
        self.finished.emit(run_environment_health_checks())


class EnvironmentHealthWindow(QtWidgets.QMainWindow):
    loading_changed = QtCore.Signal(bool)
    loading_text_changed = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Salud del entorno")
        self.resize(1080, 720)
        self._spinner_frames = ["|", "/", "-", "\\"]
        self._spinner_index = 0
        self._is_loading = False
        self._worker_thread: QtCore.QThread | None = None
        self._worker: EnvironmentHealthWorker | None = None

        self._spinner_timer = QtCore.QTimer(self)
        self._spinner_timer.setInterval(120)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        header_layout = QtWidgets.QHBoxLayout()
        title_box = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("Salud del entorno")
        title.setObjectName("sectionTitle")
        subtitle = QtWidgets.QLabel("Valida software, conectividad y rutas configuradas antes de ejecutar el flujo.")
        subtitle.setObjectName("sectionSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self.refresh_button = QtWidgets.QPushButton("Volver a validar")
        header_layout.addWidget(self.refresh_button)
        root_layout.addLayout(header_layout)

        self.summary_label = QtWidgets.QLabel("Aun no se ejecutaron validaciones.")
        self.summary_label.setObjectName("healthSummary")
        self.summary_label.setWordWrap(True)
        root_layout.addWidget(self.summary_label)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Estado", "Categoria", "Chequeo", "Detalle"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        root_layout.addWidget(self.table, 1)

        self.refresh_button.clicked.connect(self.refresh_checks)

    def refresh_checks(self) -> None:
        if self._is_loading:
            return
        self._set_loading(True)
        self.summary_label.setText("Validando entorno...")

        self._worker_thread = QtCore.QThread(self)
        self._worker = EnvironmentHealthWorker()
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_checks_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.finished.connect(self._on_worker_thread_finished)
        self._worker_thread.start()

    def _on_checks_finished(self, checks: object) -> None:
        checks = list(checks or [])
        self.table.setRowCount(len(checks))

        ok_count = 0
        warning_count = 0
        error_count = 0
        for row, check in enumerate(checks):
            status = str(check.get("status") or "")
            if status == "ok":
                ok_count += 1
                status_text = "OK"
                status_color = QtGui.QColor("#166534")
                background = QtGui.QColor("#ecfdf3")
            elif status == "warning":
                warning_count += 1
                status_text = "Aviso"
                status_color = QtGui.QColor("#9a3412")
                background = QtGui.QColor("#fff7ed")
            else:
                error_count += 1
                status_text = "Error"
                status_color = QtGui.QColor("#b91c1c")
                background = QtGui.QColor("#fff1f2")

            items = [
                QtWidgets.QTableWidgetItem(status_text),
                QtWidgets.QTableWidgetItem(str(check.get("category") or "")),
                QtWidgets.QTableWidgetItem(str(check.get("name") or "")),
                QtWidgets.QTableWidgetItem(str(check.get("detail") or "")),
            ]
            for item in items:
                item.setBackground(background)
                if item is items[0]:
                    item.setForeground(status_color)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            for column, item in enumerate(items):
                self.table.setItem(row, column, item)

        if error_count:
            self.summary_label.setText(
                f"Se detectaron {error_count} errores, {warning_count} avisos y {ok_count} validaciones correctas."
            )
        elif warning_count:
            self.summary_label.setText(
                f"No hay errores bloqueantes. Se detectaron {warning_count} avisos y {ok_count} validaciones correctas."
            )
        else:
            self.summary_label.setText(f"Entorno validado correctamente. {ok_count} chequeos OK.")

        self._set_loading(False)

    def _on_worker_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None

    def _set_loading(self, loading: bool) -> None:
        self._is_loading = loading
        self.refresh_button.setEnabled(not loading)
        self.loading_changed.emit(loading)
        if loading:
            self._spinner_index = 0
            self._spinner_timer.start()
            self._tick_spinner()
        else:
            self._spinner_timer.stop()
            self.refresh_button.setText("Volver a validar")
            self.loading_text_changed.emit("Salud del entorno")

    def _tick_spinner(self) -> None:
        if not self._is_loading:
            return
        frame = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
        self._spinner_index += 1
        text = f"{frame} Validando..."
        self.refresh_button.setText(text)
        self.loading_text_changed.emit(text)


class DescriptionDialog(QtWidgets.QDialog):
    def __init__(self, title: str, description: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Descripcion del paso")
        self.setModal(True)
        self.setMinimumWidth(420)

        icon_label = QtWidgets.QLabel("i")
        icon_label.setObjectName("descriptionIcon")
        icon_label.setAlignment(QtCore.Qt.AlignCenter)
        icon_label.setFixedSize(28, 28)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("descriptionTitle")
        title_label.setWordWrap(True)

        description_label = QtWidgets.QLabel(description)
        description_label.setObjectName("descriptionText")
        description_label.setWordWrap(True)
        description_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        close_button = QtWidgets.QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(10)
        header_layout.addWidget(icon_label, alignment=QtCore.Qt.AlignTop)
        header_layout.addWidget(title_label, 1)

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)
        root_layout.addLayout(header_layout)
        root_layout.addWidget(description_label)
        root_layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

        self.setStyleSheet(
            """
            QDialog {
                background: #ffffff;
            }
            QLabel#descriptionIcon {
                background: #dbeafe;
                color: #1d4ed8;
                border: 1px solid #93c5fd;
                border-radius: 14px;
                font-size: 12pt;
                font-weight: 700;
            }
            QLabel#descriptionTitle {
                color: #0f172a;
                font-size: 11pt;
                font-weight: 700;
            }
            QLabel#descriptionText {
                color: #334155;
                font-size: 10pt;
                line-height: 1.3;
            }
            """
        )


class NodeProxyWidget(QtWidgets.QGraphicsProxyWidget):
    def __init__(self, action_value: str, board: "PipelineBoard") -> None:
        super().__init__()
        self.action_value = action_value
        self.board = board
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCacheMode(QtWidgets.QGraphicsItem.DeviceCoordinateCache)
        self.setCursor(QtCore.Qt.OpenHandCursor)
        self._drag_origin_scene_pos: QtCore.QPointF | None = None
        self._drag_origin_item_pos: QtCore.QPointF | None = None

    def setWidget(self, widget: QtWidgets.QWidget) -> None:
        super().setWidget(widget)
        drag_widgets: list[QtWidgets.QWidget] = [widget]
        drag_handle = getattr(widget, "drag_handle", None)
        if isinstance(drag_handle, QtWidgets.QWidget):
            drag_widgets.append(drag_handle)
        for child_name in ("title_label", "message_label"):
            child = getattr(widget, child_name, None)
            if isinstance(child, QtWidgets.QWidget):
                drag_widgets.append(child)
        for drag_widget in drag_widgets:
            drag_widget.installEventFilter(self)

    def itemChange(self, change: QtWidgets.QGraphicsItem.GraphicsItemChange, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            self.board._manual_layout_dirty = True
        if change == QtWidgets.QGraphicsItem.ItemPositionHasChanged:
            self.board.update_connectors()
            self.board.update_scene_rect()
            self.board.schedule_layout_save()
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        self.setCursor(QtCore.Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        self.setCursor(QtCore.Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.MouseButtonPress and isinstance(event, QtGui.QMouseEvent):
            if event.button() == QtCore.Qt.LeftButton:
                self._drag_origin_scene_pos = self.board.mapToScene(
                    self.board.mapFromGlobal(event.globalPosition().toPoint())
                )
                self._drag_origin_item_pos = self.pos()
                self.setCursor(QtCore.Qt.ClosedHandCursor)
                return True

        if event.type() == QtCore.QEvent.MouseMove and isinstance(event, QtGui.QMouseEvent):
            if self._drag_origin_scene_pos is not None and self._drag_origin_item_pos is not None:
                current_scene_pos = self.board.mapToScene(
                    self.board.mapFromGlobal(event.globalPosition().toPoint())
                )
                delta = current_scene_pos - self._drag_origin_scene_pos
                self.setPos(self._drag_origin_item_pos + delta)
                return True

        if event.type() == QtCore.QEvent.MouseButtonRelease and isinstance(event, QtGui.QMouseEvent):
            if self._drag_origin_scene_pos is not None:
                self._drag_origin_scene_pos = None
                self._drag_origin_item_pos = None
                self.setCursor(QtCore.Qt.OpenHandCursor)
                return True

        return super().eventFilter(watched, event)


class PipelineBoard(QtWidgets.QGraphicsView):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QtGui.QPainter.Antialiasing, True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setObjectName("pipelineBoard")
        self._cards: dict[str, StepCard] = {}
        self._ordered_actions: list[Accion] = []
        self._proxy_items: dict[str, NodeProxyWidget] = {}
        self._connector_items: list[tuple[QtWidgets.QGraphicsPathItem, QtWidgets.QGraphicsPolygonItem]] = []
        self._manual_layout_dirty = False
        self._is_layouting = False
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_layout_positions)
        self._saved_positions = self._load_layout_positions()

    def set_cards(self, ordered_actions: list[Accion], cards: dict[str, "StepCard"]) -> None:
        self._scene.clear()
        self._cards = cards
        self._ordered_actions = ordered_actions
        self._proxy_items.clear()
        self._connector_items.clear()
        self._manual_layout_dirty = False
        self._is_layouting = True

        for action in ordered_actions:
            card = cards[action.value]
            proxy = NodeProxyWidget(action.value, self)
            proxy.setWidget(card)
            self._scene.addItem(proxy)
            proxy.setZValue(1)
            self._proxy_items[action.value] = proxy

        self.relayout()
        self._apply_saved_layout_positions()
        self._is_layouting = False
        self.update_connectors()
        self.update_scene_rect()

    def relayout(self) -> None:
        if not self._ordered_actions:
            return
        self._is_layouting = True

        viewport_width = max(720, self.viewport().width() - 24)
        sample_card = self._cards[self._ordered_actions[0].value]
        sample_card.adjustSize()
        node_width = sample_card.sizeHint().width()
        node_height = sample_card.sizeHint().height()
        horizontal_gap = 56
        vertical_gap = 68
        margin = 28

        columns = len(self._ordered_actions)
        positions: dict[str, QtCore.QPointF] = {}

        for row_index, row_start in enumerate(range(0, len(self._ordered_actions), columns)):
            row_actions = self._ordered_actions[row_start:row_start + columns]
            display_actions = list(row_actions)
            row_width = len(display_actions) * node_width + max(0, len(display_actions) - 1) * horizontal_gap
            x_offset = margin + max(0, (viewport_width - row_width) / 2)
            y = margin + row_index * (node_height + vertical_gap)

            for display_index, action in enumerate(display_actions):
                x = x_offset + display_index * (node_width + horizontal_gap)
                positions[action.value] = QtCore.QPointF(x, y)

        for action in self._ordered_actions:
            proxy = self._proxy_items[action.value]
            proxy.setPos(positions[action.value])

        self._rebuild_connectors()
        self.update_scene_rect()
        self._is_layouting = False

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._manual_layout_dirty:
            self.relayout()
        else:
            self.update_scene_rect()

    def schedule_layout_save(self) -> None:
        if self._is_layouting:
            return
        self._save_timer.start()

    def _load_layout_positions(self) -> dict[str, QtCore.QPointF]:
        if not PIPELINE_LAYOUT_PATH.exists():
            return {}
        try:
            raw_data = json.loads(PIPELINE_LAYOUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

        positions: dict[str, QtCore.QPointF] = {}
        for action_value, point in raw_data.items():
            if isinstance(point, dict):
                try:
                    positions[action_value] = QtCore.QPointF(float(point["x"]), float(point["y"]))
                except Exception:
                    continue
        return positions

    def _apply_saved_layout_positions(self) -> None:
        if not self._saved_positions:
            return

        applied = False
        for action in self._ordered_actions:
            point = self._saved_positions.get(action.value)
            proxy = self._proxy_items.get(action.value)
            if point is None or proxy is None:
                continue
            proxy.setPos(point)
            applied = True

        if applied:
            self._manual_layout_dirty = True
            self.update_connectors()
            self.update_scene_rect()

    def _save_layout_positions(self) -> None:
        payload: dict[str, dict[str, float]] = {}
        for action in self._ordered_actions:
            proxy = self._proxy_items.get(action.value)
            if proxy is None:
                continue
            pos = proxy.pos()
            payload[action.value] = {"x": round(pos.x(), 2), "y": round(pos.y(), 2)}

        try:
            PIPELINE_LAYOUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return
        self._saved_positions = {
            action_value: QtCore.QPointF(point["x"], point["y"])
            for action_value, point in payload.items()
        }

    def _rebuild_connectors(self) -> None:
        for path_item, arrow_item in self._connector_items:
            self._scene.removeItem(path_item)
            self._scene.removeItem(arrow_item)
        self._connector_items.clear()

        for _ in zip(self._ordered_actions, self._ordered_actions[1:]):
            path_item = QtWidgets.QGraphicsPathItem()
            path_item.setZValue(0)
            arrow_item = QtWidgets.QGraphicsPolygonItem()
            arrow_item.setZValue(0)
            self._scene.addItem(path_item)
            self._scene.addItem(arrow_item)
            self._connector_items.append((path_item, arrow_item))
        self.update_connectors()

    def update_connectors(self) -> None:
        if self._is_layouting or len(self._ordered_actions) < 2:
            return

        pen = QtGui.QPen(QtGui.QColor("#6f96c7"))
        pen.setWidth(3)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        arrow_brush = QtGui.QBrush(QtGui.QColor("#6f96c7"))

        pairs = list(zip(self._ordered_actions, self._ordered_actions[1:]))
        if len(self._connector_items) < len(pairs):
            return

        for index, (current_action, next_action) in enumerate(pairs):
            path_item, arrow_item = self._connector_items[index]
            current_proxy = self._proxy_items[current_action.value]
            next_proxy = self._proxy_items[next_action.value]
            current_rect = current_proxy.sceneBoundingRect()
            next_rect = next_proxy.sceneBoundingRect()

            start = QtCore.QPointF(current_rect.right(), current_rect.center().y())
            end = QtCore.QPointF(next_rect.left(), next_rect.center().y())

            path = QtGui.QPainterPath(start)
            dx = end.x() - start.x()
            if abs(end.y() - start.y()) < 10 and dx > 0:
                curve = min(56, max(28, dx / 2))
                path.cubicTo(
                    start.x() + curve, start.y(),
                    end.x() - curve, end.y(),
                    end.x(), end.y(),
                )
            else:
                mid_x = start.x() + max(38, min(110, abs(dx) / 2 + 18))
                path.cubicTo(
                    mid_x, start.y(),
                    max(end.x() - 48, start.x() + 30), end.y(),
                    end.x(), end.y(),
                )

            path_item.setPath(path)
            path_item.setPen(pen)

            tangent = path.angleAtPercent(0.98)
            arrow_size = 10.0
            end_point = path.pointAtPercent(1.0)
            angle_rad = -math.radians(tangent)
            p1 = end_point + QtCore.QPointF(
                -arrow_size * math.cos(angle_rad - 0.45),
                arrow_size * math.sin(angle_rad - 0.45),
            )
            p2 = end_point + QtCore.QPointF(
                -arrow_size * math.cos(angle_rad + 0.45),
                arrow_size * math.sin(angle_rad + 0.45),
            )
            arrow_item.setPolygon(QtGui.QPolygonF([end_point, p1, p2]))
            arrow_item.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            arrow_item.setBrush(arrow_brush)

    def update_scene_rect(self) -> None:
        if not self._proxy_items:
            return
        bounds = self._scene.itemsBoundingRect()
        padding = 80
        self._scene.setSceneRect(bounds.adjusted(-padding, -padding, padding, padding))

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        super().drawBackground(painter, rect)
        painter.save()
        painter.fillRect(rect, QtGui.QColor("#eef3f9"))
        pen = QtGui.QPen(QtGui.QColor("#dfe7f1"))
        pen.setWidth(1)
        painter.setPen(pen)
        grid = 24
        start_x = int(rect.left()) - (int(rect.left()) % grid)
        start_y = int(rect.top()) - (int(rect.top()) % grid)
        x = start_x
        while x < rect.right():
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += grid
        y = start_y
        while y < rect.bottom():
            painter.drawLine(rect.left(), y, rect.right(), y)
            y += grid
        painter.restore()


class StepCard(QtWidgets.QFrame):
    run_requested = QtCore.Signal(str)

    def __init__(self, action: Accion, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.action = action
        self.setObjectName("stepCard")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setMinimumWidth(220)
        self.setMaximumWidth(220)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        meta = ACTION_META[action]
        self.drag_handle = QtWidgets.QLabel("::::")
        self.drag_handle.setObjectName("dragHandle")
        self.title_label = QtWidgets.QLabel(meta["title"])
        self.title_label.setObjectName("stepTitle")
        self.title_label.setWordWrap(True)
        title_font = QtGui.QFont("Segoe UI", 10)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.help_button = QtWidgets.QToolButton()
        self.help_button.setObjectName("nodeHelpButton")
        self.help_button.setText("?")
        self.help_button.setToolTip("Ver descripcion del paso")
        self.help_button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.help_button.setFixedSize(22, 22)
        self.help_button.setStyleSheet(
            """
            QToolButton {
                background: #e8f0ff;
                color: #3157c7;
                border: 1px solid #c7d7ff;
                border-radius: 11px;
                font-size: 10pt;
                font-weight: 700;
            }
            QToolButton:hover {
                background: #dce8ff;
                border-color: #aabff7;
            }
            """
        )
        self.help_button.clicked.connect(self._show_description_popup)
        self.status_badge = QtWidgets.QLabel("Pendiente")
        self.status_badge.setObjectName("statusBadge")
        self.status_badge.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.message_label = QtWidgets.QLabel("Sin ejecutar")
        self.message_label.setObjectName("stepMessage")
        message_font = QtGui.QFont("Segoe UI", 8)
        message_font.setBold(True)
        self.message_label.setFont(message_font)
        self.run_button = QtWidgets.QPushButton("Ejecutar")
        self.run_button.clicked.connect(lambda: self.run_requested.emit(self.action.value))
        self.run_button.setObjectName("nodeButton")

        header_layout = QtWidgets.QGridLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setHorizontalSpacing(8)
        header_layout.setVerticalSpacing(6)
        header_layout.addWidget(self.drag_handle, 0, 0, alignment=QtCore.Qt.AlignTop)
        header_layout.addWidget(self.title_label, 0, 1, alignment=QtCore.Qt.AlignTop)
        header_layout.addWidget(self.help_button, 0, 2, alignment=QtCore.Qt.AlignTop)
        header_layout.addWidget(self.status_badge, 1, 1, 1, 2, alignment=QtCore.Qt.AlignRight)
        header_layout.setColumnStretch(1, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(header_layout)
        layout.addWidget(self.message_label)
        layout.addWidget(self.run_button, alignment=QtCore.Qt.AlignRight)

        self.set_status("pending", "Sin ejecutar")

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(rect), 8, 8)
        painter.fillPath(path, QtGui.QColor("#ffffff"))
        pen = QtGui.QPen(QtGui.QColor("#d9e4ef"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)
        super().paintEvent(event)

    def _show_description_popup(self) -> None:
        description = ACTION_META[self.action]["subtitle"]
        dialog = DescriptionDialog(self.title_label.text(), description, self)
        dialog.exec()

    def set_status(self, status: str, message: str = "") -> None:
        palette = {
            "pending": ("Pendiente", "#65748b", "#f4f6fb", "#d8dfec"),
            "running": ("En curso", "#0f766e", "#e6fffa", "#8ee5d7"),
            "waiting": ("Esperando", "#b45309", "#fff7ed", "#f4c27b"),
            "success": ("Correcto", "#166534", "#ecfdf3", "#8de3b1"),
            "error": ("Error", "#b91c1c", "#fff1f2", "#f3a6ae"),
        }
        title, fg, bg, border = palette.get(status, palette["pending"])
        self.status_badge.setText(title)
        self.status_badge.setStyleSheet(
            f"color: {fg}; background: {bg}; border: 1px solid {border}; border-radius: 12px; padding: 4px 10px; font-weight: 600;"
        )
        self.message_label.setText(message or "Sin detalles")

    def set_enabled_for_run(self, enabled: bool) -> None:
        self.run_button.setEnabled(enabled)


class PipelineWorker(QtCore.QObject):
    step_changed = QtCore.Signal(str, str, str)
    review_required = QtCore.Signal(object)
    review_cleared = QtCore.Signal()
    execution_finished = QtCore.Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self._decision_event = threading.Event()
        self._decision_value = "ok"

    @QtCore.Slot(object)
    def run_actions(self, action_values: object) -> None:
        try:
            actions = [Accion(value) for value in list(action_values or [])]
            runner = BuildRunner(decision_handler=self._request_decision, step_callback=self._step_changed)
            runner.start_building(actions)
        except Exception as exc:
            self.execution_finished.emit(False, str(exc))
            return
        self.execution_finished.emit(True, "Proceso finalizado")

    @QtCore.Slot(str)
    def submit_decision(self, decision: str) -> None:
        self._decision_value = decision
        self._decision_event.set()

    def _step_changed(self, action: Accion, status: str, message: str) -> None:
        self.step_changed.emit(action.value, status, message)

    def _request_decision(self, issues_extended: list[dict]) -> str:
        self._decision_value = "ok"
        self._decision_event.clear()
        self.review_required.emit(issues_extended)
        self._decision_event.wait()
        self.review_cleared.emit()
        return self._decision_value


def _create_help_label(text: str, help_text: str) -> QtWidgets.QWidget:
    container = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    label = QtWidgets.QLabel(text)
    button = QtWidgets.QToolButton()
    button.setText("?")
    button.setToolTip(help_text)
    button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
    button.setAutoRaise(True)
    button.setFixedSize(20, 20)
    layout.addWidget(label)
    layout.addWidget(button)
    layout.addStretch(1)
    return container


class CodeEditorWidget(QtWidgets.QWidget):
    def __init__(self, code_name: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.code_name = code_name
        self.fields: dict[str, QtWidgets.QWidget] = {}
        self.setObjectName("codeEditor")

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(16)

        general_group = QtWidgets.QGroupBox("Codigo")
        general_form = QtWidgets.QFormLayout(general_group)
        general_form.setSpacing(16)
        general_form.setLabelAlignment(QtCore.Qt.AlignTop)
        general_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        general_form.setContentsMargins(16, 20, 16, 16)

        self.fields["enabled"] = QtWidgets.QCheckBox("Habilitado")
        general_form.addRow(_create_help_label("Habilitado", CODE_FIELD_HELP["enabled"]), self.fields["enabled"])

        self.fields["code_path"] = QtWidgets.QLineEdit()
        general_form.addRow(_create_help_label("Ruta del codigo", CODE_FIELD_HELP["code_path"]), self.fields["code_path"])

        self.fields["main_branch"] = QtWidgets.QLineEdit()
        general_form.addRow(_create_help_label("Rama principal", CODE_FIELD_HELP["main_branch"]), self.fields["main_branch"])

        self.fields["versions.current"] = QtWidgets.QLineEdit()
        general_form.addRow(_create_help_label("Version actual", CODE_FIELD_HELP["versions.current"]), self.fields["versions.current"])

        self.fields["versions.next"] = QtWidgets.QLineEdit()
        general_form.addRow(_create_help_label("Version nueva", CODE_FIELD_HELP["versions.next"]), self.fields["versions.next"])

        self.fields["change_log_path"] = QtWidgets.QLineEdit()
        general_form.addRow(_create_help_label("Ruta del change log", CODE_FIELD_HELP["change_log_path"]), self.fields["change_log_path"])

        self.fields["assembly_paths"] = QtWidgets.QPlainTextEdit()
        self.fields["assembly_paths"].setMinimumHeight(120)
        general_form.addRow(_create_help_label("Assembly paths", CODE_FIELD_HELP["assembly_paths"]), self.fields["assembly_paths"])

        self.fields["aip_paths"] = QtWidgets.QPlainTextEdit()
        self.fields["aip_paths"].setMinimumHeight(120)
        general_form.addRow(_create_help_label("AIP paths", CODE_FIELD_HELP["aip_paths"]), self.fields["aip_paths"])

        tfs_group = QtWidgets.QGroupBox("TFS")
        tfs_form = QtWidgets.QFormLayout(tfs_group)
        tfs_form.setSpacing(16)
        tfs_form.setLabelAlignment(QtCore.Qt.AlignTop)
        tfs_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        tfs_form.setContentsMargins(16, 20, 16, 16)
        for key in [
            "BASE_URL",
            "ORG",
            "PROJECT",
            "REPO_ID",
            "PAT",
            "BUILD_DEFINITION_ID",
            "BUILD_DEFINITION_IDS",
            "TFS_POLL_INTERVAL",
            "TFS_TIMEOUT_SECS",
            "TFS_GIT_API_VERSION",
            "TFS_BUILD_API_VERSION",
        ]:
            widget = QtWidgets.QLineEdit()
            self.fields[f"tfs.{key}"] = widget
            tfs_form.addRow(_create_help_label(key, CODE_FIELD_HELP[f"tfs.{key}"]), widget)

        for field_name, widget in self.fields.items():
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.setMinimumHeight(34)
            elif isinstance(widget, QtWidgets.QPlainTextEdit):
                widget.setTabChangesFocus(True)

        root_layout.addWidget(general_group)
        root_layout.addWidget(tfs_group)
        root_layout.addStretch(1)

    def load_data(self, code_data: dict) -> None:
        self._checkbox("enabled").setChecked(bool(code_data.get("enabled")))
        self._line("code_path").setText(str(code_data.get("code_path") or ""))
        self._line("main_branch").setText(str(code_data.get("main_branch") or ""))
        versions = code_data.get("versions") or {}
        self._line("versions.current").setText(str(versions.get("current") or ""))
        self._line("versions.next").setText(str(versions.get("next") or ""))
        self._line("change_log_path").setText(str(code_data.get("change_log_path") or ""))
        self._plain("assembly_paths").setPlainText("\n".join(code_data.get("assembly_paths") or []))
        self._plain("aip_paths").setPlainText("\n".join(code_data.get("aip_paths") or []))

        tfs = code_data.get("tfs") or {}
        for key in [
            "BASE_URL",
            "ORG",
            "PROJECT",
            "REPO_ID",
            "PAT",
            "BUILD_DEFINITION_ID",
            "BUILD_DEFINITION_IDS",
            "TFS_POLL_INTERVAL",
            "TFS_TIMEOUT_SECS",
            "TFS_GIT_API_VERSION",
            "TFS_BUILD_API_VERSION",
        ]:
            self._line(f"tfs.{key}").setText("" if tfs.get(key) is None else str(tfs.get(key)))

    def build_override(self) -> dict:
        tfs_override: dict[str, object] = {}
        for key in [
            "BASE_URL",
            "ORG",
            "PROJECT",
            "REPO_ID",
            "PAT",
            "BUILD_DEFINITION_ID",
            "BUILD_DEFINITION_IDS",
            "TFS_POLL_INTERVAL",
            "TFS_TIMEOUT_SECS",
            "TFS_GIT_API_VERSION",
            "TFS_BUILD_API_VERSION",
        ]:
            raw_value = self._line(f"tfs.{key}").text().strip()
            if key in {"BUILD_DEFINITION_ID", "TFS_POLL_INTERVAL", "TFS_TIMEOUT_SECS"}:
                tfs_override[key] = int(raw_value) if raw_value else None
            else:
                tfs_override[key] = raw_value

        return {
            "enabled": self._checkbox("enabled").isChecked(),
            "code_path": self._line("code_path").text().strip(),
            "main_branch": self._line("main_branch").text().strip(),
            "versions": {
                "current": self._line("versions.current").text().strip(),
                "next": self._line("versions.next").text().strip(),
            },
            "change_log_path": self._line("change_log_path").text().strip(),
            "assembly_paths": self._split_lines(self._plain("assembly_paths").toPlainText()),
            "aip_paths": self._split_lines(self._plain("aip_paths").toPlainText()),
            "tfs": tfs_override,
        }

    def _line(self, key: str) -> QtWidgets.QLineEdit:
        return self.fields[key]  # type: ignore[return-value]

    def _plain(self, key: str) -> QtWidgets.QPlainTextEdit:
        return self.fields[key]  # type: ignore[return-value]

    def _checkbox(self, key: str) -> QtWidgets.QCheckBox:
        return self.fields[key]  # type: ignore[return-value]

    @staticmethod
    def _split_lines(raw_text: str) -> list[str]:
        return [line.strip() for line in raw_text.splitlines() if line.strip()]


class ConfigEditorWidget(QtWidgets.QWidget):
    config_saved = QtCore.Signal(str)
    config_save_failed = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.general_inputs: dict[str, QtWidgets.QWidget] = {}
        self.code_editors: dict[str, CodeEditorWidget] = {}

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 6)
        header_layout.setSpacing(12)
        title = QtWidgets.QLabel("Configuracion")
        title.setObjectName("sectionTitle")
        subtitle = QtWidgets.QLabel("Edita valores efectivos del build y guardalos en config_overrides.json.")
        subtitle.setObjectName("sectionSubtitle")
        subtitle.setWordWrap(True)
        title_box = QtWidgets.QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(8)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self.reload_button = QtWidgets.QPushButton("Recargar")
        self.save_button = QtWidgets.QPushButton("Guardar overrides")
        header_layout.addWidget(self.reload_button)
        header_layout.addWidget(self.save_button)
        root_layout.addLayout(header_layout)

        self.tabs = QtWidgets.QTabWidget()
        self.general_tab = QtWidgets.QScrollArea()
        self.general_tab.setWidgetResizable(True)
        self.codes_tab = QtWidgets.QWidget()
        self.code_selector = QtWidgets.QComboBox()
        self.code_editor_scroll = QtWidgets.QScrollArea()
        self.code_editor_scroll.setWidgetResizable(True)
        self._current_code_name = ""

        self.tabs.addTab(self.general_tab, "General")
        self.tabs.addTab(self.codes_tab, "Codigos")
        root_layout.addWidget(self.tabs)

        self._build_general_tab()
        self._build_codes_tab()
        self.reload_button.clicked.connect(self.reload_values)
        self.save_button.clicked.connect(self.save_values)
        self.code_selector.currentTextChanged.connect(self._show_selected_code)

        self.reload_values()

    def _build_general_tab(self) -> None:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(16)

        form_group = QtWidgets.QGroupBox("Valores generales")
        form_layout = QtWidgets.QFormLayout(form_group)
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(QtCore.Qt.AlignTop)
        form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setContentsMargins(16, 20, 16, 16)

        for field in GENERAL_FIELDS:
            widget: QtWidgets.QWidget
            if field["multiline"]:
                widget = QtWidgets.QPlainTextEdit()
                widget.setMinimumHeight(110)
            else:
                widget = QtWidgets.QLineEdit()
                widget.setMinimumHeight(34)
            self.general_inputs[field["name"]] = widget
            form_layout.addRow(_create_help_label(field["label"], field["help"]), widget)

        layout.addWidget(form_group)
        layout.addStretch(1)
        self.general_tab.setWidget(container)

    def _build_codes_tab(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.codes_tab)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(16)

        header = QtWidgets.QGroupBox("Codigo seleccionado")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 16, 16)
        header_layout.setSpacing(12)
        header_layout.addWidget(_create_help_label("Codigo", "Selecciona el codigo que quieres editar."))
        header_layout.addWidget(self.code_selector, 1)

        layout.addWidget(header)
        layout.addWidget(self.code_editor_scroll, 1)

    def reload_values(self) -> None:
        global config_module
        config_module = importlib.reload(config_module)

        for field in GENERAL_FIELDS:
            value = getattr(config_module, field["name"], "")
            widget = self.general_inputs[field["name"]]
            if field["multiline"]:
                widget.setPlainText(str(value))  # type: ignore[attr-defined]
            else:
                widget.setText(str(value))  # type: ignore[attr-defined]

        self.code_editors.clear()
        self.code_selector.blockSignals(True)
        self.code_selector.clear()

        for code_name, code_data in config_module.CODES.items():
            editor = CodeEditorWidget(code_name)
            editor.load_data(code_data)
            self.code_editors[code_name] = editor
            self.code_selector.addItem(code_name)

        self.code_selector.blockSignals(False)
        if self.code_selector.count():
            index = self.code_selector.findText(self._current_code_name)
            self.code_selector.setCurrentIndex(index if index >= 0 else 0)
            self._show_selected_code(self.code_selector.currentText())
        else:
            self.code_editor_scroll.takeWidget()

    def save_values(self) -> None:
        try:
            payload = self._build_override_payload()
            CONFIG_OVERRIDES_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            self.config_save_failed.emit(str(exc))
            return
        self.config_saved.emit(str(CONFIG_OVERRIDES_PATH))

    def _build_override_payload(self) -> dict:
        payload: dict[str, object] = {}
        for field in GENERAL_FIELDS:
            widget = self.general_inputs[field["name"]]
            if field["multiline"]:
                payload[field["name"]] = widget.toPlainText().strip()  # type: ignore[attr-defined]
            else:
                payload[field["name"]] = widget.text().strip()  # type: ignore[attr-defined]

        payload["CODES"] = {code_name: editor.build_override() for code_name, editor in self.code_editors.items()}
        return payload

    def _show_selected_code(self, code_name: str) -> None:
        self._current_code_name = code_name
        current_widget = self.code_editor_scroll.takeWidget()
        if current_widget is not None:
            current_widget.setParent(None)
        editor = self.code_editors.get(code_name)
        if editor is not None:
            self.code_editor_scroll.setWidget(editor)


class MainWindow(QtWidgets.QMainWindow):
    run_actions_requested = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1500, 860)

        self._running = False
        self._review_pending = False
        self._last_issues: list[dict] = []
        self.log_window = LogWindow(self)
        self.config_editor = ConfigEditorWidget()
        self.config_window = ConfigWindow(self.config_editor, self)
        self.health_window = EnvironmentHealthWindow(self)
        self.health_window.loading_changed.connect(self._set_health_button_loading)
        self.health_window.loading_text_changed.connect(self._set_health_button_text)

        self._setup_logging_bridge()
        self._build_ui()
        self._apply_styles()
        self._build_worker()

    def _setup_logging_bridge(self) -> None:
        self.log_emitter = LogEmitter()
        self.log_handler = QtLogHandler(self.log_emitter)
        self.log_emitter.message.connect(self._append_log)
        root_logger = logging.getLogger()
        if not any(isinstance(handler, QtLogHandler) for handler in root_logger.handlers):
            root_logger.addHandler(self.log_handler)

    def _build_worker(self) -> None:
        self.worker_thread = QtCore.QThread(self)
        self.worker = PipelineWorker()
        self.worker.moveToThread(self.worker_thread)
        self.run_actions_requested.connect(self.worker.run_actions)
        self.worker.step_changed.connect(self._on_step_changed)
        self.worker.review_required.connect(self._on_review_required)
        self.worker.review_cleared.connect(self._on_review_cleared)
        self.worker.execution_finished.connect(self._on_execution_finished)
        self.worker_thread.start()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)

        header_layout = QtWidgets.QHBoxLayout()
        title_box = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel(APP_TITLE)
        title.setObjectName("windowTitle")
        title_box.addWidget(title)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self.run_all_button = QtWidgets.QPushButton("Ejecutar flujo completo")
        self.reset_button = QtWidgets.QPushButton("Reiniciar estados")
        self.health_button = QtWidgets.QPushButton("Salud del entorno")
        self.config_button = QtWidgets.QPushButton("Configuracion")
        self.logs_button = QtWidgets.QPushButton("Ver logs")
        header_layout.addWidget(self.logs_button)
        header_layout.addWidget(self.health_button)
        header_layout.addWidget(self.config_button)
        header_layout.addWidget(self.reset_button)
        header_layout.addWidget(self.run_all_button)
        root_layout.addLayout(header_layout)

        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        main_splitter.setChildrenCollapsible(False)
        root_layout.addWidget(main_splitter, 1)

        pipeline_panel = QtWidgets.QWidget()
        pipeline_layout = QtWidgets.QVBoxLayout(pipeline_panel)
        pipeline_layout.setContentsMargins(0, 0, 0, 0)
        pipeline_layout.setSpacing(10)
        pipeline_intro = QtWidgets.QLabel("Flujo")
        pipeline_intro.setObjectName("sectionTitle")
        pipeline_layout.addWidget(pipeline_intro)

        self.step_cards: dict[str, StepCard] = {}
        ordered_actions = list(Accion)
        for action in ordered_actions:
            card = StepCard(action)
            card.run_requested.connect(self._run_single_action)
            self.step_cards[action.value] = card
        self.pipeline_board = PipelineBoard()
        self.pipeline_board.set_cards(ordered_actions, self.step_cards)
        pipeline_layout.addWidget(self.pipeline_board, 1)
        main_splitter.addWidget(pipeline_panel)

        review_tab = QtWidgets.QWidget()
        review_layout = QtWidgets.QVBoxLayout(review_tab)
        review_layout.setContentsMargins(12, 12, 12, 12)
        review_layout.setSpacing(12)
        self.review_summary = QtWidgets.QLabel("No hay revisiones pendientes.")
        self.review_summary.setWordWrap(True)
        self.review_summary.setObjectName("reviewSummary")
        review_layout.addWidget(self.review_summary)

        self.review_table = QtWidgets.QTableWidget(0, 4)
        self.review_table.setHorizontalHeaderLabels(["Key", "Resumen", "Responsable", "Link"])
        self.review_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.review_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.review_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.review_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.review_table.verticalHeader().setVisible(False)
        self.review_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.review_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        review_layout.addWidget(self.review_table, 1)

        review_actions = QtWidgets.QHBoxLayout()
        review_actions.addStretch(1)
        self.review_restart_button = QtWidgets.QPushButton("Reiniciar paso")
        self.review_ok_button = QtWidgets.QPushButton("Aceptar")
        self.review_force_button = QtWidgets.QPushButton("Avanzar igual")
        review_actions.addWidget(self.review_restart_button)
        review_actions.addWidget(self.review_ok_button)
        review_actions.addWidget(self.review_force_button)
        review_layout.addLayout(review_actions)
        main_splitter.addWidget(review_tab)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 3)

        self.statusBar().showMessage("Listo")
        self._set_review_controls_enabled(False)

        self.run_all_button.clicked.connect(self._run_all_actions)
        self.reset_button.clicked.connect(self._reset_statuses)
        self.logs_button.clicked.connect(self._show_logs_window)
        self.health_button.clicked.connect(self._show_health_window)
        self.config_button.clicked.connect(self._show_config_window)
        self.review_ok_button.clicked.connect(lambda: self._submit_review_decision("ok"))
        self.review_force_button.clicked.connect(lambda: self._submit_review_decision("force"))
        self.review_restart_button.clicked.connect(lambda: self._submit_review_decision("restart"))
        self.config_editor.config_saved.connect(self._on_config_saved)
        self.config_editor.config_save_failed.connect(self._on_config_save_failed)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f6f8fb; color: #18212f; font-family: "Segoe UI"; font-size: 10pt; }
            QLabel#windowTitle { font-size: 21pt; font-weight: 700; color: #0f172a; }
            QLabel#sectionTitle { font-size: 16pt; font-weight: 700; color: #0f172a; }
            QLabel#sectionSubtitle { color: #526077; }
            QFrame#stepCard {
                background: transparent;
                border: none;
            }
            QGroupBox, QScrollArea {
                background: white;
                border: 1px solid #d9e4ef;
                border-radius: 5px;
            }
            QTabWidget::pane {
                border: 1px solid #d9e4ef;
                border-radius: 5px;
                background: #ffffff;
                margin-top: 8px;
                padding-top: 8px;
            }
            QTabBar::tab {
                background: #f4f7fb;
                border: 1px solid #d9e4ef;
                border-bottom: none;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                padding: 8px 14px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f172a;
            }
            QGraphicsView#pipelineBoard {
                background: #eef3f9;
                border: 1px solid #dce3ef;
                border-radius: 18px;
            }
            QLabel#stepTitle {
                font-size: 10.8pt;
                font-weight: 700;
                color: #0f172a;
                letter-spacing: 0.2px;
                line-height: 1.2;
            }
            QLabel#stepMessage {
                color: #334155;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 5px;
                padding: 7px;
                font-size: 8.5pt;
                font-weight: 600;
            }
            QLabel#dragHandle {
                color: #94a3b8;
                letter-spacing: 1px;
                font-weight: 700;
                padding-right: 2px;
            }
            QLabel#statusBadge {
                padding-top: 0px;
                padding-bottom: 0px;
            }
            QPushButton {
                background: #f8fafc;
                color: #1e293b;
                border: 1px solid #d7e0ea;
                border-radius: 5px;
                padding: 7px 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: #eef3f8; }
            QPushButton:disabled { background: #f2f5f8; color: #9aa8ba; border-color: #e2e8f0; }
            QPushButton#nodeButton {
                background: #eff6ff;
                border: 1px solid #c9daf3;
                color: #1d4ed8;
                padding: 6px 10px;
                border-radius: 5px;
            }
            QPushButton#nodeButton:hover {
                background: #e0efff;
            }
            QToolButton { background: #e0ecff; color: #1d4ed8; border-radius: 10px; border: none; font-weight: 700; }
            QToolButton#nodeHelpButton {
                background: #dbeafe;
                color: #1d4ed8;
                border: 1px solid #93c5fd;
                border-radius: 11px;
                padding: 0px;
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                font-size: 10pt;
                font-weight: 700;
                qproperty-autoRaise: 0;
            }
            QToolButton#nodeHelpButton:hover {
                background: #bfdbfe;
                border-color: #60a5fa;
            }
            QPlainTextEdit, QLineEdit { border: 1px solid #cad5e3; border-radius: 10px; padding: 8px; background: white; }
            QComboBox {
                border: 1px solid #cad5e3;
                border-radius: 10px;
                padding: 8px 10px;
                background: white;
                min-height: 34px;
            }
            QGroupBox { font-weight: 700; margin-top: 10px; padding-top: 18px; }
            QHeaderView::section { background: #f4f6fb; border: none; border-bottom: 1px solid #dde4ef; padding: 8px; font-weight: 700; }
            QLabel#reviewSummary { background: #fff7ed; color: #9a3412; border: 1px solid #fed7aa; border-radius: 10px; padding: 10px 12px; }
            QLabel#healthSummary { background: #eef6ff; color: #1d4f91; border: 1px solid #cfe0fb; border-radius: 10px; padding: 10px 12px; }
            QFormLayout { margin-top: 8px; }
            """
        )

    def _run_all_actions(self) -> None:
        self._start_execution([action.value for action in Accion], reset_all=True)

    def _run_single_action(self, action_value: str) -> None:
        self._start_execution([action_value], reset_all=False)

    def _start_execution(self, action_values: list[str], *, reset_all: bool) -> None:
        if self._running:
            return
        if reset_all:
            self._reset_statuses()
        else:
            for action_value in action_values:
                if action_value in self.step_cards:
                    self.step_cards[action_value].set_status("pending", "En cola")

        self._running = True
        self._set_run_controls(False)
        self._set_review_controls_enabled(False)
        self.statusBar().showMessage("Ejecutando flujo...")
        self.run_actions_requested.emit(action_values)

    def _reset_statuses(self) -> None:
        for card in self.step_cards.values():
            card.set_status("pending", "Sin ejecutar")
        self.review_summary.setText("No hay revisiones pendientes.")
        self.review_table.setRowCount(0)
        self._set_review_controls_enabled(False)
        self._last_issues = []

    def _set_run_controls(self, enabled: bool) -> None:
        self.run_all_button.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)
        for card in self.step_cards.values():
            card.set_enabled_for_run(enabled)

    def _set_review_controls_enabled(self, enabled: bool) -> None:
        self.review_ok_button.setEnabled(enabled)
        self.review_force_button.setEnabled(enabled)
        self.review_restart_button.setEnabled(enabled)
        self._review_pending = enabled

    def _append_log(self, message: str) -> None:
        self.log_window.append_log(message)

    def _show_logs_window(self) -> None:
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def _show_config_window(self) -> None:
        self.config_window.show()
        self.config_window.raise_()
        self.config_window.activateWindow()

    def _show_health_window(self) -> None:
        self.health_window.refresh_checks()
        self.health_window.show()
        self.health_window.raise_()
        self.health_window.activateWindow()

    def _set_health_button_loading(self, loading: bool) -> None:
        self.health_button.setEnabled(not loading)

    def _set_health_button_text(self, text: str) -> None:
        self.health_button.setText(text)

    def _on_step_changed(self, action_value: str, status: str, message: str) -> None:
        if action_value in self.step_cards:
            self.step_cards[action_value].set_status(status, message)
        if status == "waiting":
            self.statusBar().showMessage(message)

    def _on_review_required(self, issues: object) -> None:
        self._last_issues = list(issues or [])
        self.review_summary.setText(
            f"El paso GET_JIRA_ISSUES requiere intervencion manual. Se detectaron {len(self._last_issues)} jiras para revisar."
        )
        self._populate_review_table(self._last_issues)
        self._set_review_controls_enabled(True)
        self.statusBar().showMessage("Esperando decision manual")

    def _on_review_cleared(self) -> None:
        self._set_review_controls_enabled(False)
        self.review_summary.setText("No hay revisiones pendientes.")
        self.review_table.setRowCount(0)
        self._last_issues = []

    def _submit_review_decision(self, decision: str) -> None:
        if not self._review_pending:
            return
        self._set_review_controls_enabled(False)
        self.statusBar().showMessage(f"Decision enviada: {decision}")
        self.worker.submit_decision(decision)

    def _populate_review_table(self, issues: list[dict]) -> None:
        self.review_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            key = str(issue.get("key") or "")
            link = str(issue.get("link") or "")
            summary = str(issue.get("summary") or "")
            assignee = str(issue.get("assignee_name") or "")

            key_label = QtWidgets.QLabel(f'<a href="{link}">{key}</a>' if link else key)
            key_label.setOpenExternalLinks(True)
            self.review_table.setCellWidget(row, 0, key_label)
            self.review_table.setItem(row, 1, QtWidgets.QTableWidgetItem(summary))
            self.review_table.setItem(row, 2, QtWidgets.QTableWidgetItem(assignee))
            link_label = QtWidgets.QLabel(f'<a href="{link}">{link}</a>' if link else "-")
            link_label.setOpenExternalLinks(True)
            self.review_table.setCellWidget(row, 3, link_label)

    def _on_execution_finished(self, success: bool, message: str) -> None:
        self._running = False
        self._set_run_controls(True)
        self._set_review_controls_enabled(False)
        self.statusBar().showMessage(message if success else f"Error: {message}")
        if not success:
            QtWidgets.QMessageBox.critical(self, "Error de ejecucion", message)

    def _on_config_saved(self, path: str) -> None:
        self.statusBar().showMessage(f"Overrides guardados en {path}")
        QtWidgets.QMessageBox.information(
            self,
            "Configuracion guardada",
            f"Los cambios quedaron guardados en:\n{path}\n\nSe aplicaran en la proxima ejecucion que lances desde la app.",
        )

    def _on_config_save_failed(self, error_message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Error al guardar", error_message)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.worker_thread.quit()
        self.worker_thread.wait(3000)
        super().closeEvent(event)


def launch() -> int:
    setup_logging()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch())
