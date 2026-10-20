#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcode.py — ffmpeg-GUI в стиле Win98 (dark).
"""

from __future__ import annotations

import ctypes
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog, messagebox

# === РЕСУРСЫ И FFMPEG (для работы из исходников и из PyInstaller-сборки) ===

def resource_path(rel: str) -> str:
    """Путь к ресурсу: рядом со скриптом (dev) или в _MEIPASS (PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def ffmpeg_dir() -> str:
    """Папка, где лежат ffmpeg.exe и ffprobe.exe."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "ffmpeg")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg")


# Кладём папку с ffmpeg в начало PATH, чтобы subprocess находил
# "ffmpeg" и "ffprobe" по имени без изменения остального кода.
_ff_dir = ffmpeg_dir()
if os.path.isdir(_ff_dir):
    os.environ["PATH"] = _ff_dir + os.pathsep + os.environ.get("PATH", "")

# ==============================================================================

# === СКРЫТИЕ КОНСОЛИ ПИТОНА ===
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Transcode98.App")
        if sys.executable.endswith("python.exe"):
            kernel32 = ctypes.WinDLL('kernel32')
            user32 = ctypes.WinDLL('user32')
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                user32.ShowWindow(hwnd, 0)
    except Exception:
        pass
# ==============================

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
    _BaseTk = TkinterDnD.Tk
except Exception:
    DND_FILES = None
    TkinterDnD = None
    _DND_AVAILABLE = False
    _BaseTk = tk.Tk


APP_TITLE = "Transcode 98"

# --------------------------------------------------------------------- палитра
BG          = "#3a3a3a"
BG_DEEP     = "#2a2a2a"
FIELD_BG    = "#1c1c1c"
FIELD_FG    = "#d8d8d8"
BTN_FACE    = "#4a4a4a"
BTN_FACE_HI = "#565656"
BTN_LIGHT   = "#6e6e6e"
BTN_SHADOW  = "#1e1e1e"
TEXT        = "#e0e0e0"
TEXT_DIM    = "#a0a0a0"
DISABLED_FG = "#777777"
ACCENT      = "#4d6a99"   # мягкий синий
GREEN       = "#4dff4d"   # яркий зелёный

FONT_UI   = ("MS Sans Serif", 9)
FONT_BOLD = ("MS Sans Serif", 9, "bold")
FONT_MONO = ("Consolas", 9)

CODEC_CHOICES = (
    ("AV1 (Discord) — MP4",   "av1",  "mp4"),
    ("VP9 (YouTube) — WebM",  "vp9",  "webm"),
    ("HEVC (libx265) — MP4",  "hevc", "mp4"),
)

MB_TO_MBIT = 8.388608
AUDIO_RESERVE_MBIT = 0.25

TARGET_MIN_MB        = 1
TARGET_SLIDER_MAX_MB = 90
TARGET_DEFAULT_MB    = 18

ARCHIVE_DIR_NAME = "old_material"
INPUT_GROUP_TITLE = "Входной файл — можно перетащить в окно"
DROP_HIGHLIGHT_BG = "#26384f"

# Поддерживаемые расширения для вставки из буфера
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts", ".flv",
    ".wmv", ".mpg", ".mpeg", ".3gp", ".ogv", ".mts", ".m2ts"
}

# Флаги для запуска ffmpeg без окон
_POPEN_KWARGS = {}
if sys.platform == "win32":
    _POPEN_KWARGS = {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": subprocess.STARTUPINFO()
    }
    _POPEN_KWARGS["startupinfo"].dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _POPEN_KWARGS["startupinfo"].wShowWindow = subprocess.SW_HIDE


# ------------------------------------------------------------------- утилиты GUI

def get_clipboard_files() -> list[str]:
    """Извлекает список файлов из буфера обмена Windows (CF_HDROP)."""
    if sys.platform != "win32":
        return []
    try:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        
        if not user32.OpenClipboard(None):
            return []
        try:
            CF_HDROP = 15
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return []
            
            h_drop = user32.GetClipboardData(CF_HDROP)
            if not h_drop:
                return []
            
            count = shell32.DragQueryFileW(ctypes.c_void_p(h_drop), 0xFFFFFFFF, None, 0)
            files = []
            for i in range(count):
                length = shell32.DragQueryFileW(ctypes.c_void_p(h_drop), i, None, 0)
                buf = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(ctypes.c_void_p(h_drop), i, buf, length + 1)
                files.append(buf.value)
            return files
        finally:
            user32.CloseClipboard()
    except Exception as e:
        print("Clipboard read error:", e)
        return []


def make_button(parent, text, command=None, width=None):
    b = tk.Button(
        parent, text=text, command=command,
        bg=BTN_FACE, fg=TEXT,
        activebackground=BTN_FACE_HI, activeforeground="#ffffff",
        disabledforeground=DISABLED_FG,
        relief="raised", bd=2, highlightthickness=1,
        highlightbackground="#555555", highlightcolor="#777777",
        font=FONT_UI, padx=8, pady=2, cursor="hand2", takefocus=True,
    )
    if width:
        b.configure(width=width)
    return b


def make_entry(parent, textvariable, width=None):
    e = tk.Entry(
        parent, textvariable=textvariable,
        bg=FIELD_BG, fg=FIELD_FG, insertbackground=FIELD_FG,
        disabledbackground=FIELD_BG, disabledforeground=DISABLED_FG,
        relief="sunken", bd=2, highlightthickness=0,
        font=FONT_UI, selectbackground=ACCENT, selectforeground="#ffffff",
        justify="center", takefocus=True,
    )
    if width:
        e.configure(width=width)
    return e


def make_radio(parent, text, variable, value):
    return tk.Radiobutton(
        parent, text=text, variable=variable, value=value,
        bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT,
        selectcolor=FIELD_BG, disabledforeground=DISABLED_FG,
        font=FONT_UI, highlightthickness=0, bd=0, relief="flat",
        takefocus=True,
    )


def make_check(parent, text, variable, command=None):
    return tk.Checkbutton(
        parent, text=text, variable=variable, command=command,
        bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT,
        selectcolor=FIELD_BG, disabledforeground=DISABLED_FG,
        font=FONT_UI, highlightthickness=0, bd=0, relief="flat",
        cursor="hand2", takefocus=True,
    )


def make_group(parent, title):
    return tk.LabelFrame(
        parent, text=f" {title} ",
        bg=BG, fg=TEXT, relief="groove", bd=2,
        font=FONT_BOLD, labelanchor="nw",
    )


# ------------------------------------------------------------------ утилиты ffmpeg

def _parse_hms(s: str) -> float:
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    return float(s)


def _fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def _fmt_size(b: float) -> str:
    if b <= 0:
        return "—"
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} ПБ"


def _fmt_fps(f: float) -> str:
    if f <= 0:
        return "—"
    if abs(f - round(f)) < 0.01:
        return f"{int(round(f))}"
    return f"{f:.3f}".rstrip("0").rstrip(".")


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def probe_info(path: str) -> dict:
    info = {
        "duration": 0.0,
        "size_bytes": 0,
        "bitrate": 0.0,
        "vcodec": "",
        "acodec": "",
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "total_frames": 0,
    }
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries",
             "format=duration,bit_rate,size:"
             "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames",
             "-of", "json", path],
            capture_output=True, text=True, timeout=20,
            **_POPEN_KWARGS
        )
        data = json.loads(r.stdout or "{}")
    except Exception:
        return info

    fmt = data.get("format", {}) or {}
    try:
        info["duration"] = float(fmt.get("duration", 0) or 0)
    except Exception:
        pass
    try:
        info["size_bytes"] = int(fmt.get("size", 0) or 0)
    except Exception:
        pass
    try:
        info["bitrate"] = float(fmt.get("bit_rate", 0) or 0) / 1_000_000
    except Exception:
        pass

    for st in data.get("streams", []) or []:
        ctype = st.get("codec_type")
        if ctype == "video" and not info["vcodec"]:
            info["vcodec"] = (st.get("codec_name") or "").upper()
            try:
                info["width"] = int(st.get("width", 0) or 0)
                info["height"] = int(st.get("height", 0) or 0)
            except Exception:
                pass
            fr = st.get("r_frame_rate", "0/1")
            try:
                num, den = fr.split("/")
                num_f, den_f = float(num), float(den)
                if den_f > 0:
                    info["fps"] = num_f / den_f
            except Exception:
                pass
            try:
                info["total_frames"] = int(st.get("nb_frames", 0) or 0)
            except Exception:
                pass
            if info["total_frames"] <= 0 and info["fps"] > 0 and info["duration"] > 0:
                info["total_frames"] = int(round(info["duration"] * info["fps"]))
        elif ctype == "audio" and not info["acodec"]:
            info["acodec"] = (st.get("codec_name") or "").upper()

    return info


def with_progress(cmd: list[str]) -> list[str]:
    return [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]


# ------------------------------------------------ прогресс на иконке в панели задач

class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class TaskbarProgress:
    NOPROGRESS    = 0x0
    INDETERMINATE = 0x1
    NORMAL        = 0x2
    ERROR         = 0x4
    PAUSED        = 0x8

    _CLSID_TASKBARLIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
    _IID_TASKBARLIST3  = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"

    def __init__(self, root: tk.Misc):
        self.root = root
        self._obj = None
        self._hwnd = None
        self._release = None
        self._set_value = None
        self._set_state = None
        self._last_value = -1
        self._last_state = None
        self._co_initialized = False

        if sys.platform != "win32":
            return
        try:
            ole32 = ctypes.windll.ole32
            hr = ole32.CoInitializeEx(None, 2)
            self._co_initialized = (hr == 0)
            self._connect()
        except Exception as exc:
            print("Taskbar progress unavailable:", exc)

    @property
    def available(self) -> bool:
        return self._obj is not None

    @classmethod
    def _guid(cls, text: str) -> _GUID:
        g = _GUID()
        hr = ctypes.windll.ole32.CLSIDFromString(
            ctypes.c_wchar_p(text), ctypes.byref(g))
        if hr < 0:
            raise OSError(f"CLSIDFromString HRESULT 0x{hr & 0xFFFFFFFF:08X}")
        return g

    def _connect(self):
        ole32 = ctypes.windll.ole32
        clsid = self._guid(self._CLSID_TASKBARLIST)
        iid = self._guid(self._IID_TASKBARLIST3)
        obj = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid), None, 1,
            ctypes.byref(iid), ctypes.byref(obj))
        if hr != 0 or not obj:
            raise OSError(
                f"ITaskbarList3 недоступен (HRESULT 0x{hr & 0xFFFFFFFF:08X})")

        vtbl = ctypes.cast(
            obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        hrint = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[3])
        if hrint(obj) != 0:
            raise OSError("ITaskbarList::HrInit failed")

        self._obj = obj
        self._set_value = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, wintypes.HWND,
            ctypes.c_ulonglong, ctypes.c_ulonglong)(vtbl[9])
        self._set_state = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, wintypes.HWND,
            ctypes.c_int)(vtbl[10])
        self._release = ctypes.WINFUNCTYPE(
            ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])

    def _get_hwnd(self):
        if self._hwnd:
            return self._hwnd
        try:
            self.root.update_idletasks()
            wid = self.root.winfo_id()
            hwnd = ctypes.windll.user32.GetAncestor(
                wintypes.HWND(wid), 2)
            if not hwnd:
                hwnd = ctypes.windll.user32.GetParent(wintypes.HWND(wid))
            self._hwnd = int(hwnd or wid)
        except Exception:
            return None
        return self._hwnd

    def set_state(self, state: int):
        if not self.available or state == self._last_state:
            return
        hwnd = self._get_hwnd()
        if not hwnd:
            return
        try:
            if self._set_state(self._obj, hwnd, int(state)) == 0:
                self._last_state = state
        except Exception:
            pass

    def set_value(self, frac: float):
        if not self.available:
            return
        value = int(max(0.0, min(1.0, float(frac))) * 1000)
        if value == self._last_value:
            return
        hwnd = self._get_hwnd()
        if not hwnd:
            return
        try:
            if self._set_value(self._obj, hwnd, value, 1000) == 0:
                self._last_value = value
        except Exception:
            pass

    def begin(self, frac: float = 0.0):
        self._last_value = -1
        self.set_state(self.NORMAL)
        self.set_value(frac)

    def update(self, frac: float):
        self.set_state(self.NORMAL)
        self.set_value(frac)

    def error(self):
        self.set_state(self.ERROR)

    def clear(self):
        self.set_state(self.NOPROGRESS)
        self._last_value = -1

    def close(self):
        if self.available:
            try:
                self.clear()
                self._release(self._obj)
            except Exception:
                pass
        self._obj = None
        if self._co_initialized:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass
            self._co_initialized = False


# ------------------------------------------------ перенос исходника в old_material

def archive_source(src: str, archive_dir: Path | None = None) -> str | None:
    src_path = Path(src).resolve()
    source_dir = src_path.parent

    if archive_dir is not None:
        dest_dir = Path(archive_dir)
    elif source_dir.name.lower() == ARCHIVE_DIR_NAME:
        dest_dir = source_dir
    else:
        dest_dir = source_dir / ARCHIVE_DIR_NAME

    try:
        already_there = src_path.parent == dest_dir.resolve()
    except OSError:
        already_there = False
    if already_there:
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / src_path.name
    if dest.exists():
        stem, suffix = src_path.stem, src_path.suffix
        for n in range(1, 10000):
            candidate = dest_dir / f"{stem}_{n}{suffix}"
            if not candidate.exists():
                dest = candidate
                break
        else:
            raise OSError("не удалось подобрать свободное имя в old_material")

    try:
        shutil.move(str(src_path), str(dest))
    except Exception:
        if src_path.exists():
            try:
                if dest.exists():
                    dest.unlink()
            except OSError:
                pass
        raise

    return str(dest)


# ------------------------------------------------------------- построение команд

def build_commands(codec: str, inp: str, out: str,
                   quality, two_pass: bool, target_mode: bool = False):
    null = os.devnull

    if codec == "av1":
        br = f"{float(quality):g}M"
        if not two_pass:
            return [[
                "ffmpeg", "-y", "-i", inp,
                "-c:v", "libsvtav1", "-preset", "4",
                "-b:v", br, "-g", "30", "-pix_fmt", "yuv420p",
                "-c:a", "copy", out,
            ]]
        return [
            ["ffmpeg", "-y", "-i", inp,
             "-c:v", "libsvtav1", "-preset", "8",
             "-b:v", br, "-g", "30", "-pix_fmt", "yuv420p",
             "-pass", "1", "-an", "-f", "null", null],
            ["ffmpeg", "-y", "-i", inp,
             "-c:v", "libsvtav1", "-preset", "2",
             "-b:v", br, "-g", "30", "-pix_fmt", "yuv420p",
             "-pass", "2", "-c:a", "copy", out],
        ]

    if codec == "vp9":
        br = f"{float(quality):g}M"
        common = [
            "-c:v", "libvpx-vp9",
            "-b:v", br, "-maxrate", br, "-bufsize", "24M",
            "-g", "30", "-pix_fmt", "yuv420p",
            "-row-mt", "1", "-tile-columns", "2", "-cpu-used", "4",
        ]
        if not two_pass:
            return [["ffmpeg", "-y", "-i", inp, *common,
                     "-c:a", "libopus", "-b:a", "192k", "-ar", "48000", out]]
        return [
            ["ffmpeg", "-y", "-i", inp, *common,
             "-pass", "1", "-an", "-f", "null", null],
            ["ffmpeg", "-y", "-i", inp, *common,
             "-pass", "2",
             "-c:a", "libopus", "-b:a", "192k", "-ar", "48000", out],
        ]

    if codec == "hevc":
        if target_mode:
            br = f"{float(quality):g}M"
            if not two_pass:
                return [["ffmpeg", "-y", "-i", inp,
                         "-c:v", "libx265", "-preset", "medium",
                         "-b:v", br, "-g", "30", "-pix_fmt", "yuv420p",
                         "-c:a", "copy", out]]
            return [
                ["ffmpeg", "-y", "-i", inp,
                 "-c:v", "libx265", "-preset", "medium",
                 "-b:v", br, "-g", "30", "-pix_fmt", "yuv420p",
                 "-x265-params", "pass=1", "-an", "-f", "null", null],
                ["ffmpeg", "-y", "-i", inp,
                 "-c:v", "libx265", "-preset", "medium",
                 "-b:v", br, "-g", "30", "-pix_fmt", "yuv420p",
                 "-x265-params", "pass=2", "-c:a", "copy", out],
            ]

        crf = int(quality)
        return [["ffmpeg", "-y", "-i", inp,
                 "-c:v", "libx265", "-preset", "medium",
                 "-crf", str(crf), "-g", "30", "-pix_fmt", "yuv420p",
                 "-c:a", "copy", out]]

    raise ValueError(f"Неизвестный кодек: {codec}")


# ------------------------------------------------------------------------- окно

class TranscodeApp(_BaseTk):
    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("960x800")
        self.minsize(820, 680)
        self.configure(bg=BG)

        ICON_ICO_PATH = resource_path("wm_4.ico")
        ICON_PNG_PATH = resource_path("wm_4.png")

        if sys.platform == "win32" and os.path.exists(ICON_ICO_PATH):
            try:
                self.iconbitmap(default=ICON_ICO_PATH)
                self.iconbitmap(ICON_ICO_PATH)
            except Exception as e:
                print("iconbitmap failed:", e)
        elif sys.platform != "win32":
            if os.path.exists(ICON_PNG_PATH):
                try:
                    # В Linux используем PNG через iconphoto
                    icon_img = tk.PhotoImage(file=ICON_PNG_PATH)
                    self.iconphoto(True, icon_img)
                    self._icon_img = icon_img  # сохраняем ссылку, чтобы не удалилась сборщиком мусора
                except Exception as e:
                    print("iconphoto failed:", e)
            else:
                print("Иконка .png не найдена, используется стандартная.")
                
        self._running = False

        self._running = False
        self._cancel = False
        self._proc: subprocess.Popen | None = None
        self._duration = 0.0
        self._total_frames = 0
        self._syncing_size = False
        self._taskbar_clear_id = None
        self._output_dir: str | None = None
        self._last_output: str | None = None
        
        self._current_status_text = "Готов."
        self._current_status_highlight = None

        self._build_ui()

        self.codec_var.set(CODEC_CHOICES[0][0])
        self.file_var.trace_add("write", self._on_file_change)

        self._taskbar = TaskbarProgress(self)
        self._setup_dnd()
        self._setup_keys()

        if initial_file:
            self._set_input_file(initial_file)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("Готов к работе. Перетащите файл в окно, вставьте из буфера (Ctrl+V) или нажмите «Обзор…».\n")
        if _DND_AVAILABLE:
            self._log("Drag-and-drop включён: файл можно бросить в любое место окна.\n")
        else:
            self._log("tkinterdnd2 не установлен — drag-and-drop недоступен "
                      "(pip install tkinterdnd2).\n")
        self._log("При включённой галочке исходник переносится в old_material "
                  "рядом с исходным видео.\n")
        self.set_status("Готов.")

    # -------------------------------------------------------------- построение
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        self.grp_in = make_group(self, INPUT_GROUP_TITLE)
        self.grp_in.pack(fill="x", **pad)
        self.file_var = tk.StringVar()
        self.file_entry = make_entry(self.grp_in, self.file_var)
        self.file_entry.configure(justify="left")
        self.file_entry.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        make_button(self.grp_in, "Обзор…", self._browse).pack(
            side="left", padx=(0, 6), pady=6)

        grp = make_group(self, "Параметры")
        grp.pack(fill="x", **pad)

        inner = tk.Frame(grp, bg=BG)
        inner.pack(fill="x", padx=6, pady=6)

        left = tk.Frame(inner, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        left.columnconfigure(1, weight=1)

        tk.Label(left, text="Кодек:", bg=BG, fg=TEXT, font=FONT_UI).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        self.codec_var = tk.StringVar()
        self.codec_menu = tk.OptionMenu(
            left, self.codec_var, *[c[0] for c in CODEC_CHOICES])
        self.codec_menu.configure(
            bg=BTN_FACE, fg=TEXT,
            activebackground=BTN_FACE_HI, activeforeground="#ffffff",
            relief="raised", bd=2, highlightthickness=1,
            highlightbackground="#555555", highlightcolor="#777777",
            font=FONT_UI, width=24, anchor="w", padx=8, pady=2, cursor="hand2",
            takefocus=True)
        self.codec_menu["menu"].configure(
            bg=BTN_FACE, fg=TEXT,
            activebackground=ACCENT, activeforeground="#ffffff",
            font=FONT_UI,
            bd=0,
            activeborderwidth=0,
            relief="flat",
        )
        self.codec_menu.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self.quality_label = tk.Label(
            left, text="Битрейт видео (Мбит/с):",
            bg=BG, fg=TEXT, font=FONT_UI)
        self.quality_label.grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.quality_var = tk.StringVar(value="8")
        self.quality_entry = make_entry(left, self.quality_var, width=10)
        self.quality_entry.configure(
            justify="left",
            validate="key",
            validatecommand=(self.register(self._validate_quality_entry), "%P")
        )
        self.quality_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        self.target_enabled_var = tk.BooleanVar(value=False)
        self.target_cb = make_check(
            left,
            "Задать целевой размер файла (МБ) вместо битрейта",
            self.target_enabled_var,
            command=self._on_target_toggle,
        )
        self.target_cb.grid(row=2, column=0, columnspan=2,
                            sticky="w", padx=6, pady=(8, 0))

        size_row = tk.Frame(left, bg=BG)
        size_row.grid(row=3, column=0, columnspan=2,
                      sticky="ew", padx=6, pady=(2, 0))

        self.target_size_var = tk.IntVar(value=TARGET_DEFAULT_MB)
        self.slider_var      = tk.IntVar(value=TARGET_DEFAULT_MB)

        self.target_scale = tk.Scale(
            size_row,
            from_=TARGET_MIN_MB, to=TARGET_SLIDER_MAX_MB, resolution=1,
            orient="horizontal",
            variable=self.slider_var,
            showvalue=False,
            bg=BTN_FACE, fg=TEXT,
            troughcolor=BG_DEEP,
            activebackground=ACCENT,
            highlightthickness=0,
            bd=2, relief="sunken",
            sliderrelief="raised",
            font=FONT_UI,
            length=320,
            command=self._on_slider_move,
            takefocus=True,
        )
        self.target_scale.pack(side="left", fill="x", expand=True)

        self.target_entry_var = tk.StringVar(value=str(TARGET_DEFAULT_MB))
        self.target_entry = make_entry(size_row, self.target_entry_var, width=6)
        self.target_entry.configure(
            validate="key",
            validatecommand=(self.register(self._validate_target_entry), "%P")
        )
        self.target_entry.pack(side="left", padx=(8, 0))
        tk.Label(size_row, text="МБ", bg=BG, fg=TEXT, font=FONT_UI).pack(
            side="left", padx=(4, 0))

        self.target_entry_var.trace_add("write", self._on_entry_change)
        self.target_entry.bind("<Return>", lambda _e: self._update_target_label())
        self.target_entry.bind("<FocusOut>", lambda _e: self._normalize_entry())

        self.target_info_var = tk.StringVar(value="")
        tk.Label(left, textvariable=self.target_info_var,
                 bg=BG, fg=TEXT_DIM, font=FONT_UI, anchor="w").grid(
            row=4, column=0, columnspan=2,
            sticky="w", padx=6, pady=(0, 6))

        tk.Label(left, text="Проходы:", bg=BG, fg=TEXT, font=FONT_UI).grid(
            row=5, column=0, sticky="w", padx=6, pady=4)
        passes = tk.Frame(left, bg=BG)
        passes.grid(row=5, column=1, sticky="w", padx=6, pady=4)
        self.pass_var = tk.IntVar(value=1)
        self.pass1_rb = make_radio(passes, "Однопроход", self.pass_var, 1)
        self.pass1_rb.pack(side="left")
        self.pass2_rb = make_radio(passes, "Двупроход", self.pass_var, 2)
        self.pass2_rb.pack(side="left", padx=(12, 0))

        self.cleanup_var = tk.BooleanVar(value=False)
        self.cleanup_cb = make_check(
            left,
            "После успеха: исходник → old_material рядом с видео",
            self.cleanup_var,
        )
        self.cleanup_cb.grid(row=6, column=0, columnspan=2,
                             sticky="w", padx=6, pady=(10, 2))
        self.cleanup_cb.bind("<Enter>", self._on_cleanup_hover)
        self.cleanup_cb.bind("<Leave>", self._on_cleanup_unhover)

        right = tk.LabelFrame(
            inner, text=" Информация о видео ",
            bg=BG, fg=TEXT, relief="groove", bd=2,
            font=FONT_BOLD, labelanchor="nw",
        )
        right.pack(side="right", fill="y", padx=(16, 0))

        info_rows = [
            ("Файл",         "file"),
            ("Длительность", "duration"),
            ("Кадров",       "frames"),
            ("Разрешение",   "res"),
            ("FPS",          "fps"),
            ("Видео",        "vcodec"),
            ("Аудио",        "acodec"),
            ("Битрейт",      "bitrate"),
            ("Размер",       "size"),
        ]
        self.info_vars: dict[str, tk.StringVar] = {}
        for i, (label, key) in enumerate(info_rows):
            tk.Label(right, text=label + ":",
                     bg=BG, fg=TEXT_DIM, font=FONT_UI,
                     anchor="w", width=12).grid(
                row=i, column=0, sticky="w", padx=(8, 6), pady=2)
            v = tk.StringVar(value="—")
            self.info_vars[key] = v
            tk.Label(right, textvariable=v,
                     bg=BG, fg=TEXT, font=FONT_UI,
                     anchor="w").grid(
                row=i, column=1, sticky="w", padx=(0, 12), pady=2)

        self.codec_var.trace_add("write", lambda *_: self._on_codec_change())

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", **pad)
        self.start_btn = make_button(actions, "▶  Запустить", self._start, width=14)
        self.start_btn.pack(side="left")
        self.cancel_btn = make_button(actions, "■  Отмена", self._cancel_job, width=10)
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.cancel_btn.configure(state="disabled")

        prog_frame = tk.Frame(self, bg=BG)
        prog_frame.pack(fill="x", padx=10, pady=(0, 2))
        self.progress_holder = tk.Frame(prog_frame, bg=BG_DEEP,
                                        relief="sunken", bd=2, height=18)
        self.progress_holder.pack(fill="x", expand=True)
        self.progress_holder.pack_propagate(False)
        self.progress_fill = tk.Frame(self.progress_holder, bg=ACCENT)
        self.progress_fill.place(x=0, y=0, relwidth=0.0, relheight=1.0)

        status_row = tk.Frame(self, bg=BG)
        status_row.pack(fill="x", padx=12, pady=(2, 4))
        
        self.status_text = tk.Text(status_row, height=1, bg=BG, fg=TEXT_DIM, 
                                   font=FONT_UI, bd=0, highlightthickness=0, 
                                   wrap="none", cursor="arrow", takefocus=0,
                                   padx=0, pady=0)
        self.status_text.pack(side="left", fill="x", expand=True)
        self.status_text.tag_configure("green", foreground=GREEN, font=FONT_BOLD)
        self.status_text.configure(state="disabled")
        
        self.open_loc_btn = make_button(status_row, "Открыть местоположение", self._open_location)

        grp_log = make_group(self, "Журнал")
        grp_log.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(
            grp_log, wrap="none", height=10,
            bg=FIELD_BG, fg=FIELD_FG, insertbackground=FIELD_FG,
            relief="sunken", bd=2, highlightthickness=0, font=FONT_MONO,
            selectbackground=ACCENT, selectforeground="#ffffff",
            takefocus=0,
        )
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb = tk.Scrollbar(grp_log, command=self.log.yview,
                          bg=BTN_FACE, activebackground=BTN_FACE_HI,
                          troughcolor=BG_DEEP, relief="raised", bd=2,
                          highlightthickness=0)
        sb.pack(side="right", fill="y", padx=(0, 6), pady=6)
        self.log.configure(yscrollcommand=sb.set, state="disabled")

        self._refresh_target_state()
        self._refresh_pass_state()
        self._update_target_label()
        self._reset_info()

    def _validate_quality_entry(self, new_text):
        if not new_text:
            return True
        clean = new_text.replace(',', '.')
        if clean.count('.') > 1:
            return False
        for char in clean:
            if not char.isdigit() and char != '.':
                return False
        return True

    def _validate_target_entry(self, new_text):
        if not new_text:
            return True
        return new_text.isdigit()

    def set_status(self, text: str, highlight: str | None = None):
        self._current_status_text = text
        self._current_status_highlight = highlight
        
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        if highlight and highlight in text:
            parts = text.split(highlight)
            self.status_text.insert("end", parts[0])
            self.status_text.insert("end", highlight, "green")
            self.status_text.insert("end", parts[1] if len(parts) > 1 else "")
        else:
            self.status_text.insert("end", text)
        self.status_text.configure(state="disabled")

    def _setup_keys(self):
        self.bind("<Return>", self._on_enter_key)
        self.bind("<KP_Enter>", self._on_enter_key)
        self.bind("<Up>", lambda e: self._move_focus("prev"))
        self.bind("<Down>", lambda e: self._move_focus("next"))
        self.bind("<Left>", lambda e: self._move_focus("prev"))
        self.bind("<Right>", lambda e: self._move_focus("next"))
        
        # Обработка Ctrl+A/C/V/X по VK-коду (независимо от раскладки)
        self.bind_all("<Control-KeyPress>", self._on_ctrl_key)

    def _on_ctrl_key(self, event):
        w = event.widget
        if not isinstance(w, (tk.Entry, tk.Text)):
            return
            
        if event.keycode == 65:  # VK_A
            if isinstance(w, tk.Text):
                w.tag_add("sel", "1.0", "end")
                w.mark_set("insert", "end")
            else:
                w.select_range(0, "end")
                w.icursor("end")
            return "break"
        elif event.keycode == 67:  # VK_C
            w.event_generate("<<Copy>>")
            return "break"
        elif event.keycode == 88:  # VK_X
            w.event_generate("<<Cut>>")
            return "break"
        elif event.keycode == 86:  # VK_V
            self._handle_paste(w)
            return "break"

    def _handle_paste(self, w):
        # 1. Ищем файлы в буфере (из Проводника)
        files = get_clipboard_files()
        valid_files = [f for f in files if Path(f).suffix.lower() in VIDEO_EXTENSIONS] if files else []
        
        # 2. Если файлов нет, проверяем текст (вдруг это путь)
        if not valid_files:
            try:
                text = self.clipboard_get()
                if text:
                    text = text.strip().strip('"').strip("'")
                    if os.path.isfile(text) and Path(text).suffix.lower() in VIDEO_EXTENSIONS:
                        valid_files.append(text)
            except tk.TclError:
                pass

        # 3. Если нашли видеофайл, подставляем его
        if valid_files:
            if self._running:
                self.set_status("Идёт транскодирование — дождитесь окончания.")
                return
            target_file = valid_files[0]
            self._set_input_file(target_file, user_selected=True)
            self.set_status(f"Вставлен файл: {os.path.basename(target_file)}")
            self._log(f"Вставлен файл из буфера: {target_file}\n")
            return
            
        # 4. Если это просто текст и фокус на поле пути — заменяем путь целиком
        if w == self.file_entry:
            try:
                text = self.clipboard_get()
                if text:
                    self.file_var.set(text.strip())
                    return
            except tk.TclError:
                pass
                
        # 5. Иначе делаем стандартную вставку (сработает валидация цифр в полях)
        w.event_generate("<<Paste>>")

    def _on_enter_key(self, event):
        w = self.focus_get()
        if isinstance(w, (tk.Button, tk.Checkbutton, tk.Radiobutton)):
            w.invoke()
            return "break"
        else:
            if not self._running:
                self._start()
            return "break"

    def _move_focus(self, direction):
        w = self.focus_get()
        if w is None:
            self.start_btn.focus_set()
            return "break"
            
        if isinstance(w, (tk.Entry, tk.Text, tk.Scale, tk.Spinbox)):
            return
            
        if direction == "next":
            next_w = w.tk_focusNext()
            if next_w:
                next_w.focus_set()
                return "break"
        else:
            prev_w = w.tk_focusPrev()
            if prev_w:
                prev_w.focus_set()
                return "break"
        return "break"

    def _open_location(self):
        if getattr(self, "_last_output", None) and os.path.isfile(self._last_output):
            out_path = os.path.normpath(self._last_output)
            try:
                if sys.platform == "win32":
                    subprocess.Popen(['explorer', '/select,', out_path])
                elif sys.platform == "darwin":
                    subprocess.Popen(['open', '-R', out_path])
                else:
                    subprocess.Popen(['xdg-open', os.path.dirname(out_path)])
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Не удалось открыть папку:\n{e}")

    def _setup_dnd(self):
        if not _DND_AVAILABLE:
            return
        try:
            self._bind_dnd_tree(self)
        except Exception as exc:
            print("Drag-and-drop init failed:", exc)

    def _bind_dnd_tree(self, widget):
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.dnd_bind("<<DropEnter>>", self._on_drag_enter)
            widget.dnd_bind("<<DropLeave>>", self._on_drag_leave)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._bind_dnd_tree(child)

    def _set_drop_highlight(self, active: bool):
        try:
            self.grp_in.configure(
                text=" Отпустите файл… " if active else f" {INPUT_GROUP_TITLE} ")
            self.file_entry.configure(
                bg=DROP_HIGHLIGHT_BG if active else FIELD_BG)
        except tk.TclError:
            pass

    def _on_drag_enter(self, _event=None):
        self._set_drop_highlight(True)
        if getattr(self, '_current_status_text', "") != "Отпустите файл, чтобы подставить путь.":
            self._prev_drag_text = getattr(self, '_current_status_text', "Готов.")
            self._prev_drag_highlight = getattr(self, '_current_status_highlight', None)
        self.set_status("Отпустите файл, чтобы подставить путь.")
        return "copy"

    def _on_drag_leave(self, _event=None):
        self._set_drop_highlight(False)
        if not self._running:
            self.set_status(
                getattr(self, '_prev_drag_text', "Готов."),
                getattr(self, '_prev_drag_highlight', None)
            )

    def _on_drop(self, event):
        self._set_drop_highlight(False)
        if self._running:
            self.set_status("Идёт транскодирование — дождитесь окончания.")
            return "copy"
        try:
            raw_items = self.tk.splitlist(event.data)
        except Exception:
            raw_items = (event.data,)

        files = []
        for item in raw_items:
            path = str(item).strip().strip('"')
            if os.path.isfile(path):
                files.append(path)

        if not files:
            self.set_status("Перетащите видеофайл, а не папку.")
            messagebox.showwarning(
                APP_TITLE, "Не удалось распознать файл. Перетащите видеофайл.")
            return "copy"

        if len(files) > 1:
            self._log(f"Перетащено файлов: {len(files)}. "
                      f"Взят первый: {files[0]}\n")

        self._set_input_file(files[0], user_selected=True)
        self.set_status(f"Выбран файл: {os.path.basename(files[0])}")
        self._log(f"Перетащен файл: {files[0]}\n")
        return "copy"

    def _on_cleanup_hover(self, _event=None):
        if not self._running:
            if "Исходник будет перемещён" not in getattr(self, '_current_status_text', ""):
                self._prev_hover_text = getattr(self, '_current_status_text', "Готов.")
                self._prev_hover_highlight = getattr(self, '_current_status_highlight', None)
            self.set_status(
                f"Исходник будет перемещён в подпапку {ARCHIVE_DIR_NAME} "
                f"рядом с исходным видео")

    def _on_cleanup_unhover(self, _event=None):
        if not self._running:
            self.set_status(
                getattr(self, '_prev_hover_text', "Готов."),
                getattr(self, '_prev_hover_highlight', None)
            )

    def _set_input_file(self, path: str, user_selected: bool = True):
        path = os.path.normpath(str(path).strip().strip('"'))
        if user_selected and os.path.isfile(path):
            self._output_dir = os.path.dirname(os.path.abspath(path))
        if self.file_var.get().strip().strip('"') != path:
            self.file_var.set(path)
        else:
            self._on_file_change()

    def _on_slider_move(self, value):
        if self._syncing_size:
            return
        v = int(float(value))
        self._syncing_size = True
        try:
            self.target_size_var.set(v)
            self.target_entry_var.set(str(v))
        finally:
            self._syncing_size = False
        self._update_target_label()

    def _on_entry_change(self, *_):
        if self._syncing_size:
            return
        raw = self.target_entry_var.get().replace(",", ".").strip()
        try:
            v = int(round(float(raw)))
        except ValueError:
            return
        if v < TARGET_MIN_MB:
            v = TARGET_MIN_MB

        self._syncing_size = True
        try:
            self.target_size_var.set(v)
            self.slider_var.set(min(v, TARGET_SLIDER_MAX_MB))
        finally:
            self._syncing_size = False
        self._update_target_label()

    def _normalize_entry(self):
        self.target_entry_var.set(str(self.target_size_var.get()))

    def _current_codec_key(self) -> str:
        label = self.codec_var.get()
        entry = next((c for c in CODEC_CHOICES if c[0] == label), None)
        return entry[1] if entry else "av1"

    def _on_codec_change(self):
        codec_key = self._current_codec_key()
        target_mode = self.target_enabled_var.get()

        if codec_key == "hevc" and not target_mode:
            self.quality_label.configure(text="CRF (0–51, меньше — лучше):")
            self.quality_var.set("23")
        else:
            self.quality_label.configure(text="Битрейт видео (Мбит/с):")
            self.quality_var.set("8")

        self._refresh_pass_state()
        self._update_target_label()

    def _on_target_toggle(self):
        self._refresh_target_state()

    def _refresh_target_state(self):
        enabled = self.target_enabled_var.get()
        if enabled:
            self.quality_entry.configure(state="disabled")
            self.target_scale.configure(state="normal")
            self.target_entry.configure(state="normal")
        else:
            self.quality_entry.configure(state="normal")
            self.target_scale.configure(state="disabled")
            self.target_entry.configure(state="disabled")
        self._refresh_pass_state()
        self._update_target_label()

    def _refresh_pass_state(self):
        codec_key = self._current_codec_key()
        target = self.target_enabled_var.get()
        if codec_key == "hevc" and not target:
            self.pass2_rb.configure(state="disabled")
            if self.pass_var.get() == 2:
                self.pass_var.set(1)
        else:
            self.pass2_rb.configure(state="normal")

    def _compute_target_bitrate(self) -> float:
        if self._duration <= 0:
            return 0.0
        mb = float(self.target_size_var.get())
        total = mb * MB_TO_MBIT / self._duration
        return max(total - AUDIO_RESERVE_MBIT, 0.1)

    def _update_target_label(self):
        if not self.target_enabled_var.get():
            self.target_info_var.set("")
            return
        mb = self.target_size_var.get()
        if self._duration <= 0:
            self.target_info_var.set(
                f"Цель: {mb} МБ. Нужна длительность — выберите файл.")
            return
        vbr = self._compute_target_bitrate()
        self.target_info_var.set(
            f"Цель: {mb} МБ   →   видео ≈ {vbr:.2f} Мбит/с "
            f"(длительность {_fmt_time(self._duration)})")

    def _reset_info(self):
        for v in self.info_vars.values():
            v.set("—")

    def _apply_info(self, path: str, info: dict):
        self.info_vars["file"].set(Path(path).name)
        self.info_vars["duration"].set(
            _fmt_time(info["duration"]) if info["duration"] > 0 else "—")

        if info.get("total_frames", 0) > 0:
            self.info_vars["frames"].set(_fmt_int(info["total_frames"]))
        else:
            self.info_vars["frames"].set("—")

        if info["width"] and info["height"]:
            self.info_vars["res"].set(f"{info['width']}×{info['height']}")
        else:
            self.info_vars["res"].set("—")

        self.info_vars["fps"].set(_fmt_fps(info["fps"]))
        self.info_vars["vcodec"].set(info["vcodec"] or "—")
        self.info_vars["acodec"].set(info["acodec"] or "—")
        self.info_vars["bitrate"].set(
            f"{info['bitrate']:.2f} Мбит/с" if info["bitrate"] > 0 else "—")
        self.info_vars["size"].set(
            _fmt_size(info["size_bytes"]) if info["size_bytes"] > 0 else "—")

    def _on_file_change(self, *_):
        path = self.file_var.get().strip().strip('"')
        self._duration = 0.0
        self._total_frames = 0
        self._reset_info()
        self._update_target_label()
        if os.path.isfile(path):
            try:
                in_archive = (
                    Path(path).resolve().parent.name.lower() == ARCHIVE_DIR_NAME
                )
            except OSError:
                in_archive = False
            if not in_archive:
                self._output_dir = os.path.dirname(os.path.abspath(path))
            threading.Thread(target=self._probe_bg,
                             args=(path,), daemon=True).start()

    def _probe_bg(self, path: str):
        info = probe_info(path)
        def apply():
            if self.file_var.get().strip().strip('"') == path:
                self._duration = info["duration"]
                self._total_frames = int(info.get("total_frames", 0) or 0)
                self._apply_info(path, info)
                self._update_target_label()
        self.after(0, apply)

    def _browse(self):
        if self._running:
            self.set_status("Идёт транскодирование — дождитесь окончания.")
            return
        current = self.file_var.get()
        initial_dir = (os.path.dirname(current)
                       if current and os.path.isfile(current) else None)
        path = filedialog.askopenfilename(
            title="Выберите видео",
            initialdir=initial_dir,
            filetypes=[
                ("Видеофайлы", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.ts *.flv"),
                ("Все файлы", "*.*"),
            ],
        )
        if path:
            self._set_input_file(path, user_selected=True)

    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_threadsafe(self, text: str):
        self.after(0, self._log, text)

    def _set_progress(self, frac: float):
        self.progress_fill.place_configure(
            relwidth=max(0.0, min(1.0, frac)))

    def _out_path(self, inp: str, ext: str) -> str:
        p = Path(inp)
        out_dir = Path(self._output_dir) if self._output_dir else p.parent
        digits = "".join(f"{random.randint(0, 999_999):06d}" for _ in range(3))
        return str(out_dir / f"untitled_{digits}.{ext}")

    def _resolve_quality(self):
        target = self.target_enabled_var.get()

        if target:
            inp = self.file_var.get().strip().strip('"')
            if self._duration <= 0 and os.path.isfile(inp):
                self._duration = probe_info(inp)["duration"]
            if self._duration <= 0:
                raise ValueError("нужно знать длительность видео")
            q = self._compute_target_bitrate()
            if q <= 0:
                raise ValueError("не удаётся посчитать битрейт")
            return q, True

        raw = self.quality_var.get().replace(",", ".").strip()
        codec_key = self._current_codec_key()
        if codec_key == "hevc":
            q = int(raw)
            if not (0 <= q <= 51):
                raise ValueError("CRF должен быть целым 0..51")
        else:
            q = float(raw)
            if q <= 0:
                raise ValueError("битрейт должен быть > 0")
        return q, False

    def _start(self):
        if self._running:
            return

        inp = self.file_var.get().strip().strip('"')
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_TITLE, "Входной файл не найден.")
            return

        codec_key = self._current_codec_key()
        ext = next(c[2] for c in CODEC_CHOICES if c[1] == codec_key)
        two_pass = self.pass_var.get() == 2

        try:
            quality, target_mode = self._resolve_quality()
        except ValueError as e:
            messagebox.showerror(APP_TITLE, f"Ошибка: {e}")
            return

        out = self._out_path(inp, ext)
        out_dir = os.path.dirname(os.path.abspath(out))
        if not os.path.isdir(out_dir):
            messagebox.showerror(
                APP_TITLE, f"Папка для результата не найдена:\n{out_dir}")
            return

        commands = build_commands(codec_key, inp, out,
                                  quality, two_pass, target_mode)

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self._set_progress(0.0)
        self._log(f"Вход:   {inp}\nВыход:  {out}\n")
        if target_mode:
            self._log(f"Режим:  целевой размер {self.target_size_var.get()} МБ "
                      f"→ {quality:.2f} Мбит/с\n")
        self._log("\n")

        if self._duration <= 0 or self._total_frames <= 0:
            self.set_status("Определение длительности…")
            self.update_idletasks()
            info = probe_info(inp)
            self._duration = info["duration"]
            self._total_frames = int(info.get("total_frames", 0) or 0)
            self._apply_info(inp, info)

        if self._duration > 0:
            self._log(f"Длительность: {_fmt_time(self._duration)}"
                      + (f" ({_fmt_int(self._total_frames)} кадров)"
                         if self._total_frames > 0 else "")
                      + "\n")
        else:
            self._log("Не удалось определить длительность — прогресс будет без %.\n")

        cleanup_after = self.cleanup_var.get()
        if cleanup_after:
            self._log(f"После успеха исходник → {ARCHIVE_DIR_NAME}\n")

        self._running = True
        self._cancel = False
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.cleanup_cb.configure(state="disabled")
        self.open_loc_btn.pack_forget()
        self._last_output = None
        self.set_status("Старт…")
        self._cancel_taskbar_clear()
        self._taskbar.begin(0.0)
        self._set_title_progress(0.0)

        threading.Thread(
            target=self._run_worker,
            args=(commands, out, inp, cleanup_after),
            daemon=True,
        ).start()

    def _cancel_job(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._taskbar.set_state(self._taskbar.PAUSED)
        self.set_status("Отмена…")

    def _run_worker(self, commands, out: str, inp: str, cleanup_after: bool):
        ok = True
        cwd = os.path.dirname(os.path.abspath(out)) or None
        total_passes = len(commands)

        for idx, base_cmd in enumerate(commands, 1):
            if self._cancel:
                ok = False
                break

            cmd = with_progress(base_cmd)
            self._log_threadsafe(
                f"\n─── Проход {idx}/{total_passes} ───\n" +
                " ".join(cmd) + "\n\n")

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    cwd=cwd,
                    bufsize=1,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **_POPEN_KWARGS
                )
            except FileNotFoundError:
                self._log_threadsafe("\n!!! ffmpeg не найден в PATH !!!\n")
                ok = False
                break

            base_frac = (idx - 1) / total_passes
            span = 1.0 / total_passes

            t_prog = threading.Thread(
                target=self._pump_progress,
                args=(self._proc, base_frac, span, idx, total_passes),
                daemon=True)
            t_err = threading.Thread(
                target=self._pump_stderr, args=(self._proc,), daemon=True)
            t_prog.start()
            t_err.start()
            t_prog.join()
            t_err.join()
            rc = self._proc.wait()

            if rc != 0 and not self._cancel:
                self._log_threadsafe(
                    f"\n!!! ffmpeg завершился с кодом {rc} !!!\n")
                ok = False
                break

        moved_to = None
        move_error = None

        if self._cancel:
            self._log_threadsafe("\n✘ Прервано пользователем.\n")
        elif ok:
            if not os.path.isfile(out) or os.path.getsize(out) <= 0:
                ok = False
                self._log_threadsafe("\n!!! Выходной файл не создан !!!\n")
            else:
                self._log_threadsafe(f"\n✔ Готово: {out}\n")
        else:
            self._log_threadsafe("\n✘ Ошибка.\n")

        if ok and not self._cancel and cleanup_after:
            self.after(0, self.set_status, "Перемещение исходника в old_material…")
            self._log_threadsafe("\nПеремещение исходника в old_material…\n")
            try:
                moved_to = archive_source(inp)
                if moved_to:
                    self._log_threadsafe(f"Исходник перемещён: {moved_to}\n")
                else:
                    self._log_threadsafe(
                        "Исходник уже лежит в old_material — перенос не нужен.\n")
            except Exception as exc:
                move_error = str(exc)
                self._log_threadsafe(
                    f"!!! Не удалось переместить исходник: {exc}\n")

        if self._cancel:
            result = "cancel"
        elif ok:
            result = "ok"
        else:
            result = "error"

        self.after(0, self._finish, result, moved_to, move_error, out)

    def _pump_progress(self, proc, base_frac: float, span: float,
                       pass_idx: int, total_passes: int):
        duration = self._duration
        last_time = 0.0
        last_speed = ""
        last_frame = 0
        last_fps = ""

        for line in proc.stdout:
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, _, v = line.partition("=")

            if k == "out_time":
                try:
                    last_time = _parse_hms(v)
                except Exception:
                    pass
            elif k == "speed":
                last_speed = v.strip()
            elif k == "frame":
                try:
                    last_frame = int(v)
                except Exception:
                    pass
            elif k == "fps":
                last_fps = v.strip()
            elif k == "progress":
                if duration > 0:
                    frac = base_frac + span * min(last_time / duration, 1.0)
                else:
                    frac = base_frac
                self.after(0, self._update_status,
                           frac, last_time, last_speed,
                           pass_idx, total_passes,
                           last_frame, last_fps)

    def _pump_stderr(self, proc):
        skip_prefixes = ("ffmpeg version", "  built with", "  configuration:")
        for line in proc.stderr:
            s = line.rstrip("\r\n")
            if not s.strip():
                continue
            if s.startswith(skip_prefixes):
                continue
            self._log_threadsafe(s + "\n")

    def _update_status(self, frac: float, sec: float, speed: str,
                       pass_idx: int, total_passes: int,
                       frame: int = 0, enc_fps: str = ""):
        self._set_progress(frac)

        if self._duration > 0:
            self._taskbar.update(frac)
            self._set_title_progress(frac)
        else:
            self._taskbar.set_state(self._taskbar.INDETERMINATE)
            self.title(f"{APP_TITLE} — …")

        parts = []
        if total_passes > 1:
            parts.append(f"Проход {pass_idx}/{total_passes}")

        if self._total_frames > 0:
            parts.append(f"{_fmt_int(frame)}/{_fmt_int(self._total_frames)} frames")
        elif frame > 0:
            parts.append(f"{_fmt_int(frame)} frames")

        if self._duration > 0:
            pct = min(sec / self._duration * 100, 100.0)
            parts.append(f"{_fmt_time(sec)} / {_fmt_time(self._duration)}")
            parts.append(f"{pct:.1f}%")
        else:
            parts.append(_fmt_time(sec))

        if enc_fps:
            try:
                parts.append(f"{float(enc_fps):.1f} fps")
            except Exception:
                parts.append(f"{enc_fps} fps")

        if speed:
            parts.append(f"speed={speed}")

        self.set_status("   •   ".join(parts))

    def _set_title_progress(self, frac: float):
        pct = max(0, min(100, int(round(float(frac) * 100))))
        self.title(f"{APP_TITLE} — {pct}%")

    def _cancel_taskbar_clear(self):
        if self._taskbar_clear_id:
            try:
                self.after_cancel(self._taskbar_clear_id)
            except tk.TclError:
                pass
            self._taskbar_clear_id = None

    def _schedule_taskbar_clear(self, delay_ms: int):
        self._cancel_taskbar_clear()
        self._taskbar_clear_id = self.after(delay_ms, self._clear_taskbar)

    def _clear_taskbar(self):
        self._taskbar_clear_id = None
        self._taskbar.clear()

    def _finish(self, result: str = "ok", moved_to: str | None = None,
                move_error: str | None = None, out: str | None = None):
        self._running = False
        self._proc = None
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.cleanup_cb.configure(state="normal")
        self.title(APP_TITLE)

        if moved_to:
            self._set_input_file(moved_to, user_selected=False)

        if result == "ok":
            self._set_progress(1.0)
            self._taskbar.set_value(1.0)
            self._schedule_taskbar_clear(2000)

            self._last_output = out
            status_parts = ["Готово"]
            highlight = None
            if out and os.path.isfile(out):
                try:
                    size = os.path.getsize(out)
                    size_str = _fmt_size(size)
                    status_parts.append(f"{os.path.basename(out)} ({size_str})")
                    highlight = f"({size_str})"
                except OSError:
                    pass
            if moved_to:
                status_parts.append("исходник в old_material")
            
            self.set_status(" — ".join(status_parts), highlight=highlight)
            self.open_loc_btn.pack(side="right", padx=(8, 0))

        elif result == "cancel":
            self._set_progress(0.0)
            self._taskbar.clear()
            self.set_status("Отменено.")
        else:
            self._taskbar.error()
            self._schedule_taskbar_clear(4000)
            self.set_status("Ошибка.")

        if move_error:
            messagebox.showwarning(
                APP_TITLE,
                "Видео готово, но исходник не удалось переместить "
                f"в old_material:\n{move_error}")

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno(
                    APP_TITLE, "Процесс ещё выполняется. Прервать и выйти?"):
                return
            self._cancel_job()
        self._cancel_taskbar_clear()
        self._taskbar.close()
        self.destroy()


def main():
    initial = None
    if len(sys.argv) >= 2:
        cand = sys.argv[1].strip('"')
        if os.path.isfile(cand):
            initial = cand
    if initial is None and os.path.isfile("untitled.mp4"):
        initial = os.path.abspath("untitled.mp4")

    TranscodeApp(initial).mainloop()


if __name__ == "__main__":
    main()