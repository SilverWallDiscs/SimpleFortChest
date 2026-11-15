from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QObject, Signal, QSize, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from probability import (
    BASE_TOKEN_DENOMINATOR, REWARD_ODDS, chance_at_least_one,
    chests_for_chance, mixed_chance, per_chest_probability,
)

try:
    from pynput import keyboard as pynput_keyboard
except Exception:
    pynput_keyboard = None


APP_VERSION = "1.0.0"
MODES = {
    "normal": {"label": "Normal", "multiplier": 1.0, "denominator": 137_500},
    "boost_15": {"label": "Treasure Hour · 1,5×", "multiplier": 1.5, "denominator": 91_667},
    "boost_2": {"label": "Sesión anunciada · 2×", "multiplier": 2.0, "denominator": 68_750},
}
MODE_MULTIPLIERS = {key: value["multiplier"] for key, value in MODES.items()}
HOTKEYS = ["F6", "F7", "F8", "F9", "F10", "F11", "F12", "PAUSE", "SCROLL_LOCK"]
SOURCE_URL = (
    "https://www.epicgames.com/help/c-34254770/c-33726977/"
    "what-are-the-drop-rates-of-treasure-in-chests-in-fortnite-battle-royale-s-pirate-treasure-event-a14361627"
)


def data_directory() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        folder = Path(root) / "SimpleFortChest"
    else:
        folder = Path.home() / "AppData" / "Local" / "SimpleFortChest"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fresh_ledger() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "counts": {"normal": 0, "boost_15": 0, "boost_2": 0},
        "hotkey": "F8",
        "active_mode": "normal",
        "team_size": 4,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_ledger(raw: Any) -> dict[str, Any]:
    """Validate imported JSON and normalize older/simple counter documents."""
    if not isinstance(raw, dict):
        raise ValueError("El documento no contiene un objeto JSON válido.")

    result = fresh_ledger()
    source_counts = raw.get("counts")
    if isinstance(source_counts, dict):
        for mode in MODES:
            value = source_counts.get(mode, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"El contador «{mode}» no es un entero válido.")
            result["counts"][mode] = min(value, 2_000_000_000)
    elif "total_chests" in raw:
        total = raw["total_chests"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("El total de cofres no es válido.")
        result["counts"]["normal"] = min(total, 2_000_000_000)

    hotkey = raw.get("hotkey", "F8")
    if hotkey in HOTKEYS:
        result["hotkey"] = hotkey
    active_mode = raw.get("active_mode", "normal")
    if active_mode in MODES:
        result["active_mode"] = active_mode
    team_size = raw.get("team_size", 4)
    if isinstance(team_size, int) and not isinstance(team_size, bool) and team_size in (1, 2, 3, 4):
        result["team_size"] = team_size
    result["updated_at"] = raw.get("updated_at") or datetime.now(timezone.utc).isoformat()
    return result


class HotkeyBridge(QObject):
    chest_pressed = Signal()


class GlobalHotkey:
    """Listens globally so the counter also works while Fortnite is in the foreground."""

    def __init__(self, key_name: str, callback) -> None:
        self.key_name = key_name
        self.callback = callback
        self.listener = None
        self.held = False
        self.last_press = 0.0
        self.error: str | None = None

    def _matches(self, key) -> bool:
        if pynput_keyboard is None:
            return False
        key_enum = getattr(pynput_keyboard.Key, self.key_name.lower(), None)
        if key_enum is not None and key == key_enum:
            return True
        char = getattr(key, "char", None)
        return bool(char and char.upper() == self.key_name)

    def _on_press(self, key) -> None:
        if not self._matches(key):
            return
        now = time.monotonic()
        if not self.held and now - self.last_press > 0.18:
            self.callback()
        self.held = True
        self.last_press = now

    def _on_release(self, key) -> None:
        if self._matches(key):
            self.held = False

    def start(self) -> bool:
        self.stop()
        if pynput_keyboard is None:
            self.error = "No se pudo cargar pynput. Reinstala las dependencias."
            return False
        try:
            self.held = False
            self.listener = pynput_keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release
            )
            self.listener.daemon = True
            self.listener.start()
            self.error = None
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    def stop(self) -> None:
        if self.listener is not None:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SimpleFortChest · Bitácora del Capitán")
        self.setMinimumSize(QSize(960, 700))
        self.resize(1180, 820)
        self.file_path = data_directory() / "chests.json"
        self.ledger = fresh_ledger()
        self.bridge = HotkeyBridge(self)
        self.bridge.chest_pressed.connect(self.add_one)
        self.hotkey_listener: GlobalHotkey | None = None
        self.status_message = "Bitácora lista. ¡A la caza del tesoro!"
        self._build_ui()
        self._load_startup_file()
        self._restart_hotkey()
        self.refresh_view()

    def _build_ui(self) -> None:
        self.setStyleSheet(STYLE)
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(238)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 20, 18, 18)
        side.setSpacing(12)

        crest = QLabel("⚓")
        crest.setObjectName("Crest")
        crest.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(crest)
        brand = QLabel("SIMPLE\nFORTCHEST")
        brand.setObjectName("Brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(brand)
        subtitle = QLabel("LA BITÁCORA DEL CAPITÁN")
        subtitle.setObjectName("SideEyebrow")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(subtitle)
        self._add_divider(side)

        side.addWidget(self._side_label("TECLA GLOBAL"))
        hotkey_row = QHBoxLayout()
        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItems(HOTKEYS)
        self.hotkey_combo.setCurrentText("F8")
        self.hotkey_combo.currentTextChanged.connect(self.change_hotkey)
        hotkey_row.addWidget(self.hotkey_combo)
        side.addLayout(hotkey_row)
        hotkey_help = QLabel("Cuenta incluso con Fortnite en primer plano.")
        hotkey_help.setObjectName("Muted")
        hotkey_help.setWordWrap(True)
        side.addWidget(hotkey_help)

        self._add_divider(side)
        side.addWidget(self._side_label("DOCUMENTO"))
        self._side_button(side, "Guardar ahora", self.save_now, "GoldButton")
        self._side_button(side, "Exportar bitácora .json", self.export_json)
        self._side_button(side, "Importar bitácora .json", self.import_json)
        self._side_button(side, "Abrir carpeta de guardado", self.open_data_folder)
        side.addStretch(1)
        self.status_label = QLabel("Guardado automático activado")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        side.addWidget(self.status_label)
        self._side_button(side, "Reiniciar contador", self.reset_counter, "DangerButton")
        version = QLabel(f"VERSIÓN {APP_VERSION}  ·  WINDOWS")
        version.setObjectName("SideEyebrow")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(version)

        main = QVBoxLayout()
        main.setSpacing(14)
        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        heading = QLabel("BITÁCORA DEL CAPITÁN")
        heading.setObjectName("PageTitle")
        title_stack.addWidget(heading)
        intro = QLabel("Cuenta tus cofres, consulta las probabilidades y sigue el rastro del token.")
        intro.setObjectName("Muted")
        title_stack.addWidget(intro)
        header.addLayout(title_stack)
        header.addStretch(1)
        self.save_pill = QLabel("●  AUTOGUARDADO")
        self.save_pill.setObjectName("SavePill")
        header.addWidget(self.save_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        main.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 4, 8, 10)
        content_layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        counter_card, counter = self._card("TU BOTÍN", "Todos los cofres que has registrado")
        self.total_label = QLabel("0")
        self.total_label.setObjectName("BigNumber")
        counter.addWidget(self.total_label)
        self.breakdown_label = QLabel("0 normales  ·  0 con boost 1,5×  ·  0 con boost 2×")
        self.breakdown_label.setObjectName("Muted")
        counter.addWidget(self.breakdown_label)
        buttons = QHBoxLayout()
        self.minus_button = QPushButton("− 1")
        self.minus_button.setObjectName("SecondaryButton")
        self.minus_button.clicked.connect(self.subtract_one)
        buttons.addWidget(self.minus_button)
        one_button = QPushButton("+ 1 COFRE")
        one_button.setObjectName("GoldButton")
        one_button.clicked.connect(self.add_one)
        buttons.addWidget(one_button, 2)
        ten_button = QPushButton("+ 10")
        ten_button.setObjectName("SecondaryButton")
        ten_button.clicked.connect(lambda: self.add_chests(10))
        buttons.addWidget(ten_button)
        counter.addLayout(buttons)
        edit_row = QHBoxLayout()
        self.manual_total = QLineEdit()
        self.manual_total.setPlaceholderText("Ajustar total manualmente…")
        self.manual_total.setValidator(None)
        self.manual_total.returnPressed.connect(self.apply_manual_total)
        edit_row.addWidget(self.manual_total, 2)
        edit_button = QPushButton("APLICAR")
        edit_button.setObjectName("SecondaryButton")
        edit_button.clicked.connect(self.apply_manual_total)
        edit_row.addWidget(edit_button)
        counter.addLayout(edit_row)
        manual_note = QLabel("Al editar el total, el historial se reorganiza como cofres normales.")
        manual_note.setObjectName("TinyNote")
        manual_note.setWordWrap(True)
        counter.addWidget(manual_note)
        top_row.addWidget(counter_card, 3)

        odds_card, odds = self._card("EL PRÓXIMO COFRE", "La tirada individual no recuerda tus intentos anteriores")
        mode_label = QLabel("TIPO DE SESIÓN")
        mode_label.setObjectName("FieldLabel")
        odds.addWidget(mode_label)
        self.mode_combo = QComboBox()
        for key, details in MODES.items():
            self.mode_combo.addItem(details["label"], key)
        self.mode_combo.currentIndexChanged.connect(self.change_mode)
        odds.addWidget(self.mode_combo)
        self.next_denominator = QLabel("1 entre 137.500")
        self.next_denominator.setObjectName("OddsNumber")
        odds.addWidget(self.next_denominator)
        self.next_percent = QLabel("0,000727 % por cofre")
        self.next_percent.setObjectName("GoldText")
        odds.addWidget(self.next_percent)
        self.next_explainer = QLabel("La probabilidad del siguiente cofre.")
        self.next_explainer.setObjectName("Muted")
        odds.addWidget(self.next_explainer)
        self.mode_note = QLabel("El multiplicador se aplica solo a los cofres que abras durante esa ventana.")
        self.mode_note.setObjectName("TinyNote")
        self.mode_note.setWordWrap(True)
        odds.addWidget(self.mode_note)
        top_row.addWidget(odds_card, 2)
        content_layout.addLayout(top_row)

        middle_row = QHBoxLayout()
        middle_row.setSpacing(14)
        progress_card, progress = self._card("TU TRAVESÍA", "Probabilidad acumulada según tu registro")
        self.cumulative_label = QLabel("0,0000 %")
        self.cumulative_label.setObjectName("OddsNumber")
        progress.addWidget(self.cumulative_label)
        self.cumulative_detail = QLabel("Probabilidad estimada de haber encontrado al menos un token.")
        self.cumulative_detail.setObjectName("Muted")
        self.cumulative_detail.setWordWrap(True)
        progress.addWidget(self.cumulative_detail)
        self.team_row = QHBoxLayout()
        team_caption = QLabel("TAMAÑO DE LA TRIPULACIÓN")
        team_caption.setObjectName("FieldLabel")
        self.team_row.addWidget(team_caption)
        self.team_combo = QComboBox()
        for size, label in ((1, "Solo"), (2, "Dúo"), (3, "Trío"), (4, "Escuadra ×4")):
            self.team_combo.addItem(label, size)
        self.team_combo.currentIndexChanged.connect(self.change_team_size)
        self.team_row.addWidget(self.team_combo)
        self.team_row.addStretch(1)
        progress.addLayout(self.team_row)
        self.team_chance_label = QLabel("Escuadra: 0,0000 %")
        self.team_chance_label.setObjectName("GoldText")
        progress.addWidget(self.team_chance_label)
        self.team_note = QLabel("Estimación si cada integrante abre una cantidad parecida de cofres y el token se comparte con el grupo.")
        self.team_note.setObjectName("TinyNote")
        self.team_note.setWordWrap(True)
        progress.addWidget(self.team_note)
        self.milestone_label = QLabel("50 %: 95.308 cofres  ·  90 %: 316.605 cofres")
        self.milestone_label.setObjectName("Milestone")
        progress.addWidget(self.milestone_label)
        middle_row.addWidget(progress_card, 3)

        advice_card, advice = self._card("CONSEJOS DE CORSARIO", "Lo que conviene saber antes de lanzarte al mar")
        tips = [
            ("⚓", "Cualquier cofre cuenta", "Normales, raros, Sprite, enterrados y otros cofres de Battle Royale / Zero Build."),
            ("☠", "La tripulación comparte", "Los reportes indican que si un integrante encuentra Pirate Shop Access, también lo recibe el resto del grupo."),
            ("🧭", "No existe una racha afortunada", "Ni una skin, ubicación o cofre especial tiene una mejora confirmada. Cada intento es independiente."),
        ]
        for icon, title_text, body_text in tips:
            row = QHBoxLayout()
            icon_label = QLabel(icon)
            icon_label.setObjectName("TipIcon")
            icon_label.setFixedWidth(30)
            row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
            stack = QVBoxLayout()
            t = QLabel(title_text)
            t.setObjectName("TipTitle")
            stack.addWidget(t)
            b = QLabel(body_text)
            b.setObjectName("TinyNote")
            b.setWordWrap(True)
            stack.addWidget(b)
            row.addLayout(stack, 1)
            advice.addLayout(row)
        middle_row.addWidget(advice_card, 2)
        content_layout.addLayout(middle_row)

        rewards_card, rewards = self._card("EL LIBRO DEL TESORO", "Probabilidades oficiales por cofre en una partida normal")
        self.reward_table = QTableWidget(len(REWARD_ODDS), 3)
        self.reward_table.setHorizontalHeaderLabels(["RECOMPENSA", "PROBABILIDAD", "% POR COFRE"])
        self.reward_table.verticalHeader().setVisible(False)
        self.reward_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.reward_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.reward_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reward_table.setShowGrid(False)
        self.reward_table.setAlternatingRowColors(True)
        self.reward_table.setMinimumHeight(250)
        self.reward_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.reward_table.horizontalHeader().setStretchLastSection(True)
        self.reward_table.horizontalHeader().setSectionResizeMode(0, self.reward_table.horizontalHeader().ResizeMode.Stretch)
        for column in (1, 2):
            self.reward_table.setColumnWidth(column, 150)
        for row, (name, denominator) in enumerate(REWARD_ODDS):
            name_item = QTableWidgetItem(name)
            odds_item = QTableWidgetItem(f"1 : {denominator:,}".replace(",", "."))
            percent_item = QTableWidgetItem(f"{(100 / denominator):.6f} %".replace(".", ","))
            odds_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            percent_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if row == 0:
                name_item.setText("🏴‍☠️  " + name + "  ·  OBJETIVO")
            self.reward_table.setItem(row, 0, name_item)
            self.reward_table.setItem(row, 1, odds_item)
            self.reward_table.setItem(row, 2, percent_item)
            self.reward_table.setRowHeight(row, 32)
        rewards.addWidget(self.reward_table)
        boost_note = QLabel("Treasure Hours también aumentan ciertas recompensas: el token 1,5×, el atuendo dorado 7,5× y el vehículo 10× en la sesión estándar anunciada. Los eventos concretos pueden variar.")
        boost_note.setObjectName("TinyNote")
        boost_note.setWordWrap(True)
        rewards.addWidget(boost_note)
        content_layout.addWidget(rewards_card)

        footer = QLabel("DATOS LOCALES · SIN CONEXIÓN A TU CUENTA EPIC · SIN LEER NI MODIFICAR EL JUEGO")
        footer.setObjectName("FooterNote")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(footer)
        scroll.setWidget(content)
        main.addWidget(scroll, 1)

        root_layout.addWidget(sidebar)
        root_layout.addLayout(main, 1)
        self.setCentralWidget(root)

    def _side_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _side_button(self, layout: QVBoxLayout, text: str, callback, style: str = "SecondaryButton") -> None:
        button = QPushButton(text)
        button.setObjectName(style)
        button.setMinimumHeight(38)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def _add_divider(self, layout: QVBoxLayout) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("Divider")
        layout.addWidget(line)

    def _card(self, title: str, caption: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        eyebrow = QLabel(title)
        eyebrow.setObjectName("CardTitle")
        layout.addWidget(eyebrow)
        desc = QLabel(caption)
        desc.setObjectName("TinyNote")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        return frame, layout

    def _load_startup_file(self) -> None:
        if not self.file_path.exists():
            self.save_data()
            self.status_message = "Nueva bitácora creada en este equipo."
            return
        try:
            with self.file_path.open("r", encoding="utf-8") as stream:
                self.ledger = normalize_ledger(json.load(stream))
            self.status_message = "Bitácora anterior recuperada correctamente."
        except Exception as exc:
            self.ledger = fresh_ledger()
            self.status_message = f"No se pudo leer la bitácora: {exc}"
        self._sync_controls_from_ledger()

    def _sync_controls_from_ledger(self) -> None:
        self.hotkey_combo.blockSignals(True)
        self.hotkey_combo.setCurrentText(self.ledger.get("hotkey", "F8"))
        self.hotkey_combo.blockSignals(False)
        self.mode_combo.blockSignals(True)
        index = self.mode_combo.findData(self.ledger.get("active_mode", "normal"))
        self.mode_combo.setCurrentIndex(max(index, 0))
        self.mode_combo.blockSignals(False)
        self.team_combo.blockSignals(True)
        team_index = self.team_combo.findData(self.ledger.get("team_size", 4))
        self.team_combo.setCurrentIndex(max(team_index, 0))
        self.team_combo.blockSignals(False)

    def save_data(self) -> None:
        self.ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.ledger["hotkey"] = self.hotkey_combo.currentText() if hasattr(self, "hotkey_combo") else "F8"
        self.ledger["active_mode"] = self.mode_combo.currentData() if hasattr(self, "mode_combo") else "normal"
        self.ledger["team_size"] = self.team_combo.currentData() if hasattr(self, "team_combo") else 4
        temporary = self.file_path.with_suffix(".json.tmp")
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.ledger, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.file_path)
            if hasattr(self, "save_pill"):
                self.save_pill.setText("●  AUTOGUARDADO")
            return
        except Exception as exc:
            if hasattr(self, "status_label"):
                self.status_label.setText(f"Error al guardar: {exc}")
            raise

    def save_now(self) -> None:
        try:
            self.save_data()
            self.status_message = f"Bitácora guardada en {self.file_path}"
            self.status_label.setText("¡Bitácora guardada, capitán!")
            self.save_pill.setText("●  GUARDADO")
        except Exception as exc:
            QMessageBox.critical(self, "Error al guardar", str(exc))

    def _total(self) -> int:
        return sum(self.ledger["counts"].values())

    def _active_mode(self) -> str:
        return self.mode_combo.currentData() or "normal"

    def add_one(self) -> None:
        self.add_chests(1)

    def add_chests(self, amount: int) -> None:
        mode = self._active_mode()
        current = self.ledger["counts"].get(mode, 0)
        self.ledger["counts"][mode] = min(2_000_000_000, current + amount)
        self.status_message = f"+{amount} cofre(s) registrados · {MODES[mode]['label']}"
        self._commit_change()

    def subtract_one(self) -> None:
        mode = self._active_mode()
        if self.ledger["counts"].get(mode, 0) <= 0:
            QMessageBox.information(
                self, "Nada que deshacer",
                "No hay cofres registrados en este tipo de sesión. Cambia el modo o ajusta el total manualmente."
            )
            return
        self.ledger["counts"][mode] -= 1
        self.status_message = "Se eliminó un cofre del modo seleccionado."
        self._commit_change()

    def apply_manual_total(self) -> None:
        raw = self.manual_total.text().strip().replace(".", "").replace(",", "")
        try:
            total = int(raw)
            if total < 0 or total > 2_000_000_000:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Cantidad no válida", "Introduce un número entero entre 0 y 2.000.000.000.")
            return
        boosted = self.ledger["counts"]["boost_15"] + self.ledger["counts"]["boost_2"]
        if total < boosted:
            answer = QMessageBox.question(
                self, "Reorganizar el historial",
                "El nuevo total es menor que los cofres registrados en sesiones potenciadas. "
                "Para aplicar el total, se reiniciará el desglose de boosts y todo quedará como cofre normal. ¿Continuar?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.ledger["counts"] = {"normal": total, "boost_15": 0, "boost_2": 0}
        else:
            self.ledger["counts"]["normal"] = total - boosted
        self.manual_total.clear()
        self.status_message = f"Total ajustado manualmente a {total:,} cofres.".replace(",", ".")
        self._commit_change()

    def change_mode(self) -> None:
        if not hasattr(self, "ledger"):
            return
        self.ledger["active_mode"] = self._active_mode()
        self.refresh_view()
        self._save_silently()

    def change_team_size(self) -> None:
        if not hasattr(self, "ledger"):
            return
        self.ledger["team_size"] = int(self.team_combo.currentData())
        self.refresh_view()
        self._save_silently()

    def change_hotkey(self, key_name: str) -> None:
        if not hasattr(self, "ledger"):
            return
        self.ledger["hotkey"] = key_name
        self._restart_hotkey()
        self._save_silently()

    def _restart_hotkey(self) -> None:
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        key = self.hotkey_combo.currentText() if hasattr(self, "hotkey_combo") else "F8"
        self.hotkey_listener = GlobalHotkey(key, self.bridge.chest_pressed.emit)
        active = self.hotkey_listener.start()
        if hasattr(self, "status_label"):
            if active:
                self.status_label.setText(f"Escuchando {key} globalmente.")
            else:
                self.status_label.setText(f"Tecla global no disponible: {self.hotkey_listener.error}")

    def _save_silently(self) -> None:
        try:
            self.save_data()
        except Exception:
            pass

    def _commit_change(self) -> None:
        try:
            self.save_data()
        except Exception:
            pass
        self.refresh_view()

    def _cumulative(self, party_multiplier: int = 1) -> float:
        counts = self.ledger["counts"]
        scaled = {key: value * party_multiplier for key, value in counts.items()}
        return mixed_chance(scaled, MODE_MULTIPLIERS)

    def refresh_view(self) -> None:
        if not hasattr(self, "total_label"):
            return
        counts = self.ledger["counts"]
        total = self._total()
        self.total_label.setText(f"{total:,}".replace(",", "."))
        self.breakdown_label.setText(
            f"{counts['normal']:,} normales  ·  {counts['boost_15']:,} con boost 1,5×  ·  {counts['boost_2']:,} con boost 2×".replace(",", ".")
        )
        mode = self._active_mode()
        details = MODES[mode]
        p = per_chest_probability(BASE_TOKEN_DENOMINATOR, details["multiplier"])
        self.next_denominator.setText(f"1 entre {round(1 / p):,}".replace(",", "."))
        self.next_percent.setText(f"{p * 100:.6f} %".replace(".", ","))
        self.mode_note.setText(f"Multiplicador activo: {details['multiplier']:.1f}×. Solo cuenta para los cofres que registres en este modo.".replace(".", ",") if details["multiplier"] != 1 else "Tasa normal oficial de Epic: 1 entre 137.500.")
        cumulative = self._cumulative()
        team_size = int(self.team_combo.currentData())
        team_chance = self._cumulative(team_size)
        self.cumulative_label.setText(f"{cumulative * 100:.6f} %".replace(".", ","))
        self.team_chance_label.setText(
            f"{'Solo tú' if team_size == 1 else f'Equipo ×{team_size}'}: {team_chance * 100:.6f} %".replace(".", ",")
        )
        self.cumulative_detail.setText(
            f"Modelo de intentos independientes sobre tus {total:,} cofres registrados. No predice cuándo llegará el token.".replace(",", ".")
        )
        self.milestone_label.setText(
            f"Referencia tasa normal · 50 %: {chests_for_chance(0.5):,} cofres  ·  90 %: {chests_for_chance(0.9):,}".replace(",", ".")
        )
        if hasattr(self, "status_label") and self.hotkey_listener:
            if self.hotkey_listener.error:
                self.status_label.setText(f"Tecla global no disponible: {self.hotkey_listener.error}")
            else:
                self.status_label.setText(f"Escuchando {self.hotkey_combo.currentText()} globalmente.\n{self.status_message}")
        if hasattr(self, "save_pill"):
            self.save_pill.setText("●  AUTOGUARDADO")

    def export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar bitácora", str(Path.home() / "SimpleFortChest-backup.json"),
            "Documento JSON (*.json)"
        )
        if not path:
            return
        try:
            self.save_data()
            Path(path).write_text(json.dumps(self.ledger, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_message = "Copia de seguridad exportada."
            self.status_label.setText(f"Exportado: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    def import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar bitácora", str(Path.home()), "Documento JSON (*.json)"
        )
        if not path:
            return
        try:
            loaded = normalize_ledger(json.loads(Path(path).read_text(encoding="utf-8")))
            answer = QMessageBox.question(
                self, "Reemplazar bitácora",
                "La importación reemplazará el contador y las preferencias actuales. ¿Continuar?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.ledger = loaded
            self._sync_controls_from_ledger()
            self._restart_hotkey()
            self.save_data()
            self.status_message = "Documento importado y guardado."
            self.refresh_view()
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo importar", str(exc))

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.file_path.parent)))

    def reset_counter(self) -> None:
        answer = QMessageBox.question(
            self, "¿Vaciar la bitácora?",
            "Se eliminarán todos los cofres registrados de este dispositivo. Esta acción no se puede deshacer."
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ledger["counts"] = {"normal": 0, "boost_15": 0, "boost_2": 0}
        self.status_message = "La bitácora está limpia. Nueva expedición."
        self._commit_change()

    def closeEvent(self, event) -> None:
        try:
            self.save_data()
        except Exception:
            pass
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        event.accept()


STYLE = """
QMainWindow, QWidget { background: #08121d; color: #e9dfcc; font-family: 'Segoe UI'; font-size: 10pt; }
QFrame#Sidebar { background: #0c1a29; border: 1px solid #263b50; border-radius: 17px; }
QFrame#Card { background: #101f30; border: 1px solid #29445d; border-radius: 16px; }
QLabel#Crest { color: #e4b85f; font-size: 40pt; padding: 1px; }
QLabel#Brand { color: #f2dfb7; font-size: 18pt; font-weight: 900; letter-spacing: 2px; }
QLabel#SideEyebrow, QLabel#FooterNote { color: #8da1b3; font-size: 7.5pt; font-weight: 800; letter-spacing: 1.4px; }
QLabel#PageTitle { color: #f0dfbf; font-size: 19pt; font-weight: 900; letter-spacing: 1px; }
QLabel#CardTitle { color: #e5bd70; font-size: 10pt; font-weight: 900; letter-spacing: 1.7px; }
QLabel#BigNumber { color: #f2d9a0; font-size: 48pt; font-weight: 900; }
QLabel#OddsNumber { color: #f5e3c0; font-size: 25pt; font-weight: 900; }
QLabel#GoldText { color: #edc56f; font-size: 11pt; font-weight: 800; }
QLabel#Muted { color: #9dafbf; font-size: 9pt; }
QLabel#TinyNote { color: #91a5b5; font-size: 8pt; }
QLabel#FieldLabel { color: #c8b994; font-size: 8pt; font-weight: 800; letter-spacing: 1px; }
QLabel#TipIcon { color: #e5bb6d; font-size: 17pt; }
QLabel#TipTitle { color: #ead9b8; font-size: 9pt; font-weight: 800; }
QLabel#Milestone { color: #e9c679; font-size: 9pt; font-weight: 800; padding-top: 7px; }
QLabel#StatusLabel { color: #c7d2cf; background: #142739; border: 1px solid #2c4b60; border-radius: 8px; padding: 9px; font-size: 8pt; }
QLabel#SavePill { color: #93c7a5; background: #142d2a; border: 1px solid #2b5649; border-radius: 10px; padding: 7px 11px; font-size: 8pt; font-weight: 800; }
QPushButton { border: 1px solid #344d65; border-radius: 9px; padding: 9px 12px; color: #e9dfcc; background: #1a2c40; font-weight: 800; }
QPushButton:hover { background: #263e56; border-color: #d2a858; }
QPushButton:pressed { background: #102030; }
QPushButton#GoldButton { color: #14202a; background: #ddb45e; border: 1px solid #f0d18c; font-weight: 900; }
QPushButton#GoldButton:hover { background: #f0ca79; }
QPushButton#DangerButton { color: #e7a9a0; background: #30202a; border: 1px solid #70404a; }
QPushButton#DangerButton:hover { background: #482832; }
QPushButton#SecondaryButton { background: #1a3044; }
QComboBox, QLineEdit { color: #eee3d1; background: #0c1a28; border: 1px solid #38516a; border-radius: 8px; padding: 8px 10px; selection-background-color: #b98d47; min-height: 20px; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { color: #eee3d1; background: #13263a; selection-background-color: #755c32; border: 1px solid #38516a; }
QFrame#Divider { color: #294156; max-height: 1px; border: 0; background: #294156; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 9px; background: #0b1825; margin: 2px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #43566a; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTableWidget { background: #0c1a28; alternate-background-color: #112235; color: #e5ddcd; border: 1px solid #2a4157; border-radius: 8px; gridline-color: transparent; }
QHeaderView::section { background: #192e41; color: #d9bd83; border: none; padding: 8px; font-size: 8pt; font-weight: 900; }
QTableWidget::item { padding: 4px 7px; border: none; }
"""


def main() -> int:
    QApplication.setOrganizationName("SilverWallDiscs")
    QApplication.setApplicationName("SimpleFortChest")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
