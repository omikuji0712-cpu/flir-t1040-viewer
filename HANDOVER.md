# FLIR T1040 Viewer — 引き継ぎメモ（HANDOVER）

最終更新: 2026-07-17（v1.1 時点）

---

## 1. プロジェクト概要

USB 接続した FLIR T1040 サーマルカメラのライブビュー表示・静止画/動画撮影・
カメラ設定変更ができる Windows 用 GUI ソフト。Python + PyQt6 製で、
PyInstaller により単一 exe（Python 不要）として配布している。

- **開発場所**: `E:\Claude\flir_viewer\`
- **GitHub**: https://github.com/omikuji0712-cpu/flir-t1040-viewer （public）
  - アカウント: omikuji0712-cpu（gh CLI で認証済み）
- **配布物**: デスクトップ `FLIR_T1040_Viewer_v1.1_配布キット\`
  （exe + マニュアル docx + はじめにお読みください.txt）

### バージョン履歴（git タグ）

| タグ | 内容 |
|---|---|
| `v1` | 初版：ライブビュー・RJPEG キャプチャ・カメラ設定（フォーカス/パレット/温度レンジ/放射率/NUC）・保存先設定 UI |
| `v1.01` | SDK エラーメッセージの日本語化（`_ERROR_JA` 対応表 + `translate_error()`） |
| `v1.1` | 動画録画（SEQ）と静止画/動画モード切替トグルを追加 |

---

## 2. ファイル構成

```
E:\Claude\flir_viewer\
├── main.py              ← PyQt6 GUI 本体（MainWindow, ConnectWorker, NucWorker）
├── flir_sdk.py          ← Atlas C SDK の ctypes ラッパー（FlirCamera クラス）
├── requirements.txt     ← PyQt6>=6.4.0 のみ
├── flir_viewer.spec     ← PyInstaller spec（--onefile 相当, console=False）
├── make_manual.py       ← マニュアル docx 生成スクリプト（python-docx）
├── HANDOVER.md          ← このファイル
├── .gitignore           ← dist/ build/ captures/ settings.json 等を除外
├── dll\                 ← FLIR Atlas C SDK の DLL 一式（9ファイル, git 管理対象）
│   ├── atlas_c_sdk.dll
│   ├── avcodec-62.dll / avdevice-62.dll / avfilter-11.dll
│   ├── avformat-62.dll / avutil-60.dll / live666.dll
│   ├── swresample-6.dll / swscale-9.dll
├── dist\FLIR_T1040_Viewer.exe   ← ビルド成果物（73MB, git 除外）
└── FLIR_T1040_Viewer_Manual_v1.1.docx  ← マニュアル（git 除外）
```

実行時に exe と同じフォルダへ自動生成されるもの:
- `settings.json` … 保存先フォルダ設定（`save_dir` キー）
- `captures\` … 既定の保存先フォルダ

---

## 3. 使用したソフト・SDK・ライブラリ一覧

### SDK / ネイティブ
| 名称 | バージョン | 入手元 / 場所 | 用途 |
|---|---|---|---|
| FLIR Atlas C SDK | 2.19.0 | `C:\Users\h-mor\Downloads\atlas-c-sdk-windows-vs16-x64-mt-2.19.0.zip` | カメラ制御の中核。DLL は `dll\` に展開済み。**ヘッダー（.h）37本が zip 内にあり、関数シグネチャの正確な確認に必須** |
| FLIR Device Drivers | 1.12.0.0 | FLIR Research Studio に同梱 | T1040 の USB 認識（OS レベル）。実行 PC に必要 |
| FLIR Research Studio | 26.1.6 | FLIR 公式サイト（無償） | ドライバー適用目的でインストール。アプリ本体・ライセンス認証はこのソフトの動作に**不要** |

※ Flir.Atlas.Cronos 7.7.0（.NET NuGet）も Downloads にあるが**未使用**（C SDK を採用）。
※ Spinnaker SDK は**不要**（T1040 はマシンビジョンカメラではないため）。

### Python 環境（開発 PC）
| 名称 | バージョン | 用途 |
|---|---|---|
| Python | 3.13.1 | 開発言語（`C:\Users\h-mor\AppData\Local\Programs\Python\Python313`） |
| PyQt6 | 6.11.0 | GUI フレームワーク（唯一の実行時依存） |
| PyInstaller | 6.20.0 | exe 化（onefile, console なし） |
| python-docx | 1.2.0 | マニュアル docx 生成 |
| ctypes | 標準ライブラリ | atlas_c_sdk.dll の呼び出し |

### ツール
| 名称 | 用途 |
|---|---|
| git / GitHub CLI (gh 2.92.0) | バージョン管理・リポジトリ操作。gh は `C:\Program Files\GitHub CLI`（PATH に追加が必要な場合あり） |

---

## 4. 実装の要点（flir_sdk.py）

### DLL ロード
- `_default_dll_dirs()`: 通常は `スクリプト\dll\`、PyInstaller frozen 時は `sys._MEIPASS\dll\`
- `os.add_dll_directory()` で FFmpeg 系依存 DLL を解決してから `ctypes.CDLL()`

### 重要な構造体・規約
```python
class ACS_Error(ctypes.Structure):          # {code:int, category:void*}
class ACS_CallbackContext(ctypes.Structure): # {context:void*, deleter:void*} ※値渡し
```
- `ACS_Stream_start` は `ACS_CallbackContext` を**値渡し**で受ける
- ファイルパス引数（saveAs / Recorder_start）は `ACS_NativePathChar*` = Windows では `c_wchar_p`
- **コールバックは必ず `self._cb_refs` に保持**（GC されると即クラッシュ）

### 主要フロー
1. **検索**: `ACS_Discovery_scan(usb=0x01)` → `on_found` コールバック → `threading.Event` で同期
   → `ACS_Identity_copy` で identity を確保
2. **接続**: `ACS_Camera_connect(camera, identity, None, on_disconn, None, None)` → 使用後 `ACS_Identity_free`
3. **ストリーム**: `getStreamCount`/`getStream` から `isThermal` なものを選択
   → `ACS_ThermalStreamer_alloc_cpu`（**CPU モード。OpenGL/GPU 不要にするため必須**）
   → `ACS_Stream_start`
4. **ライブビュー**: `ACS_ThermalStreamer_withThermalImage` のコールバック内で
   `ACS_ThermalImage_saveAs(tempdir\flir_viewer_live.jpg, jpeg)` → GUI 側が QPixmap で読む
   （100ms 間隔の QTimer ≒ 10fps）
5. **静止画**: 同上の仕組みで `save_dir\flir_YYYYMMDD_HHMMSS_ms.jpg`（RJPEG＝温度データ内包）
6. **動画 (v1.1)**: `ACS_ThermalSequenceRecorder_alloc` → `ACS_Stream_attachRecorder`
   → `Recorder_start(path.seq)` … `Recorder_stop` → `Stream_detachRecorder` → `Recorder_free`
   - SEQ 形式（FFF フレーム列、全フレーム温度データ付き）
   - **この API はヘッダー上 EXPERIMENTAL 表記**。実機検証は未実施なので注意
   - 状態: `getState` (0=stopped/1=paused/2=recording), `elapsedMilliSeconds`, `getFrameCounter`
7. **リモート設定**: `ACS_Camera_getRemoteControl(camera)` で remote ハンドル取得後、
   - フォーカス: `ACS_Remote_Focus_autofocus_executeSync` / `distanceStartDecrease(Increase)_executeSync` / `distanceStop_executeSync`（近/遠ボタンは press で開始・release で停止）
   - NUC: `ACS_Remote_Calibration_nuc_executeSync`
   - パレット: `availablePalettes`(list) + `currentPalette`(property) を `ACS_Property_RemotePalette_get/setSync`。**現在値の照合は名前文字列比較**（ポインタ比較は不可）
   - 温度レンジ: `ACS_Remote_TemperatureRange_ranges`(list) + `selectedIndex` を `ACS_Property_Int_get/setSync`
   - 放射率: `ACS_Remote_ThermalParameters_objectEmissivity` を `ACS_Property_Double_get/setSync`
   - カメラ情報: `ACS_Remote_CameraInformation_get*` → `ACS_Property_String_getSync` → `ACS_String_get/free`

### エラー日本語化（v1.01）
- `_ERROR_JA` 辞書: SDK の errc 由来英文（小文字化キー）→ 日本語
- `translate_error()`: 完全一致 → 部分一致 → 原文フォールバック
- `_error_detail(err)`: 「日本語（原文: ..., code=N）」形式に整形
- 英文文字列は DLL バイナリから直接抽出して確認済み（"Camera is not connected" 等）

## 5. 実装の要点（main.py）

- `MainWindow`: 左=ライブビュー QLabel、右=QScrollArea 内コントロールパネル（幅300固定）
- スレッド: `ConnectWorker(QThread)` で検索+接続（GUI ブロック回避）、`NucWorker` で NUC
- タイマー: `_live_timer`(100ms, ライブ更新+FPS計測) / `_rec_timer`(500ms, 録画経過表示)
- モード切替 (v1.1): `self._mode` ("photo"/"video")、checkable な QPushButton トグル
  - 録画中はモード切替とモードボタンを無効化
  - 録画中ボタン表示: `⏹ 録画停止` + プロパティ `recording=true` で赤色化
    （`style().unpolish/polish` で再適用）
- 設定永続化: `settings.json`（`load_settings`/`save_settings`、現状 `save_dir` のみ）
- frozen 対応: `_SCRIPT_DIR` は frozen 時 `sys.executable` の親（exe の隣に settings/captures を作るため）
- 切断/終了時: `disconnect()` が録画停止→保存も面倒を見る（`closeEvent` でも呼ぶ）

---

## 6. ビルド・配布手順

```powershell
cd E:\Claude\flir_viewer
python -m PyInstaller flir_viewer.spec --distpath dist --workpath build --noconfirm
# → dist\FLIR_T1040_Viewer.exe (約73MB)
```

- spec のポイント: `dll\*.dll` を `binaries` として `dll/` サブフォルダに同梱、
  不要な PyQt6 モジュール（WebEngine/Multimedia/Qml 等）を excludes、UPX 無効、console=False
- マニュアル生成: `python make_manual.py` → `FLIR_T1040_Viewer_Manual_v1.1.docx`
- 配布キット: exe + マニュアル + はじめにお読みください.txt をフォルダにまとめる
- 実行側 PC の要件: **FLIR Device Drivers のみ**（Python 不要・管理者権限不要・ライセンス認証不要）

### リリース時の git 手順
```powershell
git add <files>; git commit -m "..."
git tag -a v1.X -m "説明"
git push origin master; git push origin v1.X
```

---

## 7. 既知の注意点・未検証事項

1. **実機テスト未実施**: 開発 PC にカメラ接続なしで実装した。特に v1.1 の録画
   （EXPERIMENTAL API）と、パレット/温度レンジ/フォーカスの Remote 系は実機確認が必要。
2. `ACS_Remote_*` 関数のシグネチャは DLL エクスポート + SDK zip 内ヘッダーで確認済みだが、
   `_bind()` は存在しない関数を warning でスキップする防御実装になっている。
3. 温度レンジの表示名は取得未実装（"レンジ 0" などの汎用ラベル。
   `ACS_ListTemperatureRange_item` から実際の範囲値を読む改善余地あり）。
4. コンソールに日本語を print すると cp932 で文字化けする（動作には無影響）。
   デバッグ時は UTF-8 でファイルに書くか `io.TextIOWrapper(..., encoding='utf-8')`。
5. exe は未署名のため SmartScreen 警告が出る（マニュアルに対処記載済み）。
6. DLL 再配布: Research Studio 本体の EULA は再配布禁止だが、Atlas C SDK は開発者向け
   配布物。厳密には SDK zip 内の EULA 要確認。
7. 保存先 `.seq` は FLIR 専用形式。一般プレイヤーでは再生不可（マニュアル記載済み）。

## 8. 今後の拡張候補

- 温度レンジ名の実値表示（ranges リストから min/max 読み出し）
- スポット温度計測（`ACS_Remote_Measurements_addSpot` 系 / hotSpot・coldSpot）
- 録画の一時停止/再開ボタン（SDK の pause/resume は実装済みバインド済み）
- MSX・フュージョン表示切替（`ACS_Remote_Fusion_*`）
- RF-603 シャッター連携（`E:\Claude\flir_bridge\` の keyboard/F13 方式を統合）

## 9. 関連プロジェクト

- `E:\Claude\flir_bridge\` … RF-603 リモコン（F13 キー）→ RJPEG 撮影する CLI 版（先行開発）。
  DLL はここからコピーした。listener.py + flir_capture.py 構成。
- `E:\Claude\shutter_bridge\` … Canon カメラ版シャッターブリッジ（原型プロジェクト）。
