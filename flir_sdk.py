"""
FLIR Atlas C SDK — Python ctypes ラッパー
対象: USB接続 FLIR カメラ（T1040 など T1K シリーズ）
"""

import ctypes
import logging
import os
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# ── DLL ロード ────────────────────────────────────────────────────────────────

def _default_dll_dirs() -> list[Path]:
    # PyInstaller --onefile: DLL は sys._MEIPASS/dll/ に展開される
    if getattr(sys, "frozen", False):
        return [Path(sys._MEIPASS) / "dll"]
    return [Path(__file__).parent / "dll"]

_DLL_SEARCH_DIRS = _default_dll_dirs()


def _load_dll(dll_dir: Path = None) -> ctypes.CDLL:
    dirs = [Path(dll_dir)] if dll_dir else _DLL_SEARCH_DIRS
    for d in dirs:
        if d.exists() and (d / "atlas_c_sdk.dll").exists():
            os.add_dll_directory(str(d))
            return ctypes.CDLL(str(d / "atlas_c_sdk.dll"))
    searched = ", ".join(str(d) for d in dirs)
    raise FileNotFoundError(f"atlas_c_sdk.dll が見つかりません。検索先: {searched}")


# ── 構造体 ────────────────────────────────────────────────────────────────────

class ACS_Error(ctypes.Structure):
    _fields_ = [("code", ctypes.c_int), ("category", ctypes.c_void_p)]


class ACS_CallbackContext(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("deleter", ctypes.c_void_p)]


# ── コールバック型 ─────────────────────────────────────────────────────────────

_CB_ON_IMAGE     = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
_CB_ON_ERROR     = ctypes.CFUNCTYPE(None, ACS_Error, ctypes.c_void_p)
_CB_ON_DISCONN   = ctypes.CFUNCTYPE(None, ACS_Error, ctypes.c_void_p)
_CB_ON_CAM_FOUND = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
_CB_ON_DISC_ERR  = ctypes.CFUNCTYPE(None, ctypes.c_uint, ACS_Error, ctypes.c_void_p)
_CB_ON_CAM_LOST  = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
_CB_ON_DISC_FIN  = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)
_CB_WITH_IMG     = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)

_p = ctypes.c_void_p


# ── 関数バインディング ─────────────────────────────────────────────────────────

