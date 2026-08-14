"""Interface gráfica do OrganizaPDF, construída com PySide6."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QStandardPaths, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from organizapdf import __version__
from organizapdf.core import (
    MergeCancelled,
    MergeOptions,
    MergeReport,
    OrganizaPdfError,
    PdfInfo,
    PdfPasswordRequired,
    PdfSource,
    SplitOptions,
    SplitReport,
    build_page_groups,
    inspect_pdf,
    merge_pdfs,
    split_pdf,
)

SOURCE_ROLE = Qt.ItemDataRole.UserRole


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    packaged = base / "organizapdf" / "assets" / name
    return packaged if packaged.exists() else Path(__file__).resolve().parent / "assets" / name


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class PdfTree(QTreeWidget):
    files_dropped = Signal(list)
    order_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(5)
        self.setHeaderLabels(["ORDEM", "ARQUIVO", "PÁGINAS", "TAMANHO", "STATUS"])
        self.setRootIsDecorated(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setUniformRowHeights(True)
        self.setMinimumHeight(235)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            self.files_dropped.emit([url.toLocalFile() for url in event.mimeData().urls()])
            event.acceptProposedAction()
            return
        super().dropEvent(event)
        self.renumber()
        self.order_changed.emit()

    def renumber(self) -> None:
        for index in range(self.topLevelItemCount()):
            self.topLevelItem(index).setText(0, str(index + 1))

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key.Key_Delete:
            self.window().remove_selected()  # type: ignore[attr-defined]
            return
        super().keyPressEvent(event)


class SplitDropFrame(QFrame):
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(url.toLocalFile().lower().endswith(".pdf") for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        paths = [
            url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile().lower().endswith(".pdf")
        ]
        if paths:
            self.file_dropped.emit(paths[0])
            event.acceptProposedAction()


class MergeWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, sources: list[PdfSource], output: Path, options: MergeOptions) -> None:
        super().__init__()
        self.sources = sources
        self.output = output
        self.options = options
        self._cancel_requested = False

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            report = merge_pdfs(
                self.sources,
                self.output,
                self.options,
                progress=lambda current, total, name: self.progress.emit(current, total, name),
                should_cancel=lambda: self._cancel_requested,
            )
        except MergeCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.completed.emit(report)


class SplitWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        source: PdfSource,
        output_dir: Path,
        groups: list[list[int]],
        options: SplitOptions,
        overwrite: bool,
    ) -> None:
        super().__init__()
        self.source = source
        self.output_dir = output_dir
        self.groups = groups
        self.options = options
        self.overwrite = overwrite
        self._cancel_requested = False

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        try:
            report = split_pdf(
                self.source,
                self.output_dir,
                self.groups,
                self.options,
                overwrite=self.overwrite,
                progress=lambda current, total, name: self.progress.emit(current, total, name),
                should_cancel=lambda: self._cancel_requested,
            )
        except MergeCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.completed.emit(report)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("EDR Tecnologia", "OrganizaPDF")
        self.thread: QThread | None = None
        self.worker: MergeWorker | SplitWorker | None = None
        self.active_operation: str | None = None
        self.split_source: PdfSource | None = None
        self.split_info: PdfInfo | None = None
        self.setWindowTitle(f"OrganizaPDF {__version__}")
        self.setWindowIcon(QIcon(str(resource_path("icon.svg"))))
        self.resize(980, 760)
        self.setMinimumSize(800, 650)
        self._build_ui()
        self._apply_style()
        self._restore_settings()

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 22, 28, 20)
        outer.setSpacing(15)
        outer.addLayout(self._build_hero())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_merge_tab(), "  Unir PDFs  ")
        self.tabs.addTab(self._build_split_tab(), "  Separar PDF  ")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        outer.addWidget(self.tabs, stretch=1)

        action_row = QHBoxLayout()
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("hint")
        action_row.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(220)
        action_row.addWidget(self.progress)
        action_row.addStretch()
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        action_row.addWidget(self.cancel_button)
        self.main_action = QPushButton("Unir PDFs")
        self.main_action.setObjectName("mainAction")
        self.main_action.setMinimumWidth(190)
        self.main_action.clicked.connect(self.start_current_operation)
        action_row.addWidget(self.main_action)
        outer.addLayout(action_row)

        self.setCentralWidget(root)
        status = QStatusBar()
        status.showMessage("Pronto")
        self.setStatusBar(status)

        open_action = QAction("Adicionar ou abrir PDF", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose_for_current_tab)
        self.addAction(open_action)
        self.update_actions()

    def _build_hero(self) -> QHBoxLayout:
        hero = QHBoxLayout()
        logo = QLabel("PDF")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(64, 64)
        title_box = QVBoxLayout()
        title = QLabel("OrganizaPDF")
        title.setObjectName("title")
        subtitle = QLabel("Una, organize e separe documentos sem transformar páginas em imagens.")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hero.addWidget(logo)
        hero.addLayout(title_box)
        hero.addStretch()
        version = QLabel(f"v{__version__}")
        version.setObjectName("badge")
        hero.addWidget(version, alignment=Qt.AlignmentFlag.AlignTop)
        return hero

    def _build_merge_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(12)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 14)
        toolbar = QHBoxLayout()
        self.add_button = QPushButton("＋  Adicionar PDFs")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(self.choose_files)
        toolbar.addWidget(self.add_button)
        toolbar.addStretch()
        self.up_button = QToolButton()
        self.up_button.setText("↑")
        self.up_button.setToolTip("Mover para cima")
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button = QToolButton()
        self.down_button.setText("↓")
        self.down_button.setToolTip("Mover para baixo")
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.remove_button = QToolButton()
        self.remove_button.setText("Remover")
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button = QToolButton()
        self.clear_button.setText("Limpar")
        self.clear_button.clicked.connect(self.clear_files)
        for button in (self.up_button, self.down_button, self.remove_button, self.clear_button):
            toolbar.addWidget(button)
        card_layout.addLayout(toolbar)

        self.tree = PdfTree()
        self.tree.files_dropped.connect(self.add_files)
        self.tree.itemSelectionChanged.connect(self.update_actions)
        self.tree.order_changed.connect(self.update_merge_summary)
        card_layout.addWidget(self.tree)
        hint = QLabel("Arraste PDFs para esta área • a ordem da lista será a ordem do resultado")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(hint)
        self.merge_summary = QLabel("Nenhum PDF selecionado")
        self.merge_summary.setObjectName("summary")
        card_layout.addWidget(self.merge_summary)
        layout.addWidget(card, stretch=1)

        options = QFrame()
        options.setObjectName("options")
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(16, 11, 16, 11)
        options_layout.addWidget(self._section_title("Preservação e navegação"))
        checks = QHBoxLayout()
        self.outline_check = QCheckBox("Manter marcadores originais")
        self.file_bookmark_check = QCheckBox("Criar marcador para cada arquivo")
        self.metadata_check = QCheckBox("Manter metadados do primeiro PDF")
        for checkbox in (self.outline_check, self.file_bookmark_check, self.metadata_check):
            checkbox.setChecked(True)
            checks.addWidget(checkbox)
        checks.addStretch()
        options_layout.addLayout(checks)
        layout.addWidget(options)

        output_row = QHBoxLayout()
        output_row.addWidget(self._field_label("Salvar como"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Escolha o arquivo PDF de destino")
        output_row.addWidget(self.output_edit, stretch=1)
        browse = QPushButton("Escolher…")
        browse.clicked.connect(self.choose_output)
        output_row.addWidget(browse)
        layout.addLayout(output_row)
        return tab

    def _build_split_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(12)

        source_card = SplitDropFrame()
        source_card.setObjectName("card")
        source_card.file_dropped.connect(self.set_split_file)
        source_layout = QVBoxLayout(source_card)
        source_layout.setContentsMargins(18, 16, 18, 16)
        source_top = QHBoxLayout()
        self.split_choose_button = QPushButton("Selecionar PDF para separar")
        self.split_choose_button.setObjectName("primary")
        self.split_choose_button.clicked.connect(self.choose_split_file)
        source_top.addWidget(self.split_choose_button)
        source_top.addStretch()
        self.split_clear_button = QToolButton()
        self.split_clear_button.setText("Remover")
        self.split_clear_button.clicked.connect(self.clear_split_file)
        source_top.addWidget(self.split_clear_button)
        source_layout.addLayout(source_top)
        self.split_file_label = QLabel("Nenhum arquivo selecionado • você também pode arrastar um PDF")
        self.split_file_label.setObjectName("splitFile")
        self.split_file_label.setWordWrap(True)
        source_layout.addWidget(self.split_file_label)
        self.split_file_details = QLabel("")
        self.split_file_details.setObjectName("hint")
        source_layout.addWidget(self.split_file_details)
        layout.addWidget(source_card)

        method = QFrame()
        method.setObjectName("options")
        method_layout = QVBoxLayout(method)
        method_layout.setContentsMargins(16, 13, 16, 13)
        method_layout.addWidget(self._section_title("Como deseja separar?"))
        mode_row = QHBoxLayout()
        self.split_mode = QComboBox()
        self.split_mode.addItem("Uma página por arquivo", "single")
        self.split_mode.addItem("Blocos com quantidade fixa de páginas", "chunks")
        self.split_mode.addItem("Grupos personalizados", "ranges")
        self.split_mode.currentIndexChanged.connect(self.update_split_mode)
        mode_row.addWidget(self.split_mode, stretch=1)
        self.chunk_label = QLabel("Páginas por arquivo")
        self.chunk_label.setObjectName("fieldLabel")
        mode_row.addWidget(self.chunk_label)
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(1, 99999)
        self.chunk_spin.setValue(10)
        self.chunk_spin.valueChanged.connect(self.update_split_preview)
        mode_row.addWidget(self.chunk_spin)
        method_layout.addLayout(mode_row)
        self.ranges_edit = QLineEdit()
        self.ranges_edit.setPlaceholderText(
            "Exemplo: 1-3; 4-6; 7,9,11  — cada grupo separado por ; gera um PDF"
        )
        self.ranges_edit.textChanged.connect(self.update_split_preview)
        method_layout.addWidget(self.ranges_edit)
        self.split_preview = QLabel("Selecione um PDF para visualizar o resultado.")
        self.split_preview.setObjectName("summary")
        method_layout.addWidget(self.split_preview)
        layout.addWidget(method)

        split_options = QFrame()
        split_options.setObjectName("options")
        split_options_layout = QVBoxLayout(split_options)
        split_options_layout.setContentsMargins(16, 11, 16, 11)
        split_options_layout.addWidget(self._section_title("Preservação"))
        split_checks = QHBoxLayout()
        self.split_outline_check = QCheckBox("Manter marcadores aplicáveis a cada parte")
        self.split_metadata_check = QCheckBox("Manter metadados do documento")
        self.split_outline_check.setChecked(True)
        self.split_metadata_check.setChecked(True)
        split_checks.addWidget(self.split_outline_check)
        split_checks.addWidget(self.split_metadata_check)
        split_checks.addStretch()
        split_options_layout.addLayout(split_checks)
        layout.addWidget(split_options)

        destination_row = QHBoxLayout()
        destination_row.addWidget(self._field_label("Salvar partes em"))
        self.split_output_edit = QLineEdit()
        self.split_output_edit.setPlaceholderText("Escolha a pasta de destino")
        destination_row.addWidget(self.split_output_edit, stretch=1)
        browse_dir = QPushButton("Escolher…")
        browse_dir.clicked.connect(self.choose_split_output)
        destination_row.addWidget(browse_dir)
        layout.addLayout(destination_row)
        layout.addStretch()
        return tab

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #F4F6F8; color: #17212B;
                font-family: "Segoe UI", Arial; font-size: 13px;
            }
            QLabel#logo {
                background: #D92D20; color: white; border-radius: 16px;
                font-size: 20px; font-weight: 800;
            }
            QLabel#title { font-size: 28px; font-weight: 750; color: #101828; }
            QLabel#subtitle, QLabel#hint { color: #667085; }
            QLabel#badge {
                background: #E9F0FF; color: #175CD3; border-radius: 9px;
                padding: 5px 10px; font-weight: 600;
            }
            QLabel#sectionTitle, QLabel#fieldLabel { font-weight: 700; color: #344054; }
            QLabel#summary { font-weight: 650; color: #344054; }
            QLabel#splitFile { font-size: 15px; font-weight: 650; color: #344054; }
            QFrame#card, QFrame#options {
                background: white; border: 1px solid #E4E7EC; border-radius: 12px;
            }
            QTabWidget::pane { border: 0; }
            QTabBar::tab {
                background: #EAECF0; color: #475467; border-radius: 8px;
                padding: 10px 24px; margin-right: 6px; font-weight: 700;
            }
            QTabBar::tab:selected { background: #175CD3; color: white; }
            QTreeWidget {
                background: white; border: 1px solid #D0D5DD;
                border-radius: 8px; outline: 0; alternate-background-color: #F9FAFB;
            }
            QTreeWidget::item { height: 36px; border-bottom: 1px solid #F2F4F7; }
            QTreeWidget::item:selected { background: #EAF2FF; color: #1849A9; }
            QHeaderView::section {
                background: #F9FAFB; color: #667085; border: 0;
                border-bottom: 1px solid #EAECF0; padding: 8px;
                font-size: 11px; font-weight: 700;
            }
            QPushButton, QToolButton {
                background: white; border: 1px solid #D0D5DD;
                border-radius: 7px; padding: 8px 13px; font-weight: 600;
            }
            QPushButton:hover, QToolButton:hover { background: #F9FAFB; border-color: #98A2B3; }
            QPushButton:disabled, QToolButton:disabled { color: #98A2B3; background: #F2F4F7; }
            QPushButton#primary { background: #175CD3; color: white; border-color: #175CD3; }
            QPushButton#primary:hover { background: #1849A9; }
            QPushButton#mainAction {
                background: #D92D20; color: white; border-color: #D92D20;
                font-size: 14px; padding: 11px 18px;
            }
            QPushButton#mainAction:hover { background: #B42318; }
            QLineEdit, QComboBox, QSpinBox {
                background: white; border: 1px solid #D0D5DD;
                border-radius: 7px; padding: 8px; selection-background-color: #175CD3;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #84ADFF; }
            QCheckBox { spacing: 7px; }
            QProgressBar { border: 0; background: #EAECF0; height: 7px; border-radius: 3px; }
            QProgressBar::chunk { background: #175CD3; border-radius: 3px; }
            QStatusBar { background: #F4F6F8; color: #667085; }
            """
        )

    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.outline_check.setChecked(self.settings.value("outline", True, bool))
        self.file_bookmark_check.setChecked(self.settings.value("file_bookmarks", True, bool))
        self.metadata_check.setChecked(self.settings.value("metadata", True, bool))
        self.split_outline_check.setChecked(self.settings.value("split_outline", True, bool))
        self.split_metadata_check.setChecked(self.settings.value("split_metadata", True, bool))
        self.output_edit.setText(str(self._default_merge_output()))
        split_dir = self.settings.value("last_split_output_dir", self._documents_dir())
        self.split_output_edit.setText(str(split_dir))
        self.split_mode.setCurrentIndex(self.settings.value("split_mode", 0, int))
        self.chunk_spin.setValue(self.settings.value("split_chunk_size", 10, int))
        self.update_split_mode()

    @staticmethod
    def _documents_dir() -> Path:
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))

    def _default_merge_output(self) -> Path:
        base = Path(str(self.settings.value("last_output_dir", self._documents_dir())))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return base / f"PDF_unido_{stamp}.pdf"

    @Slot()
    def choose_for_current_tab(self) -> None:
        self.choose_files() if self.tabs.currentIndex() == 0 else self.choose_split_file()

    @Slot()
    def choose_files(self) -> None:
        start = str(self.settings.value("last_input_dir", self._documents_dir()))
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecionar PDFs",
            start,
            "Arquivos PDF (*.pdf)",
        )
        if paths:
            self.add_files(paths)

    @Slot(list)
    def add_files(self, paths: list[str]) -> None:
        existing = {
            self.tree.topLevelItem(i).data(0, SOURCE_ROLE).path for i in range(self.tree.topLevelItemCount())
        }
        added = 0
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if path.suffix.lower() != ".pdf" or path in existing:
                continue
            result = self._inspect_with_password(path)
            if result is None:
                continue
            source, info = result
            item = QTreeWidgetItem()
            item.setData(0, SOURCE_ROLE, source)
            item.setText(1, path.name)
            item.setToolTip(1, str(path))
            item.setText(2, str(info.pages))
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
            item.setText(3, human_size(info.size_bytes))
            item.setText(4, "Pronto • protegido" if info.encrypted else "Pronto")
            self.tree.addTopLevelItem(item)
            existing.add(path)
            added += 1
        self.tree.renumber()
        self.update_merge_summary()
        self.update_actions()
        if added:
            self.settings.setValue("last_input_dir", str(Path(paths[0]).parent))
            self.statusBar().showMessage(f"{added} arquivo(s) adicionado(s)", 4000)

    def _inspect_with_password(self, path: Path) -> tuple[PdfSource, PdfInfo] | None:
        source = PdfSource(path)
        try:
            return source, inspect_pdf(source)
        except PdfPasswordRequired:
            password, accepted = QInputDialog.getText(
                self,
                "PDF protegido",
                f"Informe a senha de “{path.name}”:",
                QLineEdit.EchoMode.Password,
            )
            if not accepted:
                return None
            source = PdfSource(path, password)
            try:
                return source, inspect_pdf(source)
            except OrganizaPdfError as exc:
                QMessageBox.warning(self, "Não foi possível abrir o PDF", str(exc))
                return None
        except OrganizaPdfError as exc:
            QMessageBox.warning(self, "Não foi possível abrir o PDF", str(exc))
            return None

    def merge_sources(self) -> list[PdfSource]:
        return [self.tree.topLevelItem(i).data(0, SOURCE_ROLE) for i in range(self.tree.topLevelItemCount())]

    @Slot()
    def remove_selected(self) -> None:
        for item in self.tree.selectedItems():
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.tree.renumber()
        self.update_merge_summary()
        self.update_actions()

    @Slot()
    def clear_files(self) -> None:
        self.tree.clear()
        self.update_merge_summary()
        self.update_actions()

    def move_selected(self, direction: int) -> None:
        selected = self.tree.selectedItems()
        if len(selected) != 1:
            return
        item = selected[0]
        old = self.tree.indexOfTopLevelItem(item)
        new = old + direction
        if not 0 <= new < self.tree.topLevelItemCount():
            return
        self.tree.takeTopLevelItem(old)
        self.tree.insertTopLevelItem(new, item)
        self.tree.setCurrentItem(item)
        self.tree.renumber()
        self.update_actions()

    @Slot()
    def update_merge_summary(self) -> None:
        files = self.tree.topLevelItemCount()
        pages = sum(int(self.tree.topLevelItem(i).text(2)) for i in range(files))
        text = (
            "Nenhum PDF selecionado" if files == 0 else f"{files} arquivo(s) • {pages} página(s) no resultado"
        )
        self.merge_summary.setText(text)

    @Slot()
    def choose_output(self) -> None:
        current = self.output_edit.text().strip() or str(self._default_merge_output())
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar PDF unido",
            current,
            "Arquivo PDF (*.pdf)",
        )
        if selected:
            if not selected.lower().endswith(".pdf"):
                selected += ".pdf"
            self.output_edit.setText(selected)
            self.settings.setValue("last_output_dir", str(Path(selected).parent))

    @Slot()
    def choose_split_file(self) -> None:
        start = str(self.settings.value("last_split_input_dir", self._documents_dir()))
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar PDF para separar",
            start,
            "Arquivo PDF (*.pdf)",
        )
        if selected:
            self.set_split_file(selected)

    @Slot(str)
    def set_split_file(self, raw_path: str) -> None:
        path = Path(raw_path).expanduser().resolve()
        result = self._inspect_with_password(path)
        if result is None:
            return
        self.split_source, self.split_info = result
        self.split_file_label.setText(path.name)
        protected = " • protegido por senha" if self.split_info.encrypted else ""
        size = human_size(self.split_info.size_bytes)
        self.split_file_details.setText(f"{self.split_info.pages} página(s) • {size}{protected}\n{path}")
        suggested_dir = path.parent / f"{path.stem}_partes"
        self.split_output_edit.setText(str(suggested_dir))
        self.chunk_spin.setMaximum(self.split_info.pages)
        self.settings.setValue("last_split_input_dir", str(path.parent))
        self.update_split_preview()
        self.update_actions()

    @Slot()
    def clear_split_file(self) -> None:
        self.split_source = None
        self.split_info = None
        self.split_file_label.setText("Nenhum arquivo selecionado • você também pode arrastar um PDF")
        self.split_file_details.clear()
        self.split_preview.setText("Selecione um PDF para visualizar o resultado.")
        self.update_actions()

    @Slot()
    def choose_split_output(self) -> None:
        current = self.split_output_edit.text().strip() or str(self._documents_dir())
        selected = QFileDialog.getExistingDirectory(self, "Pasta para salvar as partes", current)
        if selected:
            self.split_output_edit.setText(selected)
            self.settings.setValue("last_split_output_dir", selected)

    @Slot()
    def update_split_mode(self) -> None:
        mode = self.split_mode.currentData()
        chunks = mode == "chunks"
        ranges = mode == "ranges"
        self.chunk_label.setVisible(chunks)
        self.chunk_spin.setVisible(chunks)
        self.ranges_edit.setVisible(ranges)
        self.update_split_preview()

    @Slot()
    def update_split_preview(self) -> None:
        if self.split_info is None:
            self.split_preview.setText("Selecione um PDF para visualizar o resultado.")
            return
        try:
            groups = self._current_split_groups()
        except OrganizaPdfError as exc:
            self.split_preview.setText(str(exc))
            return
        selected_pages = sum(len(group) for group in groups)
        self.split_preview.setText(
            f"Resultado previsto: {len(groups)} arquivo(s) • {selected_pages} página(s)"
        )

    def _current_split_groups(self) -> list[list[int]]:
        if self.split_info is None:
            raise OrganizaPdfError("Selecione um PDF para separar.")
        return build_page_groups(
            self.split_info.pages,
            self.split_mode.currentData(),
            chunk_size=self.chunk_spin.value(),
            ranges=self.ranges_edit.text(),
        )

    @Slot(int)
    def on_tab_changed(self, index: int) -> None:
        self.main_action.setText("Unir PDFs" if index == 0 else "Separar PDF")
        self.update_actions()

    @Slot()
    def update_actions(self) -> None:
        busy = self.thread is not None
        selected = self.tree.selectedItems()
        one = len(selected) == 1
        index = self.tree.indexOfTopLevelItem(selected[0]) if one else -1
        self.up_button.setEnabled(one and index > 0 and not busy)
        self.down_button.setEnabled(one and index < self.tree.topLevelItemCount() - 1 and not busy)
        self.remove_button.setEnabled(bool(selected) and not busy)
        self.clear_button.setEnabled(self.tree.topLevelItemCount() > 0 and not busy)
        self.split_clear_button.setEnabled(self.split_source is not None and not busy)
        ready = (
            self.tree.topLevelItemCount() > 0
            if self.tabs.currentIndex() == 0
            else self.split_source is not None
        )
        self.main_action.setEnabled(ready and not busy)

    @Slot()
    def start_current_operation(self) -> None:
        if self.tabs.currentIndex() == 0:
            self.start_merge()
        else:
            self.start_split()

    def start_merge(self) -> None:
        sources = self.merge_sources()
        if not sources:
            QMessageBox.information(self, "Adicione PDFs", "Selecione pelo menos um arquivo PDF.")
            return
        output_text = self.output_edit.text().strip()
        if not output_text:
            self.choose_output()
            output_text = self.output_edit.text().strip()
        if not output_text:
            return
        output = Path(output_text)
        if output.suffix.lower() != ".pdf":
            output = output.with_suffix(".pdf")
            self.output_edit.setText(str(output))
        if output.exists() and not self._confirm_overwrite(output.name):
            return

        options = MergeOptions(
            preserve_outline=self.outline_check.isChecked(),
            add_file_bookmarks=self.file_bookmark_check.isChecked(),
            preserve_metadata=self.metadata_check.isChecked(),
        )
        self.settings.setValue("outline", options.preserve_outline)
        self.settings.setValue("file_bookmarks", options.add_file_bookmarks)
        self.settings.setValue("metadata", options.preserve_metadata)
        self.settings.setValue("last_output_dir", str(output.parent))
        self._launch_worker(MergeWorker(sources, output, options), "merge", len(sources))

    def start_split(self) -> None:
        if self.split_source is None:
            QMessageBox.information(self, "Selecione um PDF", "Escolha o documento que será separado.")
            return
        try:
            groups = self._current_split_groups()
        except OrganizaPdfError as exc:
            QMessageBox.warning(self, "Revise as páginas", str(exc))
            return
        output_text = self.split_output_edit.text().strip()
        if not output_text:
            self.choose_split_output()
            output_text = self.split_output_edit.text().strip()
        if not output_text:
            return
        output_dir = Path(output_text)
        overwrite = False
        if output_dir.exists() and any(output_dir.glob("*.pdf")):
            overwrite = self._confirm_overwrite(
                "arquivos de partes com os mesmos nomes que já estiverem na pasta"
            )
            if not overwrite:
                return

        options = SplitOptions(
            preserve_outline=self.split_outline_check.isChecked(),
            preserve_metadata=self.split_metadata_check.isChecked(),
        )
        self.settings.setValue("split_outline", options.preserve_outline)
        self.settings.setValue("split_metadata", options.preserve_metadata)
        self.settings.setValue("split_mode", self.split_mode.currentIndex())
        self.settings.setValue("split_chunk_size", self.chunk_spin.value())
        self.settings.setValue("last_split_output_dir", str(output_dir))
        worker = SplitWorker(self.split_source, output_dir, groups, options, overwrite)
        self._launch_worker(worker, "split", len(groups))

    def _confirm_overwrite(self, target: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Substituir arquivos?",
            f"Deseja substituir {target}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _launch_worker(
        self,
        worker: MergeWorker | SplitWorker,
        operation: str,
        total: int,
    ) -> None:
        self.thread = QThread(self)
        self.worker = worker
        self.active_operation = operation
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.progress.connect(self.on_progress)
        worker.failed.connect(self.on_failed)
        worker.cancelled.connect(self.on_cancelled)
        if operation == "merge":
            worker.completed.connect(self.on_merge_completed)
        else:
            worker.completed.connect(self.on_split_completed)
        for signal in (worker.completed, worker.failed, worker.cancelled):
            signal.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup_worker)
        self._set_busy(True, total)
        self.thread.start()

    def _set_busy(self, busy: bool, total: int = 1) -> None:
        self.tabs.setEnabled(not busy)
        self.main_action.setVisible(not busy)
        self.cancel_button.setVisible(busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, max(1, total))
        self.update_actions()

    @Slot(int, int, str)
    def on_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current - 1)
        verb = "Unindo" if self.active_operation == "merge" else "Criando"
        self.progress_label.setText(f"{verb} {current}/{total}: {name}")
        self.statusBar().showMessage(self.progress_label.text())

    @Slot(object)
    def on_merge_completed(self, report: MergeReport) -> None:
        self.progress.setValue(self.progress.maximum())
        details = (
            f"{report.files} arquivo(s) • {report.pages} página(s) • "
            f"{human_size(report.size_bytes)}\n{report.output}"
        )
        self._show_result(
            "PDFs unidos com sucesso",
            details,
            report.output,
            report.output.parent,
            report.warnings,
        )
        self.output_edit.setText(str(self._default_merge_output()))

    @Slot(object)
    def on_split_completed(self, report: SplitReport) -> None:
        self.progress.setValue(self.progress.maximum())
        details = (
            f"{report.files} arquivo(s) criado(s) • {report.pages} página(s) • "
            f"{human_size(report.size_bytes)}\n{report.output_dir}"
        )
        self._show_result(
            "PDF separado com sucesso",
            details,
            report.paths[0] if report.paths else None,
            report.output_dir,
            report.warnings,
        )

    def _show_result(
        self,
        title: str,
        details: str,
        first_file: Path | None,
        folder: Path,
        warnings: tuple[str, ...],
    ) -> None:
        if warnings:
            details += "\n\nObservações:\n• " + "\n• ".join(warnings)
        box = QMessageBox(self)
        box.setWindowTitle("Operação concluída")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(title)
        box.setInformativeText(details)
        open_file = None
        if first_file:
            open_file = box.addButton("Abrir PDF", QMessageBox.ButtonRole.AcceptRole)
        open_folder = box.addButton("Abrir pasta", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if open_file and box.clickedButton() is open_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(first_file)))
        elif box.clickedButton() is open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self.statusBar().showMessage("Concluído", 5000)

    @Slot(str)
    def on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Não foi possível concluir", message)
        self.statusBar().showMessage("Falha na operação", 5000)

    @Slot()
    def on_cancelled(self) -> None:
        self.statusBar().showMessage("Operação cancelada", 5000)

    @Slot()
    def cancel_operation(self) -> None:
        if self.worker:
            self.worker.request_cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("Cancelando após o arquivo atual…")

    @Slot()
    def cleanup_worker(self) -> None:
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.active_operation = None
        self.cancel_button.setEnabled(True)
        self.progress_label.clear()
        self._set_busy(False)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.thread is not None:
            QMessageBox.information(
                self,
                "Operação em andamento",
                "Cancele a operação antes de fechar o aplicativo.",
            )
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("OrganizaPDF")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("EDR Tecnologia")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
