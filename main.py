"""
FLIR T1040 Viewer — PyQt6 GUI アプリケーション

【起動方法】
  pip install PyQt6
  python main.py   （管理者権限不要）
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QSize
)
from PyQt6.QtGui import QPixmap, QFont, QIcon, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QGroupBox,
    QVBoxLayout, QHBoxLayout, QScrollArea, QSplitter,
    QStatusBar, QMessageBox, QSizePolicy, QSpacerItem,
    QFrame, QFileDialog, QLineEdit,
)

from flir_sdk import FlirCamera, CameraInfo

# ── ロギング ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── 設定 ────────────────────────────────────────────────────────────────────
# PyInstaller --onefile: __file__ は一時フォルダを指すため sys.executable 基準にする
if getattr(sys, "frozen", False):
    _SCRIPT_DIR = Path(sys.executable).parent
else:
    _SCRIPT_DIR = Path(__file__).parent
SETTINGS_FILE    = _SCRIPT_DIR / "settings.json"
DEFAULT_SAVE_DIR = str(_SCRIPT_DIR / "captures")
DLL_DIR          = None          # None → flir_sdk.py の _DLL_SEARCH_DIRS を使用
LIVE_INTERVAL    = 100           # ライブビュー更新間隔 ms (≒ 10 fps)
CONNECT_TIMEOUT  = 15.0


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data: dict):
    SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# T1040 の代表的な温度レンジ名（SDK からの取得に失敗した場合のフォールバック）
_RANGE_LABELS = [
    "レンジ 0",
    "レンジ 1",
    "レンジ 2",
    "レンジ 3",
]


# ── スタイルシート ────────────────────────────────────────────────────────────
STYLE = """
QWidget {
    font-family: "Meiryo UI", "Yu Gothic UI", sans-serif;
    font-size: 10pt;
}
QMainWindow {
    background: #EBEBEB;
}

/* --- グループボックス --- */
QGroupBox {
    font-weight: bold;
    font-size: 9pt;
    border: 1px solid #C8C8C8;
    border-radius: 6px;
    margin-top: 10px;
    padding: 8px 6px 6px 6px;
    background: #FAFAFA;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: #1A5276;
}

/* --- 汎用ボタン --- */
QPushButton {
    border: 1px solid #BBBBBB;
    border-radius: 4px;
    padding: 5px 10px;
    background: #F2F2F2;
    color: #222222;
}
QPushButton:hover   { background: #D6EAF8; border-color: #2E86C1; }
QPushButton:pressed { background: #AED6F1; }
QPushButton:disabled { color: #AAAAAA; background: #F5F5F5; border-color: #DDDDDD; }

/* --- キャプチャボタン --- */
QPushButton#btn_capture {
    font-size: 14pt;
    font-weight: bold;
    padding: 14px;
    background: #1A5276;
    color: white;
    border: none;
    border-radius: 8px;
}
QPushButton#btn_capture:hover   { background: #2874A6; }
QPushButton#btn_capture:pressed { background: #154360; }
QPushButton#btn_capture:disabled {
    background: #999999;
    color: #CCCCCC;
}

/* --- 接続ボタン --- */
QPushButton#btn_connect {
    background: #1E8449;
    color: white;
    border: none;
    font-weight: bold;
    padding: 6px 12px;
    border-radius: 4px;
}
QPushButton#btn_connect:hover   { background: #239B56; }
QPushButton#btn_connect:pressed { background: #196F3D; }
QPushButton#btn_connect:disabled { background: #AAAAAA; }

/* --- 切断ボタン --- */
QPushButton#btn_disconnect {
    background: #CB4335;
    color: white;
    border: none;
    padding: 6px 12px;
    border-radius: 4px;
}
QPushButton#btn_disconnect:hover   { background: #E74C3C; }
QPushButton#btn_disconnect:pressed { background: #A93226; }
QPushButton#btn_disconnect:disabled { background: #AAAAAA; }

/* --- NUC ボタン --- */
QPushButton#btn_nuc {
    background: #884EA0;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 10px;
}
QPushButton#btn_nuc:hover   { background: #9B59B6; }
QPushButton#btn_nuc:pressed { background: #6C3483; }
QPushButton#btn_nuc:disabled { background: #AAAAAA; }