def _bind(dll: ctypes.CDLL) -> ctypes.CDLL:
    specs = {
        # エラー・文字列
        "ACS_getLastError":            ([], ACS_Error),
        "ACS_getLastErrorMessage":     ([], ctypes.c_char_p),
        "ACS_getErrorMessage":         ([ACS_Error], _p),
        "ACS_String_get":              ([_p], ctypes.c_char_p),
        "ACS_String_free":             ([_p], None),
        # ログ
        "ACS_Logger_setLevel":         ([ctypes.c_int], None),
        # Discovery
        "ACS_Discovery_alloc":         ([], _p),
        "ACS_Discovery_free":          ([_p], None),
        "ACS_Discovery_scan":          (
            [_p, ctypes.c_uint, _CB_ON_CAM_FOUND, _CB_ON_DISC_ERR,
             _CB_ON_CAM_LOST, _CB_ON_DISC_FIN, _p], None),
        "ACS_DiscoveredCamera_getIdentity":    ([_p], _p),
        "ACS_DiscoveredCamera_getDisplayName": ([_p], ctypes.c_char_p),
        "ACS_Identity_copy":           ([_p], _p),
        "ACS_Identity_free":           ([_p], None),
        # Camera
        "ACS_Camera_alloc":            ([], _p),
        "ACS_Camera_free":             ([_p], None),
        "ACS_Camera_connect":          ([_p, _p, _p, _CB_ON_DISCONN, _p, _p], ACS_Error),
        "ACS_Camera_disconnect":       ([_p], None),
        "ACS_Camera_isConnected":      ([_p], ctypes.c_bool),
        "ACS_Camera_getStreamCount":   ([_p], ctypes.c_size_t),
        "ACS_Camera_getStream":        ([_p, ctypes.c_size_t], _p),
        "ACS_Camera_getRemoteControl": ([_p], _p),
        # Stream
        "ACS_Stream_start":            ([_p, _CB_ON_IMAGE, _CB_ON_ERROR, ACS_CallbackContext], None),
        "ACS_Stream_stop":             ([_p], None),
        "ACS_Stream_isStreaming":       ([_p], ctypes.c_bool),
        "ACS_Stream_isThermal":        ([_p], ctypes.c_bool),
        # ThermalStreamer
        "ACS_ThermalStreamer_alloc_cpu":        ([_p], _p),
        "ACS_ThermalStreamer_free":             ([_p], None),
        "ACS_ThermalStreamer_withThermalImage": ([_p, _CB_WITH_IMG, _p], None),
        # ThermalImage
        "ACS_ThermalImage_saveAs":     ([_p, ctypes.c_wchar_p, ctypes.c_int], None),
        "ACS_ThermalImage_getWidth":   ([_p], ctypes.c_int),
        "ACS_ThermalImage_getHeight":  ([_p], ctypes.c_int),
        # Remote — Focus
        "ACS_Remote_Focus_autofocus_executeSync":             ([_p], ACS_Error),
        "ACS_Remote_Focus_distanceStartDecrease_executeSync": ([_p], ACS_Error),
        "ACS_Remote_Focus_distanceStartIncrease_executeSync": ([_p], ACS_Error),
        "ACS_Remote_Focus_distanceStop_executeSync":          ([_p], ACS_Error),
        # Remote — NUC
        "ACS_Remote_Calibration_nuc_executeSync": ([_p], ACS_Error),
        # Remote — Palette
        "ACS_Remote_Palette_availablePalettes": ([_p], _p),
        "ACS_Remote_Palette_currentPalette":    ([_p], _p),
        "ACS_ListRemotePalette_size":            ([_p], ctypes.c_size_t),
        "ACS_ListRemotePalette_item":            ([_p, ctypes.c_size_t], _p),
        "ACS_RemotePalette_getName":             ([_p], ctypes.c_char_p),
        "ACS_Property_RemotePalette_getSync": ([_p, ctypes.POINTER(_p)], ACS_Error),
        "ACS_Property_RemotePalette_setSync": ([_p, _p], ACS_Error),
        # Remote — Temperature Range
        "ACS_Remote_TemperatureRange_ranges":        ([_p], _p),
        "ACS_Remote_TemperatureRange_selectedIndex": ([_p], _p),
        "ACS_ListTemperatureRange_size": ([_p], ctypes.c_size_t),
        "ACS_ListTemperatureRange_item": ([_p, ctypes.c_size_t], _p),
        # Remote — Thermal Parameters (Emissivity)
        "ACS_Remote_ThermalParameters_objectEmissivity": ([_p], _p),
        # Remote — Camera Information
        "ACS_Remote_CameraInformation_getDisplayName":      ([_p], _p),
        "ACS_Remote_CameraInformation_getSerialNumber":     ([_p], _p),
        "ACS_Remote_CameraInformation_getModelName":        ([_p], _p),
        "ACS_Remote_CameraInformation_getFirmwareRevision": ([_p], _p),
        "ACS_Remote_CameraInformation_getResolutionWidth":  ([_p], _p),
        "ACS_Remote_CameraInformation_getResolutionHeight": ([_p], _p),
        # Property — 汎用ゲッター・セッター
        "ACS_Property_String_getSync": ([_p, ctypes.POINTER(_p)], ACS_Error),
        "ACS_Property_Int_getSync":    ([_p, ctypes.POINTER(ctypes.c_int)], ACS_Error),
        "ACS_Property_Int_setSync":    ([_p, ctypes.c_int], ACS_Error),
        "ACS_Property_Double_getSync": ([_p, ctypes.POINTER(ctypes.c_double)], ACS_Error),
        "ACS_Property_Double_setSync": ([_p, ctypes.c_double], ACS_Error),
    }
    for name, (argtypes, restype) in specs.items():
        try:
            fn = getattr(dll, name)
            fn.argtypes = argtypes
            fn.restype  = restype
        except AttributeError:
            log.debug(f"SDK 関数なし（スキップ）: {name}")
    return dll


# ── 定数 ─────────────────────────────────────────────────────────────────────

ACS_CommunicationInterface_usb = 0x01
ACS_FileFormat_jpeg            = 0   # RJPEG（放射温度データ埋め込み JPEG）
ACS_FileFormat_fff             = 1
ACS_LogLevel_off               = 0


# ── エラーメッセージ日本語対応表 ────────────────────────────────────────────────
# FLIR Atlas C SDK が返す英語メッセージ（安定した errc 列挙体由来）を日本語化する。
# 未知のメッセージは原文を併記してフォールバックする。

_ERROR_JA = {
    # カメラ状態
    "camera ok":                                                   "正常",
    "camera is not connected":                                     "カメラが接続されていません",
    "camera is already streaming":                                 "カメラは既にストリーミング中です",
    "camera not ready error":                                      "カメラの準備ができていません",
    "camera general error":                                        "カメラの一般エラーが発生しました",
    "camera does not support this feature.":                       "カメラがこの機能に対応していません",
    "camera function not yet supported error":                     "カメラがこの機能にまだ対応していません",
    "camera undefined function error":                             "未定義のカメラ機能が呼び出されました",
    "camera is not mounted":                                       "カメラがマウントされていません",
    "camera is upgrading firmware.":                               "カメラがファームウェアを更新中です",
    "camera operation canceled":                                   "カメラ操作がキャンセルされました",
    "camera range error":                                          "カメラの値が範囲外です",
    "camera input data is out of valid range error":              "入力データが有効範囲外です",
    "camera bad argument  error":                                  "カメラへの引数が不正です",
    "camera byte count error":                                     "カメラのバイト数エラーが発生しました",
    "camera checksum error":                                       "カメラのチェックサムエラーが発生しました",
    "camera otp write error":                                      "カメラの OTP 書き込みエラーが発生しました",
    "camera unable to execute command due to current camera state":
        "現在のカメラ状態ではコマンドを実行できません",
    "bad date on camera":                                          "カメラの日時設定が不正です",
    # 接続・ネットワーク・認証
    "authentication failed":                                       "認証に失敗しました",
    "authentication failure":                                      "認証に失敗しました",
    "authentication cancelled":                                    "認証がキャンセルされました",
    "access denied to remote resource":                            "リモートリソースへのアクセスが拒否されました",
    "address already in use":                                      "アドレスは既に使用中です",
    "address in use":                                              "アドレスは既に使用中です",
    "api timeout expired":                                         "通信がタイムアウトしました",
    "accept timeout occurred while waiting server connect":        "サーバー接続待ちでタイムアウトしました",
    # メモリ・内部
    "a memory allocation failure occurred.":                       "メモリの割り当てに失敗しました",
    "a memory function failed":                                    "メモリ処理に失敗しました",
    "an unexpected internal failure occurred":                     "予期しない内部エラーが発生しました",
    "buffer is invalid":                                           "バッファが不正です",
}


def translate_error(eng_msg: str) -> str:
    """SDK の英語エラーメッセージを日本語化する。未知なら原文を返す。"""
    if not eng_msg:
        return ""
    key = eng_msg.strip().lower()
    if key in _ERROR_JA:
        return _ERROR_JA[key]
    # 部分一致フォールバック（SDK が詳細を付加した場合に対応）
    for k, ja in _ERROR_JA.items():
        if k in key:
            return ja
    return eng_msg  # 未知のメッセージは原文のまま


# ── データクラス ──────────────────────────────────────────────────────────────