/* --- コンボ・スピン --- */
QComboBox, QDoubleSpinBox {
    border: 1px solid #C0C0C0;
    border-radius: 3px;
    padding: 4px 6px;
    background: white;
    min-height: 22px;
}
QComboBox:focus, QDoubleSpinBox:focus {
    border-color: #2874A6;
}
QComboBox::drop-down { border: none; }

/* --- ライブビュー --- */
QLabel#lbl_live {
    background: #0D0D1A;
    color: #555577;
    border: 2px solid #2A2A4A;
    border-radius: 4px;
}

/* --- スクロールエリア --- */
QScrollArea, QScrollArea > QWidget > QWidget {
    background: #EBEBEB;
    border: none;
}

/* --- 区切り線 --- */
QFrame#separator {
    color: #CCCCCC;
    background: #CCCCCC;
    max-height: 1px;
}
"""


# ── 接続スレッド ──────────────────────────────────────────────────────────────

class ConnectWorker(QThread):
    connected = pyqtSignal(object, object)  # (FlirCamera, CameraInfo)
    failed    = pyqtSignal(str)

    def __init__(self, save_dir: str, dll_dir):
        super().__init__()
        self._save_dir = save_dir
        self._dll_dir  = dll_dir

    def run(self):
        try:
            cam  = FlirCamera(save_dir=self._save_dir, dll_dir=self._dll_dir)
            info = cam.discover_and_connect(timeout=CONNECT_TIMEOUT)
            self.connected.emit(cam, info)
        except Exception as e:
            self.failed.emit(str(e))


# ── NUC スレッド ──────────────────────────────────────────────────────────────

class NucWorker(QThread):
    done = pyqtSignal(bool)

    def __init__(self, cam: FlirCamera):
        super().__init__()
        self._cam = cam

    def run(self):
        ok = self._cam.trigger_nuc()
        self.done.emit(ok)


# ── メインウィンドウ ───────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._cam: FlirCamera | None = None
        self._worker: ConnectWorker | None = None

        # 設定読み込み
        self._settings  = load_settings()
        self._save_dir  = self._settings.get("save_dir", DEFAULT_SAVE_DIR)

        # FPS 計測用
        self._fps_t0     = time.monotonic()
        self._fps_frames = 0
        self._fps_val    = 0.0

        self.setWindowTitle("FLIR T1040 Viewer")
        self.resize(1200, 760)
        self.setStyleSheet(STYLE)

        self._build_ui()
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(LIVE_INTERVAL)
        self._live_timer.timeout.connect(self._update_live)

        self._set_connected(False)

    # ── UI 構築 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(splitter)

        # ─ 左: ライブビュー ─
        self._lbl_live = QLabel("カメラ未接続\n\n[接続] ボタンを押してください")
        self._lbl_live.setObjectName("lbl_live")
        self._lbl_live.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_live.setMinimumSize(640, 480)
        self._lbl_live.setFont(QFont("Meiryo UI", 13))
        splitter.addWidget(self._lbl_live)

        # ─ 右: コントロールパネル ─
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(300)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel = QWidget()
        vbox  = QVBoxLayout(panel)
        vbox.setSpacing(6)
        vbox.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(panel)
        splitter.addWidget(scroll)
        splitter.setSizes([890, 300])

        # ── 接続 ──
        grp = QGroupBox("接続")
        lay = QVBoxLayout(grp)

        dot_row = QHBoxLayout()
        self._dot   = QLabel("●")
        self._dot.setFixedWidth(18)
        self._dot.setFont(QFont("Arial", 13))
        self._conn_label = QLabel("未接続")
        dot_row.addWidget(self._dot)
        dot_row.addWidget(self._conn_label)
        dot_row.addStretch()
        lay.addLayout(dot_row)

        btn_row = QHBoxLayout()
        self._btn_connect    = QPushButton("接続")
        self._btn_disconnect = QPushButton("切断")
        self._btn_connect.setObjectName("btn_connect")
        self._btn_disconnect.setObjectName("btn_disconnect")
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        btn_row.addWidget(self._btn_connect)
        btn_row.addWidget(self._btn_disconnect)
        lay.addLayout(btn_row)

        self._lbl_cam = QLabel("")
        self._lbl_cam.setFont(QFont("Meiryo UI", 8))
        self._lbl_cam.setStyleSheet("color: #555555;")
        self._lbl_cam.setWordWrap(True)
        lay.addWidget(self._lbl_cam)
        vbox.addWidget(grp)

        # ── キャプチャ ──
        grp = QGroupBox("キャプチャ")
        lay = QVBoxLayout(grp)

        self._btn_capture = QPushButton("📷  キャプチャ")
        self._btn_capture.setObjectName("btn_capture")
        self._btn_capture.setFixedHeight(56)
        self._btn_capture.clicked.connect(self._on_capture)
        lay.addWidget(self._btn_capture)

        self._lbl_saved = QLabel("—")
        self._lbl_saved.setFont(QFont("Meiryo UI", 8))
        self._lbl_saved.setStyleSheet("color: #2C6E49;")
        self._lbl_saved.setWordWrap(True)
        lay.addWidget(self._lbl_saved)

        # 保存先フォルダ
        lbl_dir = QLabel("保存先フォルダ:")
        lbl_dir.setFont(QFont("Meiryo UI", 8))
        lbl_dir.setStyleSheet("color: #555555;")
        lay.addWidget(lbl_dir)

        dir_row = QHBoxLayout()
        self._edit_save_dir = QLineEdit(self._save_dir)
        self._edit_save_dir.setReadOnly(True)
        self._edit_save_dir.setFont(QFont("Meiryo UI", 8))
        self._edit_save_dir.setToolTip(self._save_dir)
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(32)
        btn_browse.setToolTip("フォルダを選択")
        btn_browse.clicked.connect(self._on_browse_save_dir)
        dir_row.addWidget(self._edit_save_dir)
        dir_row.addWidget(btn_browse)
        lay.addLayout(dir_row)

        self._btn_folder = QPushButton("📁  保存フォルダを開く")
        self._btn_folder.clicked.connect(self._on_open_folder)
        lay.addWidget(self._btn_folder)
        vbox.addWidget(grp)

        # ── フォーカス ──
        grp = QGroupBox("フォーカス")
        lay = QHBoxLayout(grp)

        self._btn_near = QPushButton("◀ 近")
        self._btn_af   = QPushButton("オートフォーカス")
        self._btn_far  = QPushButton("遠 ▶")

        self._btn_near.pressed.connect(self._on_focus_near_press)
        self._btn_near.released.connect(self._on_focus_stop)
        self._btn_af.clicked.connect(self._on_autofocus)
        self._btn_far.pressed.connect(self._on_focus_far_press)
        self._btn_far.released.connect(self._on_focus_stop)

        for b in (self._btn_near, self._btn_af, self._btn_far):
            lay.addWidget(b)
        self._focus_grp = grp
        vbox.addWidget(grp)

        # ── パレット ──
        grp = QGroupBox("カラーパレット")
        lay = QVBoxLayout(grp)
        self._cbo_palette = QComboBox()
        self._cbo_palette.currentIndexChanged.connect(self._on_palette_changed)
        lay.addWidget(self._cbo_palette)
        self._palette_grp = grp
        vbox.addWidget(grp)

        # ── 温度レンジ ──
        grp = QGroupBox("温度レンジ")
        lay = QVBoxLayout(grp)
        self._cbo_range = QComboBox()
        self._cbo_range.currentIndexChanged.connect(self._on_range_changed)
        lay.addWidget(self._cbo_range)
        self._range_grp = grp
        vbox.addWidget(grp)

        # ── 放射率 ──
        grp = QGroupBox("放射率（Emissivity）")
        lay = QHBoxLayout(grp)
        self._spin_emiss = QDoubleSpinBox()
        self._spin_emiss.setRange(0.01, 1.00)
        self._spin_emiss.setSingleStep(0.01)
        self._spin_emiss.setDecimals(2)
        self._spin_emiss.setValue(1.00)
        self._spin_emiss.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_apply = QPushButton("適用")
        btn_apply.setFixedWidth(52)
        btn_apply.clicked.connect(self._on_emissivity_apply)
        lay.addWidget(self._spin_emiss)
        lay.addWidget(btn_apply)
        self._emiss_grp = grp
        vbox.addWidget(grp)

        # ── NUC ──
        grp = QGroupBox("補正（NUC）")
        lay = QVBoxLayout(grp)
        self._btn_nuc = QPushButton("NUC 手動実行")
        self._btn_nuc.setObjectName("btn_nuc")
        self._btn_nuc.clicked.connect(self._on_nuc)
        lbl = QLabel("非一様性補正を手動でトリガーします（数秒かかります）")
        lbl.setFont(QFont("Meiryo UI", 8))
        lbl.setStyleSheet("color: #666666;")
        lbl.setWordWrap(True)
        lay.addWidget(self._btn_nuc)
        lay.addWidget(lbl)
        self._nuc_grp = grp
        vbox.addWidget(grp)

        vbox.addStretch()

        # ── ステータスバー ──
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._lbl_status = QLabel("起動完了")
        self._lbl_fps    = QLabel("")
        sb.addWidget(self._lbl_status, 1)
        sb.addPermanentWidget(self._lbl_fps)

    # ── 接続 / 切断 ──────────────────────────────────────────────────────────

    def _on_connect(self):
        if self._cam:
            return
        self._btn_connect.setEnabled(False)
        self._btn_disconnect.setEnabled(False)
        self._dot.setStyleSheet("color: #E67E22;")
        self._conn_label.setText("接続中...")
        self._lbl_status.setText(
            f"USB カメラを検索中（最大 {CONNECT_TIMEOUT:.0f} 秒）...")

        self._worker = ConnectWorker(self._save_dir, DLL_DIR)
        self._worker.connected.connect(self._on_connected)
        self._worker.failed.connect(self._on_connect_failed)
        self._worker.start()

    def _on_connected(self, cam: FlirCamera, info: CameraInfo):
        self._cam = cam
        self._set_connected(True)

        # カメラ情報ラベル
        parts = []
        if info.model_name:    parts.append(info.model_name)
        if info.serial_number: parts.append(f"S/N: {info.serial_number}")
        if info.firmware:      parts.append(f"FW: {info.firmware}")
        if info.width:         parts.append(f"{info.width}×{info.height}")
        self._lbl_cam.setText("\n".join(parts))

        # パレット一覧を取得・設定
        self._cbo_palette.blockSignals(True)
        self._cbo_palette.clear()
        palettes = cam.get_palettes()
        for p in palettes:
            self._cbo_palette.addItem(p)
        cur = cam.get_current_palette()
        if cur >= 0:
            self._cbo_palette.setCurrentIndex(cur)
        self._cbo_palette.blockSignals(False)

        # 温度レンジ一覧
        self._cbo_range.blockSignals(True)
        self._cbo_range.clear()
        count = cam.get_temp_range_count()
        for i in range(count):
            label = _RANGE_LABELS[i] if i < len(_RANGE_LABELS) else f"レンジ {i}"
            self._cbo_range.addItem(label)
        cur_r = cam.get_current_temp_range()
        if cur_r >= 0:
            self._cbo_range.setCurrentIndex(cur_r)
        self._cbo_range.blockSignals(False)

        # 放射率
        self._spin_emiss.setValue(cam.get_emissivity())

        self._lbl_status.setText("ストリーミング中")
        self._live_timer.start()

    def _on_connect_failed(self, msg: str):
        self._set_connected(False)
        QMessageBox.critical(self, "接続エラー", msg)
        self._lbl_status.setText("接続失敗")

    def _on_disconnect(self):
        self._live_timer.stop()
        if self._cam:
            try:
                self._cam.disconnect()
            except Exception:
                pass
            self._cam = None
        self._set_connected(False)
        self._lbl_cam.setText("")
        self._cbo_palette.clear()
        self._cbo_range.clear()
        self._lbl_live.clear()
        self._lbl_live.setText("カメラ未接続\n\n[接続] ボタンを押してください")
        self._lbl_fps.setText("")
        self._lbl_status.setText("切断しました")

    def _set_connected(self, on: bool):
        self._btn_connect.setEnabled(not on)
        self._btn_disconnect.setEnabled(on)
        for grp in (self._focus_grp, self._palette_grp, self._range_grp,
                    self._emiss_grp, self._nuc_grp):
            grp.setEnabled(on)
        self._btn_capture.setEnabled(on)
        self._btn_folder.setEnabled(True)

        if on:
            self._dot.setStyleSheet("color: #1E8449;")
            self._conn_label.setText("接続中")
        else:
            self._dot.setStyleSheet("color: #CB4335;")
            self._conn_label.setText("未接続")

    # ── ライブビュー更新 ─────────────────────────────────────────────────────

    def _update_live(self):
        if not self._cam:
            return
        path = self._cam.get_live_frame()
        if not path:
            return
        pix = QPixmap(path)
        if pix.isNull():
            return

        # アスペクト比を保ちつつラベルサイズに合わせてスケール
        self._lbl_live.setPixmap(
            pix.scaled(
                self._lbl_live.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        # FPS 計測（1秒ごとに更新）
        self._fps_frames += 1
        elapsed = time.monotonic() - self._fps_t0
        if elapsed >= 1.0:
            self._fps_val    = self._fps_frames / elapsed
            self._fps_frames = 0
            self._fps_t0     = time.monotonic()
            w, h = self._cam.image_size
            size_str = f"  |  {w}×{h}" if w else ""
            self._lbl_fps.setText(
                f"FPS: {self._fps_val:.1f}{size_str}"
                f"  |  フレーム数: {self._cam.frame_count}"
            )

    # ── キャプチャ ───────────────────────────────────────────────────────────

    def _on_capture(self):
        if not self._cam:
            return
        path = self._cam.capture(prefix="flir")
        if path:
            self._lbl_saved.setText(f"✔  {Path(path).name}")
            self._lbl_status.setText(f"保存完了: {path}")
        else:
            self._lbl_saved.setText("✘  キャプチャ失敗")
            self._lbl_status.setText(
                "キャプチャ失敗 — 起動直後の場合は 2〜3 秒待ってから再試行してください")

    def _on_open_folder(self):
        folder = Path(self._save_dir).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _on_browse_save_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self,
            "保存先フォルダを選択",
            self._save_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not chosen:
            return
        self._save_dir = chosen
        self._edit_save_dir.setText(chosen)
        self._edit_save_dir.setToolTip(chosen)
        # 接続中なら即座にカメラの保存先も更新
        if self._cam:
            from pathlib import Path as _Path
            self._cam.save_dir = _Path(chosen)
            self._cam.save_dir.mkdir(parents=True, exist_ok=True)
        # 設定を永続化
        self._settings["save_dir"] = chosen
        save_settings(self._settings)
        self._lbl_status.setText(f"保存先を変更しました: {chosen}")

    # ── フォーカス ───────────────────────────────────────────────────────────

    def _on_focus_near_press(self):
        if self._cam:
            self._cam.focus_near_start()

    def _on_focus_far_press(self):
        if self._cam:
            self._cam.focus_far_start()

    def _on_focus_stop(self):
        if self._cam:
            self._cam.focus_stop()

    def _on_autofocus(self):
        if not self._cam:
            return
        self._btn_af.setEnabled(False)
        self._lbl_status.setText("オートフォーカス実行中...")
        ok = self._cam.autofocus()
        self._btn_af.setEnabled(True)
        self._lbl_status.setText(
            "オートフォーカス完了" if ok else "オートフォーカス失敗")

    # ── パレット ─────────────────────────────────────────────────────────────

    def _on_palette_changed(self, index: int):
        if self._cam and index >= 0:
            ok = self._cam.set_palette(index)
            name = self._cbo_palette.currentText()
            self._lbl_status.setText(
                f"パレット: {name}" if ok else f"パレット変更失敗: {name}")

    # ── 温度レンジ ───────────────────────────────────────────────────────────

    def _on_range_changed(self, index: int):
        if self._cam and index >= 0:
            ok = self._cam.set_temp_range(index)
            self._lbl_status.setText(
                f"温度レンジ: レンジ {index} に変更" if ok
                else f"温度レンジ変更失敗")

    # ── 放射率 ───────────────────────────────────────────────────────────────

    def _on_emissivity_apply(self):
        if not self._cam:
            return
        val = self._spin_emiss.value()
        ok  = self._cam.set_emissivity(val)
        self._lbl_status.setText(
            f"放射率 {val:.2f} を設定しました" if ok
            else f"放射率の設定に失敗しました")

    # ── NUC ─────────────────────────────────────────────────────────────────

    def _on_nuc(self):
        if not self._cam:
            return
        self._btn_nuc.setEnabled(False)
        self._lbl_status.setText("NUC 実行中...")
        worker = NucWorker(self._cam)
        worker.done.connect(self._on_nuc_done)
        worker.done.connect(lambda _: worker.deleteLater())
        worker.start()
        self._nuc_worker = worker  # GC 防止

    def _on_nuc_done(self, ok: bool):
        self._btn_nuc.setEnabled(True)
        self._lbl_status.setText("NUC 完了" if ok else "NUC 実行失敗")

    # ── 終了 ─────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._live_timer.stop()
        if self._cam:
            try:
                self._cam.disconnect()
            except Exception:
                pass
        super().closeEvent(event)


# ── エントリーポイント ─────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Meiryo UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