class CameraInfo:
    def __init__(self):
        self.display_name  = ""
        self.model_name    = ""
        self.serial_number = ""
        self.firmware      = ""
        self.width         = 0
        self.height        = 0

    def __str__(self):
        parts = []
        if self.model_name:    parts.append(self.model_name)
        if self.serial_number: parts.append(f"S/N: {self.serial_number}")
        if self.firmware:      parts.append(f"FW: {self.firmware}")
        if self.width:         parts.append(f"{self.width}×{self.height}")
        return "  |  ".join(parts)


# ── FlirCamera ────────────────────────────────────────────────────────────────

class FlirCamera:
    """USB FLIR カメラの接続・ストリーミング・設定制御クラス"""

    def __init__(self, save_dir: str = "captures", dll_dir: Path = None):
        self._dll = _bind(_load_dll(dll_dir))
        self._dll.ACS_Logger_setLevel(ACS_LogLevel_off)
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

        self._live_path = str(Path(tempfile.gettempdir()) / "flir_viewer_live.jpg")
        self._camera    = None
        self._stream    = None
        self._streamer  = None
        self._remote    = None
        self._connected = False
        self._cb_refs   = []
        self._img_w     = 0
        self._img_h     = 0
        self._frame_cnt = 0
        self._live_ok   = False

        # ライブビュー用固定コールバック（GC防止のためインスタンス変数に保持）
        self._live_cb = _CB_WITH_IMG(self._on_live_frame)
        self._cb_refs.append(self._live_cb)

    # ── 内部コールバック ─────────────────────────────────────────────────────

    def _on_live_frame(self, img_ptr, _ctx):
        if not img_ptr:
            self._live_ok = False
            return
        if self._img_w == 0:
            self._img_w = self._dll.ACS_ThermalImage_getWidth(img_ptr)
            self._img_h = self._dll.ACS_ThermalImage_getHeight(img_ptr)
        self._dll.ACS_ThermalImage_saveAs(img_ptr, self._live_path, ACS_FileFormat_jpeg)
        err = self._dll.ACS_getLastError()
        self._live_ok = (err.code == 0)
        if self._live_ok:
            self._frame_cnt += 1

    # ── 接続 ─────────────────────────────────────────────────────────────────

    def discover_and_connect(self, timeout: float = 15.0) -> CameraInfo:
        identity = self._discover_usb(timeout)
        self._do_connect(identity)
        self._start_stream()
        self._remote = self._dll.ACS_Camera_getRemoteControl(self._camera)
        self._connected = True
        log.info("FLIR カメラ: 準備完了")
        return self._read_camera_info()

    def _discover_usb(self, timeout: float):
        found    = threading.Event()
        id_hold  = [None]
        err_hold = [None]

        @_CB_ON_CAM_FOUND
        def on_found(disc_cam, _ctx):
            if id_hold[0] is not None:
                return
            raw  = self._dll.ACS_DiscoveredCamera_getDisplayName(disc_cam)
            name = raw.decode(errors="replace") if raw else "(不明)"
            log.info(f"カメラ発見: {name}")
            ident      = self._dll.ACS_DiscoveredCamera_getIdentity(disc_cam)
            id_hold[0] = self._dll.ACS_Identity_copy(ident)
            found.set()

        @_CB_ON_DISC_ERR
        def on_disc_err(iface, err, _ctx):
            err_hold[0] = f"カメラ検索エラー: {self._error_detail(err)}"
            found.set()

        self._cb_refs += [on_found, on_disc_err]

        disc = self._dll.ACS_Discovery_alloc()
        try:
            self._dll.ACS_Discovery_scan(
                disc, ACS_CommunicationInterface_usb,
                on_found, on_disc_err, None, None, None)
            if not found.wait(timeout):
                raise TimeoutError(
                    f"FLIR カメラが {timeout:.0f} 秒以内に見つかりませんでした。\n"
                    "USB 接続とカメラの電源を確認してください。")
        finally:
            self._dll.ACS_Discovery_free(disc)

        if err_hold[0]:
            raise RuntimeError(err_hold[0])
        if not id_hold[0]:
            raise RuntimeError("カメラ Identity を取得できませんでした")
        return id_hold[0]

    def _error_detail(self, err) -> str:
        """ACS_Error から日本語のエラー詳細文を組み立てる。"""
        msg_ptr = self._dll.ACS_getErrorMessage(err)
        eng = ""
        if msg_ptr:
            raw = self._dll.ACS_String_get(msg_ptr)
            eng = raw.decode(errors="replace") if raw else ""
            self._dll.ACS_String_free(msg_ptr)
        ja = translate_error(eng)
        # 翻訳できた場合は原文を併記、できなかった場合は原文のみ
        if ja and ja != eng:
            return f"{ja}（原文: {eng}, code={err.code}）"
        return f"{eng or '不明なエラー'}（code={err.code}）"

    def _do_connect(self, identity):
        self._camera = self._dll.ACS_Camera_alloc()

        @_CB_ON_DISCONN
        def on_disconn(err, _ctx):
            self._connected = False
            log.warning(f"カメラが切断されました (code={err.code})")

        self._cb_refs.append(on_disconn)
        err = self._dll.ACS_Camera_connect(
            self._camera, identity, None, on_disconn, None, None)
        self._dll.ACS_Identity_free(identity)
        if err.code:
            raise RuntimeError(f"接続失敗: {self._error_detail(err)}")
        log.info("カメラ接続完了")

    def _start_stream(self):
        count = self._dll.ACS_Camera_getStreamCount(self._camera)
        for i in range(count):
            s = self._dll.ACS_Camera_getStream(self._camera, i)
            if self._dll.ACS_Stream_isThermal(s):
                self._stream = s
                break
        if not self._stream:
            raise RuntimeError("サーマルストリームが見つかりません")

        self._streamer = self._dll.ACS_ThermalStreamer_alloc_cpu(self._stream)
        if not self._streamer:
            raise RuntimeError("ThermalStreamer の作成に失敗しました")

        @_CB_ON_IMAGE
        def on_frame(_ctx):
            pass

        @_CB_ON_ERROR
        def on_err(err, _ctx):
            if err.code:
                log.debug(f"ストリームエラー (code={err.code}) — NUC/FFC の可能性あり")

        self._cb_refs += [on_frame, on_err]
        ctx = ACS_CallbackContext()
        self._dll.ACS_Stream_start(self._stream, on_frame, on_err, ctx)
        log.info("サーマルストリーミング開始")

    # ── フレーム取得 ──────────────────────────────────────────────────────────

    def get_live_frame(self) -> str | None:
        """ライブビュー用 JPEG 一時ファイルのパスを返す（失敗時は None）"""
        if not self._connected or not self._streamer:
            return None
        self._live_ok = False
        self._dll.ACS_ThermalStreamer_withThermalImage(
            self._streamer, self._live_cb, None)
        return self._live_path if self._live_ok else None

    # ── キャプチャ ────────────────────────────────────────────────────────────

    def capture(self, prefix: str = "flir") -> str | None:
        """現在フレームを RJPEG として saves_dir に保存し、パスを返す"""
        if not self._connected or not self._streamer:
            return None
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        path = str(self.save_dir / f"{prefix}_{ts}.jpg")
        saved = [False]

        @_CB_WITH_IMG
        def do_save(img_ptr, _ctx):
            if img_ptr:
                self._dll.ACS_ThermalImage_saveAs(img_ptr, path, ACS_FileFormat_jpeg)
                err    = self._dll.ACS_getLastError()
                saved[0] = (err.code == 0)

        # コールバック参照を一時的に保持（同期呼び出しなので即解放でも安全だが念のため）
        self._cb_refs.append(do_save)
        self._dll.ACS_ThermalStreamer_withThermalImage(self._streamer, do_save, None)
        self._cb_refs.remove(do_save)
        return path if saved[0] else None

    # ── カメラ情報 ────────────────────────────────────────────────────────────

    def _read_camera_info(self) -> CameraInfo:
        info = CameraInfo()
        if not self._remote:
            return info

        def _str(fn_name: str) -> str:
            try:
                prop = getattr(self._dll, fn_name)(self._remote)
                if not prop:
                    return ""
                out = _p()
                err = self._dll.ACS_Property_String_getSync(prop, ctypes.byref(out))
                if err.code or not out.value:
                    return ""
                raw    = self._dll.ACS_String_get(out)
                result = raw.decode(errors="replace") if raw else ""
                self._dll.ACS_String_free(out)
                return result
            except Exception:
                return ""

        def _int(fn_name: str) -> int:
            try:
                prop = getattr(self._dll, fn_name)(self._remote)
                if not prop:
                    return 0
                val = ctypes.c_int(0)
                err = self._dll.ACS_Property_Int_getSync(prop, ctypes.byref(val))
                return val.value if err.code == 0 else 0
            except Exception:
                return 0

        info.display_name  = _str("ACS_Remote_CameraInformation_getDisplayName")
        info.model_name    = _str("ACS_Remote_CameraInformation_getModelName")
        info.serial_number = _str("ACS_Remote_CameraInformation_getSerialNumber")
        info.firmware      = _str("ACS_Remote_CameraInformation_getFirmwareRevision")
        info.width         = _int("ACS_Remote_CameraInformation_getResolutionWidth")
        info.height        = _int("ACS_Remote_CameraInformation_getResolutionHeight")
        return info

    # ── リモート操作ヘルパー ─────────────────────────────────────────────────

    def _exec(self, fn_name: str) -> bool:
        if not self._remote:
            return False
        try:
            err = getattr(self._dll, fn_name)(self._remote)
            if err.code:
                log.warning(f"{fn_name}: エラー code={err.code}")
            return err.code == 0
        except Exception as e:
            log.warning(f"{fn_name}: {e}")
            return False

    # ── フォーカス ────────────────────────────────────────────────────────────

    def autofocus(self) -> bool:
        return self._exec("ACS_Remote_Focus_autofocus_executeSync")

    def focus_near_start(self) -> bool:
        return self._exec("ACS_Remote_Focus_distanceStartDecrease_executeSync")

    def focus_far_start(self) -> bool:
        return self._exec("ACS_Remote_Focus_distanceStartIncrease_executeSync")

    def focus_stop(self) -> bool:
        return self._exec("ACS_Remote_Focus_distanceStop_executeSync")

    # ── NUC ──────────────────────────────────────────────────────────────────

    def trigger_nuc(self) -> bool:
        return self._exec("ACS_Remote_Calibration_nuc_executeSync")

    # ── パレット ──────────────────────────────────────────────────────────────

    def get_palettes(self) -> list[str]:
        if not self._remote:
            return []
        try:
            avail = self._dll.ACS_Remote_Palette_availablePalettes(self._remote)
            if not avail:
                return []
            count = self._dll.ACS_ListRemotePalette_size(avail)
            names = []
            for i in range(count):
                item = self._dll.ACS_ListRemotePalette_item(avail, i)
                raw  = self._dll.ACS_RemotePalette_getName(item) if item else None
                names.append(raw.decode(errors="replace") if raw else f"Palette {i}")
            return names
        except Exception as e:
            log.warning(f"get_palettes: {e}")
            return []

    def get_current_palette(self) -> int:
        if not self._remote:
            return -1
        try:
            avail    = self._dll.ACS_Remote_Palette_availablePalettes(self._remote)
            cur_prop = self._dll.ACS_Remote_Palette_currentPalette(self._remote)
            if not avail or not cur_prop:
                return -1
            cur_ptr = _p()
            err = self._dll.ACS_Property_RemotePalette_getSync(cur_prop, ctypes.byref(cur_ptr))
            if err.code or not cur_ptr.value:
                return -1
            raw      = self._dll.ACS_RemotePalette_getName(cur_ptr.value)
            cur_name = raw.decode(errors="replace") if raw else ""
            count = self._dll.ACS_ListRemotePalette_size(avail)
            for i in range(count):
                item = self._dll.ACS_ListRemotePalette_item(avail, i)
                if item:
                    r = self._dll.ACS_RemotePalette_getName(item)
                    if r and r.decode(errors="replace") == cur_name:
                        return i
            return -1
        except Exception as e:
            log.warning(f"get_current_palette: {e}")
            return -1

    def set_palette(self, index: int) -> bool:
        if not self._remote:
            return False
        try:
            avail    = self._dll.ACS_Remote_Palette_availablePalettes(self._remote)
            cur_prop = self._dll.ACS_Remote_Palette_currentPalette(self._remote)
            if not avail or not cur_prop:
                return False
            item = self._dll.ACS_ListRemotePalette_item(avail, index)
            if not item:
                return False
            err = self._dll.ACS_Property_RemotePalette_setSync(cur_prop, item)
            return err.code == 0
        except Exception as e:
            log.warning(f"set_palette: {e}")
            return False

    # ── 温度レンジ ────────────────────────────────────────────────────────────

    def get_temp_range_count(self) -> int:
        if not self._remote:
            return 0
        try:
            lst = self._dll.ACS_Remote_TemperatureRange_ranges(self._remote)
            return int(self._dll.ACS_ListTemperatureRange_size(lst)) if lst else 0
        except Exception:
            return 0

    def get_current_temp_range(self) -> int:
        if not self._remote:
            return -1
        try:
            prop = self._dll.ACS_Remote_TemperatureRange_selectedIndex(self._remote)
            if not prop:
                return -1
            val = ctypes.c_int(0)
            err = self._dll.ACS_Property_Int_getSync(prop, ctypes.byref(val))
            return val.value if err.code == 0 else -1
        except Exception as e:
            log.warning(f"get_current_temp_range: {e}")
            return -1

    def set_temp_range(self, index: int) -> bool:
        if not self._remote:
            return False
        try:
            prop = self._dll.ACS_Remote_TemperatureRange_selectedIndex(self._remote)
            if not prop:
                return False
            err = self._dll.ACS_Property_Int_setSync(prop, index)
            return err.code == 0
        except Exception as e:
            log.warning(f"set_temp_range: {e}")
            return False

    # ── 放射率 ────────────────────────────────────────────────────────────────

    def get_emissivity(self) -> float:
        if not self._remote:
            return 1.0
        try:
            prop = self._dll.ACS_Remote_ThermalParameters_objectEmissivity(self._remote)
            if not prop:
                return 1.0
            val = ctypes.c_double(1.0)
            err = self._dll.ACS_Property_Double_getSync(prop, ctypes.byref(val))
            return val.value if err.code == 0 else 1.0
        except Exception as e:
            log.warning(f"get_emissivity: {e}")
            return 1.0

    def set_emissivity(self, value: float) -> bool:
        if not self._remote:
            return False
        try:
            prop = self._dll.ACS_Remote_ThermalParameters_objectEmissivity(self._remote)
            if not prop:
                return False
            err = self._dll.ACS_Property_Double_setSync(prop, value)
            return err.code == 0
        except Exception as e:
            log.warning(f"set_emissivity: {e}")
            return False

    # ── 切断 ─────────────────────────────────────────────────────────────────

    def disconnect(self):
        self._connected = False
        for fn, obj in [
            ("ACS_Stream_stop",         self._stream),
            ("ACS_ThermalStreamer_free", self._streamer),
            ("ACS_Camera_free",         self._camera),
        ]:
            if obj:
                try:
                    getattr(self._dll, fn)(obj)
                except Exception:
                    pass
        self._stream   = None
        self._streamer = None
        self._camera   = None
        self._remote   = None
        log.info("切断完了")

    # ── プロパティ ────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def frame_count(self) -> int:
        return self._frame_cnt

    @property
    def image_size(self) -> tuple[int, int]:
        return (self._img_w, self._img_h)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.disconnect()
