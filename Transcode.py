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
WARN_FG     = "#e06c6c"   # недопустимое значение в поле
ACCENT      = "#4d6a99"   # мягкий синий
GREEN       = "#4dff4d"   # яркий зелёный

FONT_UI   = ("MS Sans Serif", 9)
FONT_BOLD = ("MS Sans Serif", 9, "bold")
FONT_MONO = ("Consolas", 9)

if sys.platform == "darwin":
    FONT_UI   = ("Helvetica", 9)
    FONT_BOLD = ("Helvetica", 9, "bold")
    FONT_MONO = ("Menlo", 9)
elif sys.platform != "win32":
    # В Linux шрифтов MS Sans Serif и Consolas нет — берём DejaVu,
    # который есть почти в любом дистрибутиве.
    FONT_UI   = ("DejaVu Sans", 9)
    FONT_BOLD = ("DejaVu Sans", 9, "bold")
    FONT_MONO = ("DejaVu Sans Mono", 9)

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


# ============================================================ КОНФИГУРАЦИИ
#
# Пользовательские конфигурации транскода хранятся в JSON рядом с приложением
# (или в папке настроек пользователя), чтобы их можно было добавлять,
# редактировать и удалять через окно «Настройки».
#
# Структура одной конфигурации:
#   {
#     "name":     отображаемое имя,
#     "vcodec":   имя видео-кодека ffmpeg (libsvtav1, libvpx-vp9, libx265…),
#     "ext":      расширение выходного файла без точки,
#     "quality_mode": "bitrate" | "crf",
#     "default_quality": число (битрейт Мбит/с или CRF),
#     "preset":   пресет кодека (может быть пустым),
#     "pass1_preset": пресет первого прохода ("" — основной preset),
#     "pass2_preset": пресет второго прохода ("" — основной preset),
#     "extra_args": список доп. аргументов видео (например ["-g", "30"]),
#     "audio_codec": "copy" | имя аудио-кодека,
#     "audio_args": список аргументов аудио (например ["-b:a", "192k"]),
#     "raw_args": список произвольных аргументов ffmpeg,
#     "two_pass": true | false,
#     "gop":      интервал ключевых кадров (0 — не задавать),
#     "backend":  "cpu" | "gpu",
#     "advanced_log": готовая команда ffmpeg ("" — использовать поля выше),
#   }

CONFIG_DIR_NAME = "Transcode98"
CONFIG_FILE_NAME = "configs.json"


def config_path() -> Path:
    """Путь к файлу пользовательских конфигураций."""
    # Рядом с приложением (portable), иначе — в профиле пользователя.
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                                           else __file__))
    portable = os.path.join(base, CONFIG_FILE_NAME)
    try:
        if os.access(base, os.W_OK):
            return Path(portable)
    except Exception:
        pass
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        appdata = (os.environ.get("XDG_CONFIG_HOME")
                   or os.path.join(os.path.expanduser("~"), ".config"))
    return Path(appdata) / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def default_configs() -> list[dict]:
    """Встроенные конфигурации (используются, если файла ещё нет)."""
    return [
        {
            "name": "AV1 (Discord) — MP4",
            "vcodec": "libsvtav1",
            "ext": "mp4",
            "quality_mode": "bitrate",
            "default_quality": 8.0,
            "preset": "4",
            "pass1_preset": "8",
            "pass2_preset": "2",
            "extra_args": ["-g", "30", "-pix_fmt", "yuv420p"],
            "audio_codec": "copy",
            "audio_args": [],
            "raw_args": [],
            "two_pass": True,
            "gop": 30,
            "backend": "cpu",
            "advanced_log": "",
        },
        {
            "name": "VP9 (YouTube) — WebM",
            "vcodec": "libvpx-vp9",
            "ext": "webm",
            "quality_mode": "bitrate",
            "default_quality": 8.0,
            "preset": "4",
            "pass1_preset": "",
            "pass2_preset": "",
            "extra_args": ["-g", "30", "-pix_fmt", "yuv420p",
                           "-row-mt", "1", "-tile-columns", "2", "-cpu-used", "4"],
            "audio_codec": "libopus",
            "audio_args": ["-b:a", "192k", "-ar", "48000"],
            "raw_args": [],
            "two_pass": True,
            "gop": 30,
            "backend": "cpu",
            "advanced_log": "",
        },
        {
            "name": "HEVC (libx265) — MP4",
            "vcodec": "libx265",
            "ext": "mp4",
            "quality_mode": "crf",
            "default_quality": 23.0,
            "preset": "medium",
            "pass1_preset": "",
            "pass2_preset": "",
            "extra_args": ["-g", "30", "-pix_fmt", "yuv420p"],
            "audio_codec": "copy",
            "audio_args": [],
            "raw_args": [],
            "two_pass": True,
            "gop": 30,
            "backend": "cpu",
            "advanced_log": "",
        },
        {
            "name": "H.264 (libx264) — MP4",
            "vcodec": "libx264",
            "ext": "mp4",
            "quality_mode": "crf",
            "default_quality": 23.0,
            "preset": "medium",
            "pass1_preset": "",
            "pass2_preset": "",
            "extra_args": ["-g", "30", "-pix_fmt", "yuv420p"],
            "audio_codec": "copy",
            "audio_args": [],
            "raw_args": [],
            "two_pass": False,
            "gop": 30,
            "backend": "cpu",
            "advanced_log": "",
        },
    ]


_CONFIG_FIELDS = (
    "name", "vcodec", "ext", "quality_mode", "default_quality",
    "preset", "pass1_preset", "pass2_preset",
    "extra_args", "audio_codec", "audio_args", "raw_args",
    "two_pass", "gop", "backend", "advanced_log",
)

# Нейтральные значения для полей, которых нет в конфиге. Не наследуем их
# от первого встроенного пресета (AV1), иначе новые и неполные конфиги
# получают чужие preset/extra_args/audio_args.
NEUTRAL_CONFIG = {
    "name": "Новая конфигурация",
    "vcodec": "libx264",
    "ext": "mp4",
    "quality_mode": "crf",
    "default_quality": 23.0,
    "preset": "",
    "pass1_preset": "",
    "pass2_preset": "",
    "extra_args": ["-pix_fmt", "yuv420p"],
    "audio_codec": "copy",
    "audio_args": [],
    "raw_args": [],
    "two_pass": False,
    "gop": 30,
    "backend": "cpu",
    "advanced_log": "",
}

# Старые встроенные advanced_log не содержали -i (вход добавлялся после
# выводных опций) и перекрывали параметры главного окна. Сбрасываем их при
# загрузке, чтобы вернуть рабочие команды и настройки по умолчанию.
LEGACY_ADVANCED_LOGS = {
    "-c:v libsvtav1 -preset 4 -b:v 8M -g 30 -pix_fmt yuv420p "
    "-c:a copy {input} {output}",
    "-c:v libvpx-vp9 -cpu-used 4 -b:v 8M -maxrate 8M -bufsize 24M "
    "-g 30 -pix_fmt yuv420p -row-mt 1 -tile-columns 2 -c:a libopus "
    "-b:a 192k -ar 48000 {input} {output}",
    "-c:v libx265 -preset medium -crf 23 -g 30 -pix_fmt yuv420p "
    "-c:a copy {input} {output}",
}

# Бэкенд кодирования: CPU (медленнее, но качественнее) или GPU (быстрее,
# но с потерями в качестве). Значение хранится в поле "backend".
ENCODER_BACKENDS = {"cpu": "CPU", "gpu": "GPU"}

# Соответствие CPU-кодека его аппаратному аналогу для бэкенда GPU.
# У VP9 нет аппаратного аналога в NVENC/QSV/AMF, поэтому он остаётся
# программным (libvpx-vp9).
GPU_CODEC_MAP = {
    "libx264":    "h264_nvenc",
    "libx265":    "hevc_nvenc",
    "libsvtav1":  "av1_nvenc",
    "libaom-av1": "av1_nvenc",
}

# Кодеки, которые уже являются аппаратными.
GPU_CODECS = {"h264_nvenc", "hevc_nvenc", "av1_nvenc",
              "h264_qsv", "hevc_qsv", "av1_qsv",
              "h264_amf", "hevc_amf", "av1_amf"}

# --------------------------------------------------------------- каталог кодеков
#
# Готовые варианты для меню «Добавить» и подсказок в редакторе. При выборе
# кодека поля заполняются типовыми значениями, но в configs.json по-прежнему
# хранится обычное имя ffmpeg — можно ввести и любой другой кодек вручную.
CODEC_CATALOG = (
    {
        "vcodec": "libx264",
        "title": "H.264 (x264) — совместимость",
        "ext": "mp4",
        "quality_mode": "crf",
        "quality": 23.0,
        "speed": "medium",
        "two_pass": False,
        "audio_codec": "copy",
        "audio_args": [],
        "extra_args": ["-pix_fmt", "yuv420p"],
        "gop": 30,
    },
    {
        "vcodec": "libx265",
        "title": "H.265 / HEVC (x265) — эффективность",
        "ext": "mp4",
        "quality_mode": "crf",
        "quality": 24.0,
        "speed": "medium",
        "two_pass": False,
        "audio_codec": "copy",
        "audio_args": [],
        "extra_args": ["-pix_fmt", "yuv420p"],
        "gop": 30,
    },
    {
        "vcodec": "libsvtav1",
        "title": "AV1 (SVT-AV1) — минимальный размер",
        "ext": "mp4",
        "quality_mode": "crf",
        "quality": 30.0,
        "speed": "8",
        "pass1": "8",
        "pass2": "2",
        "two_pass": False,
        "audio_codec": "copy",
        "audio_args": [],
        "extra_args": ["-pix_fmt", "yuv420p"],
        "gop": 30,
    },
    {
        "vcodec": "libvpx-vp9",
        "title": "VP9 — WebM для YouTube",
        "ext": "webm",
        "quality_mode": "crf",
        "quality": 32.0,
        "speed": "4",
        "two_pass": False,
        "audio_codec": "libopus",
        "audio_args": ["-b:a", "192k", "-ar", "48000"],
        "extra_args": ["-pix_fmt", "yuv420p", "-row-mt", "1",
                       "-tile-columns", "2"],
        "gop": 30,
    },
)

CODEC_BY_ID = {item["vcodec"]: item for item in CODEC_CATALOG}

# Понятные названия скоростных пресетов. Второй элемент пары — значение,
# которое записывается в configs.json (и уходит в ffmpeg).
_SPEED_X264 = (
    ("Очень быстро", "ultrafast"),
    ("Быстро", "veryfast"),
    ("Обычно", "medium"),
    ("Медленно", "slow"),
    ("Очень медленно", "veryslow"),
)
_SPEED_AV1 = (
    ("Максимальная скорость", "12"),
    ("Быстро", "10"),
    ("Обычно", "8"),
    ("Медленно", "6"),
    ("Очень медленно", "4"),
    ("Максимум качества", "2"),
)
_SPEED_VP9 = (
    ("Максимальная скорость", "8"),
    ("Быстро", "6"),
    ("Обычно", "4"),
    ("Медленно", "2"),
    ("Максимум качества", "0"),
)
_SPEED_NVENC = (
    ("Максимальная скорость", "1"),
    ("Быстро", "3"),
    ("Обычно", "5"),
    ("Качество", "7"),
)
_SPEED_QSV = (
    ("Очень быстро", "veryfast"),
    ("Быстро", "fast"),
    ("Обычно", "medium"),
    ("Медленно", "slow"),
    ("Очень медленно", "veryslow"),
)
_SPEED_AMF = (
    ("Скорость", "speed"),
    ("Баланс", "balanced"),
    ("Качество", "quality"),
)

SPEED_CHOICES = {
    "libx264": _SPEED_X264,
    "libx265": _SPEED_X264,
    "libsvtav1": _SPEED_AV1,
    "libvpx-vp9": _SPEED_VP9,
    "h264_nvenc": _SPEED_NVENC,
    "hevc_nvenc": _SPEED_NVENC,
    "av1_nvenc": _SPEED_NVENC,
    "h264_qsv": _SPEED_QSV,
    "hevc_qsv": _SPEED_QSV,
    "av1_qsv": _SPEED_QSV,
    "h264_amf": _SPEED_AMF,
    "hevc_amf": _SPEED_AMF,
    "av1_amf": _SPEED_AMF,
}

SPEED_HINTS = {
    "libx264": "Пресет x264: чем медленнее, тем лучше сжатие.",
    "libx265": "Пресет x265: чем медленнее, тем лучше сжатие.",
    "libsvtav1": "Для AV1 меньшее число — медленнее и качественнее (0–13).",
    "libvpx-vp9": "Для VP9 меньшее число — медленнее и качественнее (0–8).",
    "h264_nvenc": "Для NVENC: p1 — быстрее, p7 — качественнее.",
    "hevc_nvenc": "Для NVENC: p1 — быстрее, p7 — качественнее.",
    "av1_nvenc": "Для NVENC: p1 — быстрее, p7 — качественнее.",
    "h264_qsv": "Пресет Intel QSV: чем медленнее, тем лучше сжатие.",
    "hevc_qsv": "Пресет Intel QSV: чем медленнее, тем лучше сжатие.",
    "av1_qsv": "Пресет Intel QSV: чем медленнее, тем лучше сжатие.",
    "h264_amf": "Пресет AMD AMF: скорость / баланс / качество.",
    "hevc_amf": "Пресет AMD AMF: скорость / баланс / качество.",
    "av1_amf": "Пресет AMD AMF: скорость / баланс / качество.",
}


def _speed_choices(vcodec: str) -> tuple[tuple[str, str], ...]:
    """Подсказки для поля «Скорость» с учётом кодека."""
    return SPEED_CHOICES.get(vcodec, (
        ("Быстро", "fast"),
        ("Обычно", "medium"),
        ("Медленно", "slow"),
    ))


def _speed_hint(vcodec: str) -> str:
    """Короткое пояснение к шкале скорости выбранного кодека."""
    return SPEED_HINTS.get(
        vcodec, "Пресет кодека: чем медленнее, тем лучше сжатие.")


def _speed_value_ok(vcodec: str, value: str) -> bool:
    """Проверяет, подходит ли значение скорости для известного кодека."""
    if not value:
        return True
    if vcodec in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
        return value.isdigit() and 1 <= int(value) <= 7
    if vcodec == "libsvtav1":
        return value.isdigit() and 0 <= int(value) <= 13
    if vcodec == "libvpx-vp9":
        return value.isdigit() and 0 <= int(value) <= 8
    if vcodec in SPEED_CHOICES:
        return value in {v for _, v in SPEED_CHOICES[vcodec]}
    return True


def quality_range(cfg: dict) -> tuple[int, int]:
    """Допустимый диапазон CRF/CQ для кодека.

    У AV1 и VP9 шкала шире (0–63), у H.264/H.265 и аппаратных — 0–51.
    """
    vcodec = resolve_vcodec(cfg)
    if vcodec in ("libsvtav1", "libaom-av1", "libvpx-vp9"):
        return 0, 63
    return 0, 51


# Глобальные опции графического интерфейса.
# Хранятся в том же JSON-файле (ключ "ui_options") и управляются из окна
# «Настройки» → «Опции GUI». Определяют, показывать ли в главном окне
# соответствующие блоки (рескейлинг, понижение FPS, сводка ffprobe, журнал).
DEFAULT_UI_OPTIONS = {
    "rescale_enabled": True,
    "fps_enabled": True,
    "ffprobe_enabled": True,
    "log_enabled": True,
}


def _sanitize_ui_options(opts: dict | None) -> dict:
    """Приводит опции GUI к валидному виду."""
    out = dict(DEFAULT_UI_OPTIONS)
    if isinstance(opts, dict):
        for key in DEFAULT_UI_OPTIONS:
            if key in opts:
                out[key] = bool(opts[key])
    return out


def _sanitize_config(cfg: dict, fallback: dict | None = None) -> dict:
    """Приводит конфиг к валидному виду, подставляя значения по умолчанию."""
    base = dict(fallback or NEUTRAL_CONFIG)
    out = {}
    out["name"] = str(cfg.get("name") or base["name"]).strip() or "Без названия"
    out["vcodec"] = str(cfg.get("vcodec") or base["vcodec"]).strip() or base["vcodec"]
    ext = str(cfg.get("ext") or base["ext"]).strip().lstrip(".")
    out["ext"] = ext or base["ext"]
    qm = str(cfg.get("quality_mode") or base["quality_mode"]).strip().lower()
    out["quality_mode"] = qm if qm in ("bitrate", "crf") else base["quality_mode"]
    try:
        out["default_quality"] = float(cfg.get("default_quality", base["default_quality"]))
    except (TypeError, ValueError):
        out["default_quality"] = float(base["default_quality"])

    def _as_list(v):
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str):
            # Разбираем с учётом кавычек, чтобы аргументы с пробелами
            # оставались одним токеном.
            return _split_advanced(v) if v.strip() else []
        return []

    def _list_field(key):
        value = cfg[key] if key in cfg else base.get(key, [])
        if value is None:
            value = base.get(key, [])
        return _as_list(value)

    def _str_field(key):
        value = cfg[key] if key in cfg else base.get(key, "")
        return "" if value is None else str(value).strip()

    out["preset"] = _str_field("preset")
    out["pass1_preset"] = _str_field("pass1_preset")
    out["pass2_preset"] = _str_field("pass2_preset")
    # Для AV1 сохраняем историческое поведение: если пресеты проходов не
    # заданы явно, первый проход идёт с 8, финальный — с 2.
    if out["vcodec"] == "libsvtav1":
        if "pass1_preset" not in cfg:
            out["pass1_preset"] = "8"
        if "pass2_preset" not in cfg:
            out["pass2_preset"] = "2"

    out["extra_args"] = _list_field("extra_args")
    ac = str(cfg.get("audio_codec", base.get("audio_codec", "copy")) or "copy").strip()
    out["audio_codec"] = ac or "copy"
    out["audio_args"] = _list_field("audio_args")
    out["raw_args"] = _list_field("raw_args")
    out["two_pass"] = bool(cfg.get("two_pass", base.get("two_pass", False)))
    try:
        out["gop"] = int(cfg.get("gop", base.get("gop", 0)) or 0)
    except (TypeError, ValueError):
        out["gop"] = int(base.get("gop", 0) or 0)

    backend = str(cfg.get("backend", base.get("backend", "cpu"))).strip().lower()
    out["backend"] = backend if backend in ENCODER_BACKENDS else "cpu"

    # ВАЖНО: advanced_log не наследуется от fallback-конфига, иначе
    # все конфиги без явного значения получают лог первого.
    adv = cfg.get("advanced_log", "")
    if isinstance(adv, list):
        adv = " ".join(str(x) for x in adv)
    adv = str(adv or "").strip()
    if adv in LEGACY_ADVANCED_LOGS:
        adv = ""
    out["advanced_log"] = adv
    return out


def load_configs() -> list[dict]:
    """Читает пользовательские конфигурации с диска (или возвращает встроенные)."""
    path = config_path()
    if not path.is_file():
        return default_configs()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_configs()
    raw = data.get("configs") if isinstance(data, dict) else data
    if not isinstance(raw, list) or not raw:
        return default_configs()
    result = []
    for item in raw:
        if isinstance(item, dict):
            result.append(_sanitize_config(item))
    return result or default_configs()


def load_ui_options() -> dict:
    """Читает глобальные опции GUI с диска (или возвращает значения по умолчанию)."""
    path = config_path()
    if not path.is_file():
        return dict(DEFAULT_UI_OPTIONS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_UI_OPTIONS)
    if isinstance(data, dict):
        return _sanitize_ui_options(data.get("ui_options"))
    return dict(DEFAULT_UI_OPTIONS)


def save_configs(configs: list[dict], ui_options: dict | None = None) -> None:
    """Сохраняет конфигурации (и, опционально, опции GUI) на диск.

    Если ui_options не передан, уже сохранённые опции GUI не теряются.
    """
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Сохраняем ранее записанные данные (например ui_options), чтобы не
        # затирать их при сохранении только списка конфигураций.
        data: dict = {}
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    data = existing
            except Exception:
                data = {}

        data["version"] = 1
        data["configs"] = configs
        if ui_options is not None:
            data["ui_options"] = _sanitize_ui_options(ui_options)
        else:
            data["ui_options"] = _sanitize_ui_options(data.get("ui_options"))

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception as exc:
        raise OSError(f"Не удалось сохранить конфигурации:\n{exc}") from exc


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


def make_radio(parent, text, variable, value, command=None):
    return tk.Radiobutton(
        parent, text=text, variable=variable, value=value, command=command,
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


def make_option_menu(parent, textvariable, values, width=24):
    m = tk.OptionMenu(parent, textvariable, *values)
    m.configure(
        bg=BTN_FACE, fg=TEXT,
        activebackground=BTN_FACE_HI, activeforeground="#ffffff",
        relief="raised", bd=2, highlightthickness=1,
        highlightbackground="#555555", highlightcolor="#777777",
        font=FONT_UI, width=width, anchor="w", padx=8, pady=2, cursor="hand2",
        takefocus=True)
    m["menu"].configure(
        bg=BTN_FACE, fg=TEXT,
        activebackground=ACCENT, activeforeground="#ffffff",
        font=FONT_UI, bd=0, activeborderwidth=0, relief="flat")
    return m


def make_menu_button(parent, text, items, width=None):
    """Кнопка с выпадающим меню; items — список пар (подпись, команда)."""
    mb = tk.Menubutton(
        parent, text=text,
        bg=BTN_FACE, fg=TEXT,
        activebackground=BTN_FACE_HI, activeforeground="#ffffff",
        disabledforeground=DISABLED_FG,
        relief="raised", bd=2, highlightthickness=1,
        highlightbackground="#555555", highlightcolor="#777777",
        font=FONT_UI, padx=8, pady=2, cursor="hand2", takefocus=True)
    if width:
        mb.configure(width=width)
    menu = tk.Menu(
        mb, tearoff=False,
        bg=BTN_FACE, fg=TEXT,
        activebackground=ACCENT, activeforeground="#ffffff",
        font=FONT_UI, bd=0, activeborderwidth=0, relief="flat")
    for label, command in items:
        menu.add_command(label=label, command=command)
    mb.configure(menu=menu)
    return mb


class SuggestEntry(tk.Frame):
    """Поле ввода с кнопкой ▾ и списком подсказок.

    Значение можно выбрать из списка или ввести вручную. Это важно для
    кодеков и пресетов, которых нет в стандартном наборе.
    """

    def __init__(self, parent, textvariable, values=(), width=None,
                 on_pick=None):
        super().__init__(parent, bg=BG)
        self.var = textvariable
        self.on_pick = on_pick
        self.entry = make_entry(self, textvariable, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        self.button = tk.Menubutton(
            self, text="▾",
            bg=BTN_FACE, fg=TEXT,
            activebackground=BTN_FACE_HI, activeforeground="#ffffff",
            disabledforeground=DISABLED_FG,
            relief="raised", bd=2, highlightthickness=1,
            highlightbackground="#555555", highlightcolor="#777777",
            font=FONT_UI, padx=6, pady=1, cursor="hand2", takefocus=True)
        self.menu = tk.Menu(
            self.button, tearoff=False,
            bg=BTN_FACE, fg=TEXT,
            activebackground=ACCENT, activeforeground="#ffffff",
            font=FONT_UI, bd=0, activeborderwidth=0, relief="flat")
        self.button.configure(menu=self.menu)
        self.button.pack(side="left", padx=(4, 0))
        self.set_values(values)

    def set_values(self, values):
        """Обновляет список подсказок.

        Элементы могут быть строками или парами (подпись, значение).
        """
        self.menu.delete(0, "end")
        for item in values:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                label, value = item
            else:
                label = value = str(item)
            self.menu.add_command(
                label=str(label), command=lambda v=value: self._pick(v))

    def _pick(self, value):
        self.var.set(str(value))
        if self.on_pick:
            self.on_pick(str(value))


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
        "abitrate": 0.0,
    }
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries",
             "format=duration,bit_rate,size:"
             "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,bit_rate",
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
            try:
                info["abitrate"] = float(st.get("bit_rate", 0) or 0) / 1000.0
            except Exception:
                pass

    # Некоторые контейнеры (напр. MKV) не сообщают bit_rate на уровне потока.
    # Тогда делаем отдельный запрос по первому аудиопотоку.
    if info["acodec"] and info["abitrate"] <= 0:
        info["abitrate"] = _probe_audio_bitrate(path)

    return info


def _probe_audio_bitrate(path: str) -> float:
    """Запасной запрос битрейта первого аудиопотока (кбит/с).

    Некоторые контейнеры (MKV и др.) не хранят bit_rate на уровне потока,
    поэтому сначала пробуем поле stream.bit_rate, а затем оцениваем битрейт
    по суммарному размеру пакетов и длительности аудиопотока.
    """
    # 1) прямое поле bit_rate
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate", "-of", "json", path],
            capture_output=True, text=True, timeout=20,
            **_POPEN_KWARGS)
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams", []) or []
        if streams:
            br = streams[0].get("bit_rate")
            if br:
                return float(br) / 1000.0
    except Exception:
        pass

    # 2) оценка по длительности аудиопотока и размеру пакетов
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "format=duration:stream=duration:packet=size",
             "-of", "json", path],
            capture_output=True, text=True, timeout=40,
            **_POPEN_KWARGS)
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams", []) or []
        duration = 0.0
        if streams:
            try:
                duration = float(streams[0].get("duration", 0) or 0)
            except (TypeError, ValueError):
                duration = 0.0
        if duration <= 0:
            # контейнер не хранит длительность аудиопотока — берём общую
            try:
                duration = float((data.get("format", {}) or {}).get("duration", 0) or 0)
            except (TypeError, ValueError):
                duration = 0.0
        total_bytes = 0
        for pkt in data.get("packets", []) or []:
            try:
                total_bytes += int(pkt.get("size", 0) or 0)
            except (TypeError, ValueError):
                pass
        if total_bytes > 0 and duration > 0:
            return (total_bytes * 8.0) / duration / 1000.0
    except Exception:
        pass

    return 0.0


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

def build_video_args(cfg: dict, quality, two_pass: bool,
                     target_mode: bool = False, scale_filter: str = "",
                     fps_value: float = 0.0, pass_index: int = 0) -> list[str]:
    """Собирает список аргументов видео-части команды ffmpeg."""
    vcodec = resolve_vcodec(cfg)
    qmode = cfg["quality_mode"]
    is_gpu = vcodec in GPU_CODECS
    args: list[str] = ["-c:v", vcodec]

    preset = str(cfg.get("preset", "") or "").strip()
    if two_pass and pass_index in (1, 2):
        override = str(cfg.get(f"pass{pass_index}_preset", "") or "").strip()
        if override:
            preset = override
    if preset:
        if vcodec == "libvpx-vp9":
            args += ["-cpu-used", preset]
        elif vcodec.startswith(("h264_nvenc", "hevc_nvenc", "av1_nvenc")):
            # для NVENC — это профиль скорости p1..p7
            args += ["-preset",
                     f"p{min(max(int(preset), 1), 7)}" if preset.isdigit() else "p5"]
        else:
            args += ["-preset", preset]

    if qmode == "crf" and not target_mode:
        q = str(int(round(float(quality))))
        if vcodec in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
            # У NVENC аналог CRF — параметр -cq (в режиме VBR).
            args += ["-rc", "vbr", "-cq", q]
        elif vcodec in ("h264_qsv", "hevc_qsv", "av1_qsv"):
            args += ["-global_quality", q]
        elif vcodec in ("h264_amf", "hevc_amf", "av1_amf"):
            args += ["-rc", "cqp", "-qp_i", q, "-qp_p", q]
        elif vcodec == "libvpx-vp9":
            # VP9 требует -b:v 0, иначе CRF работает как ограничение битрейта.
            args += ["-b:v", "0", "-crf", q]
        else:
            args += ["-crf", q]
    else:
        br = f"{float(quality):g}M"
        args += ["-b:v", br]
        if vcodec == "libvpx-vp9":
            args += ["-maxrate", br, "-bufsize", "24M"]
        elif is_gpu:
            args += ["-maxrate", br, "-bufsize", "24M"]

    # доп. аргументы из конфигурации (уже включают gop/pix_fmt и т.п.)
    extra_args = list(cfg.get("extra_args", []))
    if vcodec == "libvpx-vp9" and preset:
        # Пресет уже добавлен как -cpu-used; убираем его копию из extra_args,
        # иначе она перекрывает пресеты проходов (pass1_preset/pass2_preset).
        cleaned: list[str] = []
        i = 0
        while i < len(extra_args):
            if extra_args[i] == "-cpu-used":
                i += 2
                continue
            cleaned.append(extra_args[i])
            i += 1
        extra_args = cleaned
    args += extra_args

    gop = cfg.get("gop", 0)
    if gop and "-g" not in cfg.get("extra_args", []):
        args += ["-g", str(gop)]

    if scale_filter:
        args += ["-vf", scale_filter]
    if fps_value and fps_value > 0:
        args += ["-r", f"{fps_value:g}"]

    return args


def resolve_vcodec(cfg: dict) -> str:
    """Возвращает итоговый видео-кодек с учётом выбранного бэкенда.

    При backend == "gpu" CPU-кодек заменяется его аппаратным аналогом
    (если он есть в GPU_CODEC_MAP). Если пользователь уже указал
    аппаратный кодек, он возвращается без изменений.
    """
    vcodec = cfg.get("vcodec", "")
    if cfg.get("backend", "cpu") == "gpu":
        if vcodec in GPU_CODECS:
            return vcodec
        return GPU_CODEC_MAP.get(vcodec, vcodec)
    return vcodec


def _split_advanced(text: str) -> list[str]:
    """Разбивает строку аргументов на токены с учётом кавычек.

    В отличие от shlex, сохраняет обратные слэши в путях Windows и
    корректно обрабатывает кавычки внутри токена (`title="My Video"`).
    """
    tokens: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in text:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "\"'":
            quote = ch
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _build_advanced_command(text: str, cfg: dict, inp: str, out: str) -> list[str]:
    """Собирает команду ffmpeg из расширенного лога.

    Поддерживаются подстановки:
      {input}, {output} — пути входного и выходного файлов;
      {ext}             — расширение выходного файла.
    Вход всегда идёт первым: если в шаблоне нет -i, он добавляется
    автоматически, иначе выводные опции вроде -c:v попали бы в input.
    """
    tokens = _split_advanced(text)
    if tokens and tokens[0].lower() in ("ffmpeg", "ffmpeg.exe"):
        tokens = tokens[1:]
    # -y добавляем сами, чтобы не дублировать его из шаблона.
    tokens = [t for t in tokens if t != "-y"]

    has_input_opt = any(t == "-i" for t in tokens)
    has_output = any("{output}" in t or "{out}" in t for t in tokens)
    ext = cfg.get("ext", "")

    def substitute(token: str) -> str:
        return (token.replace("{input}", inp).replace("{in}", inp)
                .replace("{output}", out).replace("{out}", out)
                .replace("{ext}", ext))

    body = []
    for token in tokens:
        if not has_input_opt and token in ("{input}", "{in}"):
            continue
        body.append(substitute(token))

    result = ["ffmpeg", "-y"]
    if not has_input_opt:
        result += ["-i", inp]
    result += body
    if not has_output:
        result += [out]
    return result


def build_commands(cfg: dict, inp: str, out: str,
                   quality, two_pass: bool, target_mode: bool = False,
                   scale_filter: str = "", fps_value: float = 0.0):
    """Строит список команд ffmpeg по выбранной конфигурации.

    Возвращает список списков (1 или 2 команды: однопроход/двупроход).
    """
    null = os.devnull
    advanced = str(cfg.get("advanced_log", "") or "").strip()
    if advanced:
        # Расширенный лог задаёт команду целиком и имеет приоритет над
        # всеми параметрами, заданными в редакторе конфигурации.
        return [_build_advanced_command(advanced, cfg, inp, out)]

    # Двупроход с CRF не имеет смысла: статистика первого прохода не
    # используется. Оставляем его только для битрейта/целевого размера.
    if two_pass and cfg.get("quality_mode") == "crf" and not target_mode:
        two_pass = False

    vcodec = resolve_vcodec(cfg)
    audio_codec = cfg.get("audio_codec", "copy")
    audio_args = list(cfg.get("audio_args", []))

    def audio_part() -> list[str]:
        return ["-c:a", audio_codec, *audio_args]

    def video_part(pass_index: int = 0) -> list[str]:
        args = build_video_args(cfg, quality, two_pass, target_mode,
                                scale_filter, fps_value, pass_index)
        # Произвольные пользовательские аргументы ffmpeg вставляются напрямую,
        # после всех авто-построенных параметров и перед выходным файлом.
        return args + list(cfg.get("raw_args", []))

    if not two_pass:
        return [["ffmpeg", "-y", "-i", inp, *video_part(), *audio_part(), out]]

    # Двухпроходное кодирование для аппаратных кодеков бессмысленно/не нужно.
    if vcodec in GPU_CODECS:
        return [["ffmpeg", "-y", "-i", inp, *video_part(), *audio_part(), out]]

    # Двупроход: для x265 pass через -x265-params, для остальных -pass N
    def pass_args(n: int) -> list[str]:
        if vcodec == "libx265":
            return ["-x265-params", f"pass={n}"]
        return ["-pass", str(n)]

    first = ["ffmpeg", "-y", "-i", inp, *video_part(1), *pass_args(1),
             "-an", "-f", "null", null]
    second = ["ffmpeg", "-y", "-i", inp, *video_part(2), *pass_args(2),
              *audio_part(), out]
    return [first, second]


# ------------------------------------------------------------------------- окно

class SettingsWindow(tk.Toplevel):
    """Окно управления пользовательскими конфигурациями транскода.

    Редактор позволяет задать имя, видео-кодек и расширение, бэкенд CPU/GPU,
    режим и значение качества, пресет (и отдельные пресеты проходов), GOP,
    аргументы видео/аудио, произвольные аргументы ffmpeg и двупроход.
    Дополнительно — расширенный лог конфигурации, который при заполнении
    полностью перекрывает параметры редактора при построении команды ffmpeg.
    """

    def __init__(self, master: "TranscodeApp"):
        super().__init__(master)
        self.app = master
        self.title("Настройки — конфигурации и опции GUI")
        self.configure(bg=BG)
        self.geometry("900x700")
        self.minsize(780, 600)
        self.transient(master)
        self.grab_set()

        self.configs: list[dict] = [dict(c) for c in master.configs]
        self.selected_index: int | None = None
        self.ui_options: dict = _sanitize_ui_options(master.ui_options)

        self._build_ui()
        self._refresh_list()
        if self.configs:
            self._select_index(0)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=10, pady=10)

        left_col = tk.Frame(outer, bg=BG)
        left_col.pack(side="left", fill="y", expand=False, padx=(0, 10))

        left = make_group(left_col, "Конфигурации")
        left.pack(fill="both", expand=True)

        list_frame = tk.Frame(left, bg=BG)
        list_frame.pack(fill="both", expand=True, padx=6, pady=6)
        self.listbox = tk.Listbox(
            list_frame, height=16, width=32,
            bg=FIELD_BG, fg=FIELD_FG, selectbackground=ACCENT,
            selectforeground="#ffffff", font=FONT_UI,
            relief="sunken", bd=2, highlightthickness=0,
            activestyle="none", exportselection=False,
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        lsb = tk.Scrollbar(list_frame, command=self.listbox.yview,
                           bg=BTN_FACE, activebackground=BTN_FACE_HI,
                           troughcolor=BG_DEEP, relief="raised", bd=2,
                           highlightthickness=0)
        lsb.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=lsb.set)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        # Del удаляет выбранную конфигурацию (с подтверждением, как кнопка).
        self.listbox.bind("<Delete>", self._on_list_delete)

        btns = tk.Frame(left, bg=BG)
        btns.pack(fill="x", padx=6, pady=(0, 6))
        add_items = [
            (item["title"],
             lambda v=item["vcodec"]: self._add_from_template(v))
            for item in CODEC_CATALOG
        ]
        add_items.append(("— Пустая конфигурация —", self._add))
        make_menu_button(btns, "Добавить ▾", add_items).pack(side="left")
        make_button(btns, "Дублировать", self._duplicate).pack(side="left", padx=(6, 0))
        make_button(btns, "Удалить", self._delete).pack(side="left", padx=(6, 0))

        gui_group = make_group(left_col, "Опции GUI")
        gui_group.pack(fill="x", pady=(10, 0))
        gui_body = tk.Frame(gui_group, bg=BG)
        gui_body.pack(fill="x", padx=8, pady=8)

        tk.Label(gui_body,
                 text="Какие блоки показывать в главном окне:",
                 bg=BG, fg=TEXT_DIM, font=FONT_UI, anchor="w",
                 justify="left").pack(fill="x", anchor="w")

        self.var_opt_rescale = tk.BooleanVar(
            value=bool(self.ui_options.get("rescale_enabled", True)))
        self.var_opt_fps = tk.BooleanVar(
            value=bool(self.ui_options.get("fps_enabled", True)))
        self.var_opt_ffprobe = tk.BooleanVar(
            value=bool(self.ui_options.get("ffprobe_enabled", True)))
        self.var_opt_log = tk.BooleanVar(
            value=bool(self.ui_options.get("log_enabled", True)))

        make_check(gui_body, "Рескейлинг (изменить разрешение)",
                   self.var_opt_rescale).pack(anchor="w", pady=(6, 0))
        make_check(gui_body, "Понижение частоты кадров (FPS)",
                   self.var_opt_fps).pack(anchor="w", pady=(2, 0))
        make_check(gui_body, "Сводка ffprobe (информация о видео)",
                   self.var_opt_ffprobe).pack(anchor="w", pady=(2, 0))
        make_check(gui_body, "Журнал выполнения",
                   self.var_opt_log).pack(anchor="w", pady=(2, 0))

        # ---------------------------------------------------------- редактор
        right = make_group(outer, "Редактор")
        right.pack(side="right", fill="both", expand=True)

        # Форма длинная: прокручиваем её, иначе нижние поля не помещаются
        # в окне при невысоком разрешении экрана.
        canvas = tk.Canvas(right, bg=BG, bd=0, highlightthickness=0)
        form_sb = tk.Scrollbar(
            right, orient="vertical", command=canvas.yview,
            bg=BTN_FACE, activebackground=BTN_FACE_HI, troughcolor=BG_DEEP,
            relief="raised", bd=2, highlightthickness=0)
        canvas.configure(yscrollcommand=form_sb.set)
        form_sb.pack(side="right", fill="y", pady=6)
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        self._form_canvas = canvas

        form = tk.Frame(canvas, bg=BG)
        form_id = canvas.create_window((0, 0), window=form, anchor="nw")
        form.columnconfigure(1, weight=1)
        form.bind("<Configure>",
                  lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(form_id, width=e.width))
        self.bind("<MouseWheel>", self._on_mousewheel, add="+")
        if sys.platform != "win32":
            # X11 присылает прокрутку как Button-4 / Button-5.
            self.bind("<Button-4>", self._on_mousewheel, add="+")
            self.bind("<Button-5>", self._on_mousewheel, add="+")

        rows = [0]

        def section(text):
            tk.Label(form, text=text, bg=BG, fg=TEXT,
                     font=FONT_BOLD, anchor="w").grid(
                row=rows[0], column=0, columnspan=2, sticky="w",
                padx=(0, 8), pady=(10, 4))
            rows[0] += 1

        def field(label_text, widget, hint=None, sticky="ew"):
            r = rows[0]
            tk.Label(form, text=label_text, bg=BG, fg=TEXT_DIM, font=FONT_UI,
                     anchor="w").grid(row=r, column=0, sticky="w",
                                      padx=(0, 8), pady=2)
            widget.grid(row=r, column=1, sticky=sticky, pady=2)
            rows[0] += 1
            if hint:
                tk.Label(form, text=hint, bg=BG, fg=TEXT_DIM, font=FONT_UI,
                         anchor="w", wraplength=430, justify="left").grid(
                    row=rows[0], column=1, sticky="w")
                rows[0] += 1
            return widget

        self.var_name     = tk.StringVar()
        self.var_vcodec    = tk.StringVar()
        self.var_ext       = tk.StringVar()
        self.var_backend   = tk.StringVar(value="cpu")
        self.var_acodec    = tk.StringVar()
        self.var_qmode     = tk.StringVar(value="bitrate")
        self.var_quality   = tk.StringVar(value="8")
        self.var_preset    = tk.StringVar()
        self.var_pass1     = tk.StringVar()
        self.var_pass2     = tk.StringVar()
        self.var_gop       = tk.StringVar(value="30")
        self.var_extra     = tk.StringVar()
        self.var_aargs     = tk.StringVar()
        self.var_raw       = tk.StringVar()
        self.var_two_pass  = tk.BooleanVar(value=False)
        self.var_adv_enabled = tk.BooleanVar(value=False)
        self.var_show_advanced = tk.BooleanVar(value=False)

        self._form = form

        section("Основное")
        self.ent_name = field("Название:", make_entry(form, self.var_name))

        self.ent_vcodec_box = SuggestEntry(
            form, self.var_vcodec,
            [(item["title"], item["vcodec"]) for item in CODEC_CATALOG],
            on_pick=self._on_codec_pick)
        self.ent_vcodec = self.ent_vcodec_box.entry
        field("Видео-кодек:", self.ent_vcodec_box,
              hint="Выберите готовый вариант — остальные поля заполнятся сами. "
                   "Можно ввести и другой кодек ffmpeg.")
        self.ent_vcodec.bind(
            "<FocusOut>", lambda _e: self._refresh_speed_ui())

        self.ent_ext = field(
            "Контейнер:", make_entry(form, self.var_ext, width=10),
            sticky="w",
            hint="Расширение выходного файла: mp4, mkv, webm …")

        backend_box = tk.Frame(form, bg=BG)
        self._backend_radios = []
        for key, title in ENCODER_BACKENDS.items():
            rb = make_radio(backend_box, title, self.var_backend, key,
                            command=self._on_backend_change)
            rb.pack(side="left", padx=(0, 12))
            self._backend_radios.append(rb)
        field("Бэкенд:", backend_box, sticky="w",
              hint="CPU — медленнее, но качественнее. "
                   "GPU — быстрее (NVENC), если он есть в системе.")

        section("Качество и скорость")
        qmode_box = tk.Frame(form, bg=BG)
        self._qmode_radios = []
        for key, title in (("crf", "Постоянное качество (CRF)"),
                           ("bitrate", "Битрейт (Мбит/с)")):
            rb = make_radio(qmode_box, title, self.var_qmode, key,
                            command=self._refresh_quality_ui)
            rb.pack(side="left", padx=(0, 12))
            self._qmode_radios.append(rb)
        field("Режим:", qmode_box, sticky="w")

        self.ent_quality = field(
            "Качество по умолч.:", make_entry(form, self.var_quality, width=10),
            sticky="w")
        self.quality_hint = tk.Label(
            form, text="", bg=BG, fg=TEXT_DIM, font=FONT_UI, anchor="w",
            wraplength=430, justify="left")
        self.quality_hint.grid(row=rows[0], column=1, sticky="w")
        rows[0] += 1

        self.ent_preset_box = SuggestEntry(
            form, self.var_preset, _speed_choices(""), width=14)
        self.ent_preset = self.ent_preset_box.entry
        field("Скорость:", self.ent_preset_box)
        self.speed_hint = tk.Label(
            form, text="", bg=BG, fg=TEXT_DIM, font=FONT_UI, anchor="w",
            wraplength=430, justify="left")
        self.speed_hint.grid(row=rows[0], column=1, sticky="w")
        rows[0] += 1

        # Предупреждение о недопустимом пресете — отдельной красной строкой,
        # чтобы не перекрашивать всю подсказку.
        self._speed_warn_row = rows[0]
        self.speed_warn = tk.Label(
            form, text="", bg=BG, fg=WARN_FG, font=FONT_UI, anchor="w",
            wraplength=430, justify="left")
        rows[0] += 1

        self.chk_two_pass = make_check(
            form, "Разрешить двухпроходное кодирование", self.var_two_pass)
        field("Двупроход:", self.chk_two_pass, sticky="w",
              hint="Только для битрейта: точнее расход бит при низком битрейте.")

        self.chk_advanced = make_check(
            form, "Показать дополнительные параметры",
            self.var_show_advanced, command=self._toggle_advanced)
        self.chk_advanced.grid(row=rows[0], column=0, columnspan=2,
                               sticky="w", pady=(10, 4))
        rows[0] += 1

        self._adv_start_row = rows[0]

        section("Дополнительно")
        self.ent_gop = field(
            "GOP:", make_entry(form, self.var_gop, width=10), sticky="w",
            hint="Интервал ключевых кадров; 0 — не задавать.")
        self.ent_pass1 = field(
            "Пресет 1-го прохода:", make_entry(form, self.var_pass1, width=10),
            sticky="w", hint="Пусто — используется основной пресет.")
        self.ent_pass2 = field(
            "Пресет 2-го прохода:", make_entry(form, self.var_pass2, width=10),
            sticky="w", hint="Пусто — используется основной пресет.")
        self.ent_extra = field(
            "Доп. видео-аргументы:", make_entry(form, self.var_extra),
            hint="Через пробел: -pix_fmt yuv420p -row-mt 1")
        self.ent_acodec = field(
            "Аудио-кодек:", make_entry(form, self.var_acodec),
            hint="copy — без перекодирования, или aac / libopus …")
        self.ent_aargs = field(
            "Доп. аудио-аргументы:", make_entry(form, self.var_aargs),
            hint="Через пробел: -b:a 192k -ar 48000")
        self.ent_raw = field(
            "Произвольные аргументы:", make_entry(form, self.var_raw),
            hint="Вставляются как есть перед выходным файлом: "
                 "-movflags +faststart -tune film …")

        # ------------------------------------------- гибкая настройка
        section("Гибкая настройка — расширенный лог")

        tk.Label(form,
                 text="Аргументы ffmpeg. Если включено — полностью заменяют "
                      "базовые параметры. Подстановки: {input}, {output}, {ext}.",
                 bg=BG, fg=TEXT_DIM, font=FONT_UI, anchor="w",
                 wraplength=430, justify="left").grid(
            row=rows[0], column=0, columnspan=2, sticky="w")
        rows[0] += 1

        self.chk_adv = make_check(form, "Использовать расширенный лог",
                                  self.var_adv_enabled,
                                  command=self._on_adv_toggle)
        self.chk_adv.grid(row=rows[0], column=1, sticky="w", pady=(4, 2))
        rows[0] += 1

        adv_box = tk.Frame(form, bg=BG)
        adv_box.grid(row=rows[0], column=1, sticky="ew", pady=2)
        adv_box.columnconfigure(0, weight=1)
        self.txt_adv = tk.Text(
            adv_box, height=4, width=40, wrap="word",
            bg=FIELD_BG, fg=FIELD_FG, insertbackground=FIELD_FG,
            relief="sunken", bd=2, highlightthickness=0, font=FONT_MONO,
            selectbackground=ACCENT, selectforeground="#ffffff",
        )
        self.txt_adv.grid(row=0, column=0, sticky="ew")
        adv_sb = tk.Scrollbar(adv_box, command=self.txt_adv.yview,
                              bg=BTN_FACE, activebackground=BTN_FACE_HI,
                              troughcolor=BG_DEEP, relief="raised", bd=2,
                              highlightthickness=0)
        adv_sb.grid(row=0, column=1, sticky="ns")
        self.txt_adv.configure(yscrollcommand=adv_sb.set)
        rows[0] += 1

        tk.Label(form,
                 text="Пример: ffmpeg -i {input} -c:v libx264 -crf 20 "
                      "-preset slow {output}",
                 bg=BG, fg=TEXT_DIM, font=FONT_UI, anchor="w",
                 wraplength=430, justify="left").grid(
            row=rows[0], column=1, sticky="w")
        rows[0] += 1

        self._adv_end_row = rows[0]
        self._adv_rows = range(self._adv_start_row, self._adv_end_row)
        # Запоминаем виджеты заранее: после grid_remove() Tk перестаёт
        # показывать их в grid_slaves(), и вернуть их было бы нечем.
        self._adv_widgets = [
            w for w in form.winfo_children()
            if int(w.grid_info().get("row", -1)) in self._adv_rows
        ]

        # Поля, которые перекрывает расширенный лог. Имя остаётся
        # редактируемым всегда — оно не влияет на команду ffmpeg.
        self._base_widgets = [
            self.ent_vcodec, self.ent_vcodec_box.button,
            self.ent_ext, *self._backend_radios,
            *self._qmode_radios, self.ent_quality,
            self.ent_preset, self.ent_preset_box.button,
            self.ent_pass1, self.ent_pass2, self.ent_gop,
            self.chk_two_pass, self.ent_extra, self.ent_acodec,
            self.ent_aargs, self.ent_raw,
        ]

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        make_button(bottom, "Сохранить", self._save, width=22).pack(side="left")
        make_button(bottom, "Сброс к заводским", self._reset_to_defaults,
                    width=20).pack(side="left", padx=(8, 0))
        make_button(bottom, "Отмена", self._on_close, width=10).pack(side="right")

    # --------------------------------------------------- список и выбор
    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for cfg in self.configs:
            self.listbox.insert("end", cfg["name"])
        if self.selected_index is not None and 0 <= self.selected_index < len(self.configs):
            self.listbox.selection_set(self.selected_index)
            self.listbox.activate(self.selected_index)
        else:
            self.selected_index = None
            self._load_editor(None)

    def _on_select(self, _event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if self.selected_index is not None and self.selected_index != idx:
            self._apply_editor(silent=True)
        # ВАЖНО: сначала фиксируем новый индекс, затем грузим редактор.
        # Иначе _apply_editor() обновит элемент списка по старому индексу.
        self.selected_index = idx
        self._load_editor(self.configs[idx])

    def _select_index(self, idx: int):
        """Программно выбирает конфигурацию (список + редактор)."""
        if idx < 0 or idx >= len(self.configs):
            return
        self.selected_index = idx
        self._refresh_list()
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.activate(idx)
        self.listbox.see(idx)
        self._load_editor(self.configs[idx])

    def _load_editor(self, cfg: dict | None):
        if cfg is None:
            for var in (self.var_name, self.var_vcodec, self.var_ext,
                        self.var_preset, self.var_pass1, self.var_pass2,
                        self.var_gop, self.var_quality, self.var_extra,
                        self.var_acodec, self.var_aargs, self.var_raw):
                var.set("")
            self.var_backend.set("cpu")
            self.var_qmode.set("bitrate")
            self.var_two_pass.set(False)
            self.var_adv_enabled.set(False)
            self.var_show_advanced.set(False)
            self.txt_adv.configure(state="normal")
            self.txt_adv.delete("1.0", "end")
            self.txt_adv.configure(state="disabled")
            self._set_editor_enabled(False)
            self._toggle_advanced(scroll=False)
            return

        cfg = _sanitize_config(cfg)
        self.var_name.set(cfg["name"])
        self.var_vcodec.set(cfg["vcodec"])
        self.var_ext.set(cfg["ext"])
        self.var_backend.set(cfg["backend"])
        self.var_qmode.set(cfg["quality_mode"])
        self.var_quality.set(f"{cfg['default_quality']:g}")
        self.var_preset.set(cfg["preset"])
        self.var_pass1.set(cfg["pass1_preset"])
        self.var_pass2.set(cfg["pass2_preset"])
        self.var_gop.set(str(cfg["gop"]))
        self.var_extra.set(" ".join(cfg["extra_args"]))
        self.var_acodec.set(cfg["audio_codec"])
        self.var_aargs.set(" ".join(cfg["audio_args"]))
        self.var_raw.set(" ".join(cfg["raw_args"]))
        self.var_two_pass.set(bool(cfg["two_pass"]))

        adv = cfg["advanced_log"]
        self.var_adv_enabled.set(bool(adv))
        self.var_show_advanced.set(bool(adv))
        self.txt_adv.configure(state="normal")
        self.txt_adv.delete("1.0", "end")
        if adv:
            self.txt_adv.insert("1.0", adv)
        self._set_editor_enabled(True)
        self._refresh_quality_ui()
        self._refresh_speed_ui()
        self._toggle_advanced(scroll=False)
        self._on_adv_toggle()

    def _set_editor_enabled(self, enabled: bool):
        """Включает/выключает весь редактор (когда конфиг не выбран)."""
        state = "normal" if enabled else "disabled"
        for w in (self.ent_name, *self._base_widgets, self.chk_adv,
                  self.chk_advanced):
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        self.txt_adv.configure(
            state="normal" if enabled and self.var_adv_enabled.get() else "disabled")
        if enabled:
            self._refresh_quality_ui()
            self._refresh_speed_ui()
        else:
            self.chk_two_pass.configure(state="disabled")
            self._refresh_speed_ui()

    def _editor_vcodec(self) -> str:
        """Итоговый кодек с учётом CPU/GPU, как в команде ffmpeg."""
        return resolve_vcodec({
            "vcodec": self.var_vcodec.get().strip(),
            "backend": self.var_backend.get(),
        })

    def _refresh_quality_ui(self):
        """Обновляет подсказку и доступность двухпрохода под режим качества."""
        crf = self.var_qmode.get() == "crf"
        lo, hi = quality_range({
            "vcodec": self.var_vcodec.get().strip(),
            "backend": self.var_backend.get(),
        })
        if crf:
            self.quality_hint.configure(
                text=f"CRF {lo}–{hi}: меньше — лучше. Ориентир: 20–28 для "
                     f"H.264/H.265, 28–35 для AV1/VP9.")
        else:
            self.quality_hint.configure(
                text="Битрейт в Мбит/с. Для небольших файлов включите "
                     "двухпроход.")
        two_pass_ok = (
            self.selected_index is not None
            and not self.var_adv_enabled.get()
            and not crf
        )
        self.chk_two_pass.configure(
            state="normal" if two_pass_ok else "disabled")

    def _refresh_speed_ui(self):
        """Подставляет подсказки скорости для выбранного кодека."""
        vcodec = self._editor_vcodec()
        choices = _speed_choices(vcodec)
        self.ent_preset_box.set_values(choices)
        self.speed_hint.configure(text=_speed_hint(vcodec))
        current = self.var_preset.get().strip()
        if current and not _speed_value_ok(vcodec, current):
            self.speed_warn.configure(
                text=f"Текущее значение «{current}» не подходит — "
                     f"выберите из списка.")
            self.speed_warn.grid(row=self._speed_warn_row, column=1,
                                 sticky="w")
        else:
            self.speed_warn.grid_remove()

    def _on_codec_pick(self, vcodec: str):
        """Заполняет поля типовыми значениями выбранного кодека."""
        item = CODEC_BY_ID.get(vcodec)
        if not item:
            self._refresh_quality_ui()
            self._refresh_speed_ui()
            return
        self.var_vcodec.set(item["vcodec"])
        self.var_ext.set(item["ext"])
        self.var_qmode.set(item["quality_mode"])
        self.var_quality.set(f"{item['quality']:g}")
        self.var_preset.set(item["speed"])
        self.var_pass1.set(item.get("pass1", ""))
        self.var_pass2.set(item.get("pass2", ""))
        self.var_two_pass.set(bool(item.get("two_pass", False)))
        self.var_acodec.set(item["audio_codec"])
        self.var_aargs.set(" ".join(item["audio_args"]))
        self.var_extra.set(" ".join(item["extra_args"]))
        self.var_gop.set(str(item["gop"]))
        self._refresh_quality_ui()
        self._refresh_speed_ui()

    def _on_backend_change(self):
        self._refresh_quality_ui()
        self._refresh_speed_ui()

    def _toggle_advanced(self, scroll: bool = True):
        """Скрывает/показывает редкие поля, чтобы не пугать новичка."""
        show = bool(self.var_show_advanced.get())
        for w in self._adv_widgets:
            if show:
                w.grid()
            else:
                w.grid_remove()
        if show and scroll:
            self._form_canvas.yview_moveto(1.0)

    def _on_mousewheel(self, event):
        """Прокручивает форму колесом мыши, не мешая списку и логу."""
        widget = event.widget
        if isinstance(widget, (tk.Text, tk.Listbox)):
            return None
        # Windows/macOS: event.delta; X11: Button-4 (вверх) / Button-5 (вниз).
        num = getattr(event, "num", None)
        if num == 4:
            step = -1
        elif num == 5:
            step = 1
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return None
            step = -1 if delta > 0 else 1
        w = widget
        while w is not None and w is not self:
            if w is self._form_canvas:
                self._form_canvas.yview_scroll(step, "units")
                return "break"
            w = getattr(w, "master", None)
        return None

    def _on_adv_toggle(self):
        selected = self.selected_index is not None
        enabled = bool(self.var_adv_enabled.get())
        # Если включили расширенный лог, сразу показываем его поле —
        # иначе непонятно, почему остальные настройки стали серыми.
        if enabled and not self.var_show_advanced.get():
            self.var_show_advanced.set(True)
            self._toggle_advanced(scroll=False)
        self.txt_adv.configure(
            state="normal" if selected and enabled else "disabled")
        self._set_base_enabled(selected and not enabled)

    def _set_base_enabled(self, enabled: bool):
        """Блокирует поля, которые перекрывает расширенный лог.

        Имя конфигурации остаётся доступным: оно не влияет на команду ffmpeg.
        """
        state = "normal" if enabled else "disabled"
        for w in self._base_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        self._refresh_quality_ui()

    def _collect_editor(self) -> dict:
        adv = ""
        if self.var_adv_enabled.get():
            adv = self.txt_adv.get("1.0", "end").strip()
        base = {}
        if (self.selected_index is not None
                and 0 <= self.selected_index < len(self.configs)):
            base = dict(self.configs[self.selected_index])
        base.update({
            "name": self.var_name.get(),
            "vcodec": self.var_vcodec.get(),
            "ext": self.var_ext.get(),
            "backend": self.var_backend.get(),
            "quality_mode": self.var_qmode.get(),
            "default_quality": self.var_quality.get(),
            "preset": self.var_preset.get(),
            "pass1_preset": self.var_pass1.get(),
            "pass2_preset": self.var_pass2.get(),
            "gop": self.var_gop.get(),
            "two_pass": bool(self.var_two_pass.get()),
            "extra_args": _split_advanced(self.var_extra.get()),
            "audio_codec": self.var_acodec.get(),
            "audio_args": _split_advanced(self.var_aargs.get()),
            "raw_args": _split_advanced(self.var_raw.get()),
            "advanced_log": adv,
        })
        cfg = _sanitize_config(base)
        # Сохраняем незнакомые ключи, чтобы редактор не терял данные,
        # добавленные в configs.json вручную или будущими версиями.
        for key, value in base.items():
            cfg.setdefault(key, value)
        return cfg

    def _apply_editor(self, silent: bool = False) -> bool:
        if self.selected_index is None:
            if not silent:
                messagebox.showinfo(APP_TITLE, "Сначала выберите конфигурацию слева.",
                                    parent=self)
            return False
        if not silent and not self.var_name.get().strip():
            messagebox.showwarning(APP_TITLE, "Название конфигурации не может быть пустым.",
                                   parent=self)
            return False
        if not silent and not self.var_vcodec.get().strip():
            messagebox.showwarning(APP_TITLE, "Видео-кодек не может быть пустым.",
                                   parent=self)
            return False
        cfg = self._collect_editor()
        self.configs[self.selected_index] = cfg
        # Обновляем только текст элемента, не пересоздавая его и не трогая
        # выделение — иначе Tk сбрасывает selection во время обработки
        # <<ListboxSelect>> и подсветка «залипает» на прошлом конфиге.
        lb = self.listbox
        idx = self.selected_index
        if lb.get(idx) != cfg["name"]:
            lb.delete(idx)
            lb.insert(idx, cfg["name"])
        return True

    # --------------------------------------------------- действия
    def _unique_name(self, base: str) -> str:
        """Подбирает имя, которого ещё нет в списке конфигураций."""
        existing = {c["name"] for c in self.configs}
        if base not in existing:
            return base
        n = 2
        while f"{base} ({n})" in existing:
            n += 1
        return f"{base} ({n})"

    def _add(self):
        if self.selected_index is not None:
            self._apply_editor(silent=True)
        new_cfg = _sanitize_config(dict(NEUTRAL_CONFIG))
        new_cfg["name"] = self._unique_name(new_cfg["name"])
        self.configs.append(new_cfg)
        self.selected_index = len(self.configs) - 1
        self._refresh_list()
        self._load_editor(new_cfg)

    def _add_from_template(self, vcodec: str):
        """Создаёт конфигурацию из готового варианта кодека."""
        item = CODEC_BY_ID.get(vcodec)
        if item is None:
            return
        if self.selected_index is not None:
            self._apply_editor(silent=True)
        cfg = _sanitize_config({
            "name": item["title"],
            "vcodec": item["vcodec"],
            "ext": item["ext"],
            "quality_mode": item["quality_mode"],
            "default_quality": item["quality"],
            "preset": item["speed"],
            "pass1_preset": item.get("pass1", ""),
            "pass2_preset": item.get("pass2", ""),
            "extra_args": list(item["extra_args"]),
            "audio_codec": item["audio_codec"],
            "audio_args": list(item["audio_args"]),
            "raw_args": [],
            "two_pass": bool(item.get("two_pass", False)),
            "gop": item["gop"],
            "backend": "cpu",
            "advanced_log": "",
        })
        cfg["name"] = self._unique_name(item["title"])
        self.configs.append(cfg)
        self.selected_index = len(self.configs) - 1
        self._refresh_list()
        self._load_editor(cfg)

    def _duplicate(self):
        if self.selected_index is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите конфигурацию слева.",
                                parent=self)
            return
        self._apply_editor(silent=True)
        src = self.configs[self.selected_index]
        copy_cfg = _sanitize_config(dict(src))
        copy_cfg["name"] = src["name"] + " (копия)"
        self.configs.append(copy_cfg)
        self.selected_index = len(self.configs) - 1
        self._refresh_list()
        self._load_editor(copy_cfg)

    def _delete(self):
        if self.selected_index is None:
            messagebox.showinfo(APP_TITLE, "Сначала выберите конфигурацию слева.",
                                parent=self)
            return
        if len(self.configs) <= 1:
            messagebox.showwarning(APP_TITLE, "Нельзя удалить последнюю конфигурацию.",
                                   parent=self)
            return
        name = self.configs[self.selected_index]["name"]
        if not messagebox.askyesno(APP_TITLE,
                                   f"Удалить конфигурацию «{name}»?", parent=self):
            return
        del self.configs[self.selected_index]
        self.selected_index = min(self.selected_index, len(self.configs) - 1)
        self._refresh_list()
        self._load_editor(self.configs[self.selected_index])

    def _on_list_delete(self, _event=None):
        """Del в списке конфигураций — то же, что кнопка «Удалить»."""
        if self.selected_index is None:
            return "break"
        self._delete()
        return "break"

    # --------------------------------------------------- сохранение
    def _collect_ui_options(self) -> dict:
        return _sanitize_ui_options({
            "rescale_enabled": bool(self.var_opt_rescale.get()),
            "fps_enabled": bool(self.var_opt_fps.get()),
            "ffprobe_enabled": bool(self.var_opt_ffprobe.get()),
            "log_enabled": bool(self.var_opt_log.get()),
        })

    def _reset_to_defaults(self):
        """Возвращает встроенные конфигурации и сбрасывает прочие настройки."""
        if not messagebox.askyesno(
                APP_TITLE,
                "Сбросить все конфигурации к заводским?\n\n"
                "Пользовательские конфигурации будут удалены, "
                "опции GUI вернутся к значениям по умолчанию.",
                parent=self):
            return
        self.configs = default_configs()
        self.ui_options = dict(DEFAULT_UI_OPTIONS)
        self.var_opt_rescale.set(True)
        self.var_opt_fps.set(True)
        self.var_opt_ffprobe.set(True)
        self.var_opt_log.set(True)
        self.selected_index = 0
        try:
            save_configs(self.configs, ui_options=self.ui_options)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        self.app.set_configs(self.configs)
        self.app.set_ui_options(self.ui_options)
        self._refresh_list()
        if self.configs:
            self._select_index(0)
        messagebox.showinfo(APP_TITLE, "Конфигурации сброшены к заводским.",
                            parent=self)

    def _save(self) -> bool:
        # Сначала фиксируем правки текущей конфигурации — иначе изменения
        # в редакторе теряются при нажатии «Сохранить».
        if self.selected_index is not None and not self._apply_editor():
            return False
        ui_options = self._collect_ui_options()
        self.ui_options = dict(ui_options)
        try:
            save_configs(self.configs, ui_options=ui_options)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return False
        self.app.set_configs(self.configs)
        self.app.set_ui_options(ui_options)
        return True

    def _on_close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class TranscodeApp(_BaseTk):
    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x830")
        # Нижнюю границу высоты подгоняет _update_min_height(): она зависит
        # от того, какие панели включены в «Опциях GUI».
        self.minsize(860, 340)
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
                    icon_img = tk.PhotoImage(file=ICON_PNG_PATH)
                    self.iconphoto(True, icon_img)
                    self._icon_img = icon_img
                except Exception as e:
                    print("iconphoto failed:", e)
            else:
                print("Иконка .png не найдена, используется стандартная.")

        self._running = False
        self._cancel = False
        self._proc: subprocess.Popen | None = None
        self._duration = 0.0
        self._total_frames = 0
        self._src_width = 0
        self._src_height = 0
        self._src_fps = 0.0
        self._syncing_size = False
        self._taskbar_clear_id = None
        self._output_dir: str | None = None
        self._last_output: str | None = None
        self._syncing_scale = False

        self._current_status_text = "Готов."
        self._current_status_highlight = None

        self.configs: list[dict] = load_configs()
        self.ui_options: dict = load_ui_options()

        self._build_ui()
        self.apply_ui_options()

        self._refresh_codec_menu()
        self.codec_var.set(self.configs[0]["name"])
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

    # -------------------------------------------------------------- конфигурации
    def _current_config(self) -> dict:
        name = self.codec_var.get()
        for cfg in self.configs:
            if cfg["name"] == name:
                return cfg
        return self.configs[0]

    def _refresh_codec_menu(self):
        names = [c["name"] for c in self.configs]
        menu = self.codec_menu["menu"]
        menu.delete(0, "end")
        for n in names:
            menu.add_command(label=n,
                             command=tk._setit(self.codec_var, n,
                                               self._on_codec_change))
        if self.codec_var.get() not in names and names:
            self.codec_var.set(names[0])

    def set_configs(self, configs: list[dict]):
        self.configs = [dict(c) for c in configs]
        self._refresh_codec_menu()
        if self.codec_var.get() not in [c["name"] for c in self.configs]:
            self.codec_var.set(self.configs[0]["name"])
        self._on_codec_change()

    def set_ui_options(self, options: dict):
        """Применяет новые глобальные опции GUI и обновляет окно."""
        self.ui_options = _sanitize_ui_options(options)
        self.apply_ui_options()

    def apply_ui_options(self):
        """Показывает/скрывает блоки главного окна согласно опциям GUI."""
        opts = _sanitize_ui_options(self.ui_options)

        rescale_on = opts.get("rescale_enabled", True)
        fps_on = opts.get("fps_enabled", True)
        ffprobe_on = opts.get("ffprobe_enabled", True)
        log_on = opts.get("log_enabled", True)

        for w in getattr(self, "_scale_widgets", []):
            try:
                if rescale_on:
                    w.grid()
                else:
                    w.grid_remove()
            except Exception:
                pass
        for w in getattr(self, "_fps_widgets", []):
            try:
                if fps_on:
                    w.grid()
                else:
                    w.grid_remove()
            except Exception:
                pass

        info_frame = getattr(self, "info_frame", None)
        if info_frame is not None:
            if ffprobe_on:
                info_frame.pack(side="right", fill="y", padx=(16, 0))
            else:
                info_frame.pack_forget()

        log_group = getattr(self, "grp_log", None)
        if log_group is not None:
            if log_on:
                log_group.pack(fill="both", expand=True,
                               padx=10, pady=6)
            else:
                log_group.pack_forget()

        # При выключении опции сбрасываем её локальную галочку, чтобы
        # скрытый блок не влиял на команду ffmpeg.
        if not rescale_on and self.scale_enabled_var.get():
            self.scale_enabled_var.set(False)
            self._on_scale_toggle()
        if not fps_on and self.fps_enabled_var.get():
            self.fps_enabled_var.set(False)
            self._on_fps_toggle()
        self._refresh_func_box()

    def _open_settings(self):
        if self._running:
            self.set_status("Идёт транскодирование — дождитесь окончания.")
            return
        SettingsWindow(self)

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

        # ---------- конфигурация (пресет) ----------
        tk.Label(left, text="Конфигурация:", bg=BG, fg=TEXT, font=FONT_UI).grid(
            row=0, column=0, sticky="w", padx=6, pady=2)
        self.codec_var = tk.StringVar()
        codec_row = tk.Frame(left, bg=BG)
        codec_row.grid(row=0, column=1, sticky="w", padx=6, pady=2)
        self.codec_menu = make_option_menu(codec_row, self.codec_var, [""], width=24)
        self.codec_menu.pack(side="left")
        make_button(codec_row, "Настройки…", self._open_settings).pack(
            side="left", padx=(8, 0))

        # ---------- качество ----------
        self.quality_label = tk.Label(
            left, text="Битрейт видео (Мбит/с):",
            bg=BG, fg=TEXT, font=FONT_UI)
        self.quality_label.grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.quality_var = tk.StringVar(value="8")
        self.quality_entry = make_entry(left, self.quality_var, width=10)
        self.quality_entry.configure(
            justify="left",
            validate="key",
            validatecommand=(self.register(self._validate_quality_entry), "%P")
        )
        self.quality_entry.grid(row=1, column=1, sticky="w", padx=6, pady=2)

        self.target_enabled_var = tk.BooleanVar(value=False)
        self.target_cb = make_check(
            left,
            "Задать целевой размер файла (МБ) вместо битрейта",
            self.target_enabled_var,
            command=self._on_target_toggle,
        )
        self.target_cb.grid(row=2, column=0, columnspan=2,
                            sticky="w", padx=6, pady=(4, 0))

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
            sticky="w", padx=6, pady=(0, 2))

        tk.Label(left, text="Проходы:", bg=BG, fg=TEXT, font=FONT_UI).grid(
            row=5, column=0, sticky="w", padx=6, pady=2)
        passes = tk.Frame(left, bg=BG)
        passes.grid(row=5, column=1, sticky="w", padx=6, pady=2)
        self.pass_var = tk.IntVar(value=1)
        self.pass1_rb = make_radio(passes, "Однопроход", self.pass_var, 1)
        self.pass1_rb.pack(side="left")
        self.pass2_rb = make_radio(passes, "Двупроход", self.pass_var, 2)
        self.pass2_rb.pack(side="left", padx=(12, 0))

        # ---------- опции: три галочки в одну строку ----------
        opts_row = tk.Frame(left, bg=BG)
        opts_row.grid(row=6, column=0, columnspan=2,
                      sticky="w", padx=6, pady=(4, 0))

        self.scale_enabled_var = tk.BooleanVar(value=False)
        self.scale_cb = make_check(
            opts_row, "Рескейлинг", self.scale_enabled_var,
            command=self._on_scale_toggle)
        self.scale_cb.grid(row=0, column=0, sticky="w")

        self.fps_enabled_var = tk.BooleanVar(value=False)
        self.fps_cb = make_check(
            opts_row, "Понизить FPS", self.fps_enabled_var,
            command=self._on_fps_toggle)
        self.fps_cb.grid(row=0, column=1, sticky="w", padx=(16, 0))

        self.cleanup_var = tk.BooleanVar(value=False)
        self.cleanup_cb = make_check(
            opts_row, "Исходник → old_material", self.cleanup_var)
        self.cleanup_cb.grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.cleanup_cb.bind("<Enter>", self._on_cleanup_hover)
        self.cleanup_cb.bind("<Leave>", self._on_cleanup_unhover)

        # ---------- параметры включённых функций ----------
        self.func_box = tk.LabelFrame(
            left, text=" Параметры функций ",
            bg=BG, fg=TEXT, relief="groove", bd=2,
            font=FONT_BOLD, labelanchor="nw",
        )
        self.func_box.grid(row=7, column=0, columnspan=2,
                           sticky="ew", padx=6, pady=(4, 0))
        self.func_box.columnconfigure(0, weight=1)

        # рескейлинг
        self.scale_ctl = tk.Frame(self.func_box, bg=BG)
        self.scale_ctl.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))

        tk.Label(self.scale_ctl, text="Высота:", bg=BG, fg=TEXT_DIM,
                 font=FONT_UI).pack(side="left")
        self.scale_height_var = tk.StringVar(value="720")
        self.scale_height_entry = make_entry(
            self.scale_ctl, self.scale_height_var, width=7)
        self.scale_height_entry.configure(
            validate="key",
            validatecommand=(self.register(self._validate_int_entry), "%P"))
        self.scale_height_entry.pack(side="left", padx=(4, 12))

        self.scale_keep_aspect_var = tk.BooleanVar(value=True)
        self.scale_keep_cb = make_check(
            self.scale_ctl, "Сохранять пропорции (по высоте)",
            self.scale_keep_aspect_var, command=self._update_scale_preview)
        self.scale_keep_cb.pack(side="left")

        self.scale_preview_var = tk.StringVar(value="")
        self.scale_preview_label = tk.Label(
            self.func_box, textvariable=self.scale_preview_var,
            bg=BG, fg=TEXT_DIM, font=FONT_UI, anchor="w")
        self.scale_preview_label.grid(
            row=1, column=0, sticky="w", padx=6, pady=(0, 4))

        # понижение FPS
        self.fps_ctl = tk.Frame(self.func_box, bg=BG)
        self.fps_ctl.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 4))
        tk.Label(self.fps_ctl, text="Целевой FPS:", bg=BG, fg=TEXT_DIM,
                 font=FONT_UI).pack(side="left")
        self.fps_value_var = tk.StringVar(value="30")
        self.fps_entry = make_entry(self.fps_ctl, self.fps_value_var, width=8)
        self.fps_entry.configure(
            validate="key",
            validatecommand=(self.register(self._validate_float_entry), "%P"))
        self.fps_entry.pack(side="left", padx=(4, 12))
        self.fps_info_var = tk.StringVar(value="")
        tk.Label(self.fps_ctl, textvariable=self.fps_info_var, bg=BG, fg=TEXT_DIM,
                 font=FONT_UI).pack(side="left")

        # Виджеты, которые скрываются через «Настройки → Опции GUI».
        self._scale_widgets = [self.scale_cb]
        self._fps_widgets = [self.fps_cb]

        right = tk.LabelFrame(
            inner, text=" Информация о видео ",
            bg=BG, fg=TEXT, relief="groove", bd=2,
            font=FONT_BOLD, labelanchor="nw",
        )
        right.pack(side="right", fill="y", padx=(16, 0))
        self.info_frame = right

        info_rows = [
            ("Файл",         "file"),
            ("Длительность", "duration"),
            ("Кадров",       "frames"),
            ("Разрешение",   "res"),
            ("FPS",          "fps"),
            ("Видео",        "vcodec"),
            ("Аудио",        "acodec"),
            ("Аудио битрейт", "abitrate"),
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

        # Небольшой запас снизу: без него при включении опций сводка
        # подрастает на несколько пикселей вместе с левой колонкой.
        tk.Frame(right, bg=BG, height=8).grid(
            row=len(info_rows), column=0, columnspan=2)

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
        self.grp_log = grp_log
        self.log = tk.Text(
            grp_log, wrap="none", height=8,
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
        self._on_scale_toggle()
        self._on_fps_toggle()
        self._reset_info()

    # ---------------------------------------------------------- валидация полей
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

    def _validate_int_entry(self, new_text):
        if not new_text:
            return True
        return new_text.isdigit()

    def _validate_float_entry(self, new_text):
        if not new_text:
            return True
        clean = new_text.replace(',', '.')
        if clean.count('.') > 1:
            return False
        for char in clean:
            if not char.isdigit() and char != '.':
                return False
        return True

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
        files = get_clipboard_files()
        valid_files = [f for f in files if Path(f).suffix.lower() in VIDEO_EXTENSIONS] if files else []

        if not valid_files:
            try:
                text = self.clipboard_get()
                if text:
                    text = text.strip().strip('"').strip("'")
                    if os.path.isfile(text) and Path(text).suffix.lower() in VIDEO_EXTENSIONS:
                        valid_files.append(text)
            except tk.TclError:
                pass

        if valid_files:
            if self._running:
                self.set_status("Идёт транскодирование — дождитесь окончания.")
                return
            target_file = valid_files[0]
            self._set_input_file(target_file, user_selected=True)
            self.set_status(f"Вставлен файл: {os.path.basename(target_file)}")
            self._log(f"Вставлен файл из буфера: {target_file}\n")
            return

        if w == self.file_entry:
            try:
                text = self.clipboard_get()
                if text:
                    self.file_var.set(text.strip())
                    return
            except tk.TclError:
                pass

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

    # ---------------------------------------------------------- размер/битрейт
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

    def _on_codec_change(self):
        if not getattr(self, "configs", None):
            return
        cfg = self._current_config()
        target_mode = self.target_enabled_var.get()

        if cfg["quality_mode"] == "crf" and not target_mode:
            lo, hi = quality_range(cfg)
            self.quality_label.configure(
                text=f"CRF ({lo}–{hi}, меньше — лучше):")
        else:
            self.quality_label.configure(text="Битрейт видео (Мбит/с):")
        self.quality_var.set(f"{cfg['default_quality']:g}")

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
        cfg = self._current_config()
        if not cfg:
            return
        # Двупроход имеет смысл только для битрейта/целевого размера и
        # программных кодеков: CRF, GPU и расширенный лог его не используют.
        target_mode = self.target_enabled_var.get()
        advanced = bool(str(cfg.get("advanced_log", "") or "").strip())
        vcodec = resolve_vcodec(cfg)
        two_pass_allowed = (
            bool(cfg.get("two_pass", False))
            and not advanced
            and vcodec not in GPU_CODECS
            and (cfg.get("quality_mode") != "crf" or target_mode)
        )
        if two_pass_allowed:
            self.pass2_rb.configure(state="normal")
        else:
            self.pass2_rb.configure(state="disabled")
            if self.pass_var.get() == 2:
                self.pass_var.set(1)

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

    # ---------------------------------------------------------- рескейлинг
    def _on_scale_toggle(self):
        enabled = self.scale_enabled_var.get()
        state = "normal" if enabled else "disabled"
        self.scale_height_entry.configure(state=state)
        self.scale_keep_cb.configure(state=state)
        self._update_scale_preview()
        self._refresh_func_box()

    def _refresh_func_box(self):
        """Показывает блок «Параметры функций» и строки включённых опций."""
        rescale_on = (self.ui_options.get("rescale_enabled", True)
                      and self.scale_enabled_var.get())
        fps_on = (self.ui_options.get("fps_enabled", True)
                  and self.fps_enabled_var.get())
        for widget, visible in ((self.scale_ctl, rescale_on),
                                (self.scale_preview_label, rescale_on),
                                (self.fps_ctl, fps_on)):
            if visible:
                widget.grid()
            else:
                widget.grid_remove()
        if rescale_on or fps_on:
            self.func_box.grid()
        else:
            self.func_box.grid_remove()
        self._update_min_height()

    def _update_min_height(self):
        """Подгоняет минимальную высоту окна под видимые блоки.

        Скрытые через «Опции GUI» панели больше не оставляют пустого
        запаса внизу: окно сжимается до фактического содержимого.
        Журналу при этом всегда остаётся место на пару строк.
        """
        try:
            self.update_idletasks()
        except tk.TclError:
            return
        total = self.winfo_reqheight()
        log_group = getattr(self, "grp_log", None)
        if log_group is not None and log_group.winfo_manager():
            info = log_group.pack_info()
            pady = info.get("pady", 0)
            if isinstance(pady, (tuple, list)):
                pady = sum(int(v) for v in pady)
            try:
                total -= int(log_group.winfo_reqheight()) + int(pady)
            except (TypeError, ValueError):
                pass
            total += 72  # минимум на 2–3 строки лога
        self.minsize(860, max(340, total))

    def _scaled_size(self) -> tuple[int, int] | None:
        """Вычисляет целевые (ширина, высота) по желаемой высоте."""
        raw = self.scale_height_var.get().strip()
        if not raw.isdigit():
            return None
        target_h = int(raw)
        if target_h <= 0:
            return None
        w, h = self._src_width, self._src_height
        if w <= 0 or h <= 0:
            return (0, target_h)  # размеры ещё неизвестны — вернём только высоту
        if self.scale_keep_aspect_var.get():
            target_w = max(2, int(round(w * target_h / h)))
            target_w -= target_w % 2
            target_h -= target_h % 2
            return (target_w, target_h)
        return (max(2, target_h), target_h)

    def _update_scale_preview(self, *_):
        if not self.scale_enabled_var.get():
            self.scale_preview_var.set("")
            return
        raw = self.scale_height_var.get().strip()
        if not raw.isdigit() or int(raw) <= 0:
            self.scale_preview_var.set("Укажите положительную высоту.")
            return
        if self._src_width <= 0 or self._src_height <= 0:
            self.scale_preview_var.set(
                f"Высота: {raw}px (выберите файл, чтобы увидеть итоговое разрешение).")
            return
        size = self._scaled_size()
        if not size or size[0] <= 0:
            self.scale_preview_var.set("")
            return
        w, h = size
        self.scale_preview_var.set(
            f"{self._src_width}×{self._src_height}  →  {w}×{h}")

    def _scale_filter(self) -> str:
        """Возвращает строку видео-фильтра scale=… или пустую."""
        if not self.ui_options.get("rescale_enabled", True):
            return ""
        if not self.scale_enabled_var.get():
            return ""
        size = self._scaled_size()
        if not size or size[1] <= 0:
            raise ValueError("укажите корректную высоту для рескейлинга")
        w, h = size
        if w > 0:
            return f"scale={w}:{h}"
        # ширина неизвестна — масштабируем по высоте с сохранением пропорций
        if self.scale_keep_aspect_var.get():
            return f"scale=-2:{h}"
        return f"scale={h}:{h}"

    # ---------------------------------------------------------- понижение FPS
    def _on_fps_toggle(self):
        enabled = self.fps_enabled_var.get()
        self.fps_entry.configure(state="normal" if enabled else "disabled")
        self._update_fps_info()
        self._refresh_func_box()

    def _update_fps_info(self):
        if not self.fps_enabled_var.get():
            self.fps_info_var.set("")
            return
        if self._src_fps > 0:
            self.fps_info_var.set(f"(в исходнике {_fmt_fps(self._src_fps)})")
        else:
            self.fps_info_var.set("")

    def _fps_value(self) -> float:
        if not self.ui_options.get("fps_enabled", True):
            return 0.0
        if not self.fps_enabled_var.get():
            return 0.0
        raw = self.fps_value_var.get().replace(",", ".").strip()
        try:
            v = float(raw)
        except ValueError:
            raise ValueError("укажите корректный FPS")
        if v <= 0:
            raise ValueError("FPS должен быть больше нуля")
        if self._src_fps > 0 and v >= self._src_fps - 0.01:
            raise ValueError("целевой FPS должен быть меньше исходного "
                             f"({_fmt_fps(self._src_fps)})")
        return v

    # ---------------------------------------------------------- информация
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
        abr = float(info.get("abitrate", 0) or 0)
        self.info_vars["abitrate"].set(
            f"{abr:.0f} кбит/с" if abr > 0 else "—")
        self.info_vars["size"].set(
            _fmt_size(info["size_bytes"]) if info["size_bytes"] > 0 else "—")

    def _on_file_change(self, *_):
        path = self.file_var.get().strip().strip('"')
        self._duration = 0.0
        self._total_frames = 0
        self._src_width = 0
        self._src_height = 0
        self._src_fps = 0.0
        self._reset_info()
        self._update_target_label()
        self._update_scale_preview()
        self._update_fps_info()
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
                self._src_width = int(info.get("width", 0) or 0)
                self._src_height = int(info.get("height", 0) or 0)
                self._src_fps = float(info.get("fps", 0) or 0)
                self._apply_info(path, info)
                self._update_target_label()
                self._update_scale_preview()
                self._update_fps_info()
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
        cfg = self._current_config()

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
        if cfg["quality_mode"] == "crf":
            lo, hi = quality_range(cfg)
            try:
                q = int(float(raw))
            except ValueError:
                raise ValueError(f"CRF должен быть целым числом {lo}..{hi}")
            if not (lo <= q <= hi):
                raise ValueError(f"CRF должен быть целым {lo}..{hi}")
        else:
            try:
                q = float(raw)
            except ValueError:
                raise ValueError("битрейт должен быть числом")
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

        cfg = self._current_config()
        ext = cfg["ext"]
        adv = str(cfg.get("advanced_log", "") or "").strip()
        advanced = bool(adv)
        vcodec = resolve_vcodec(cfg)
        two_pass = (self.pass_var.get() == 2
                    and bool(cfg.get("two_pass", False))
                    and not advanced
                    and vcodec not in GPU_CODECS
                    and (cfg.get("quality_mode") != "crf"
                         or self.target_enabled_var.get()))

        quality, target_mode = 0.0, False
        scale_filter, fps_value = "", 0.0
        if advanced:
            # Расширенный лог задаёт команду целиком. Не валидируем и не
            # применяем поля главного окна — иначе «мусор» в них мешает
            # запуску, хотя на команду всё равно не влияет.
            target_mode = False
        else:
            try:
                quality, target_mode = self._resolve_quality()
            except ValueError as e:
                messagebox.showerror(APP_TITLE, f"Ошибка: {e}")
                return

            try:
                scale_filter = self._scale_filter()
            except ValueError as e:
                messagebox.showerror(APP_TITLE, f"Ошибка рескейлинга: {e}")
                return

            try:
                fps_value = self._fps_value()
            except ValueError as e:
                messagebox.showerror(APP_TITLE, f"Ошибка FPS: {e}")
                return

        out = self._out_path(inp, ext)
        out_dir = os.path.dirname(os.path.abspath(out))
        if not os.path.isdir(out_dir):
            messagebox.showerror(
                APP_TITLE, f"Папка для результата не найдена:\n{out_dir}")
            return

        commands = build_commands(cfg, inp, out, quality, two_pass,
                                  target_mode, scale_filter, fps_value)

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self._set_progress(0.0)
        self._log(f"Вход:   {inp}\nВыход:  {out}\n")
        shown_codec = resolve_vcodec(cfg)
        self._log(f"Конфигурация: {cfg['name']}  (видео: {shown_codec})\n")
        backend = cfg.get("backend", "cpu")
        self._log(f"Бэкенд: {ENCODER_BACKENDS.get(backend, backend)}\n")
        if advanced:
            self._log("Режим: расширенный лог (перекрывает параметры редактора)\n")
            ignored = []
            if self.target_enabled_var.get():
                ignored.append("целевой размер")
            if self.scale_enabled_var.get():
                ignored.append("рескейлинг")
            if self.fps_enabled_var.get():
                ignored.append("FPS")
            if self.pass_var.get() == 2:
                ignored.append("двупроход")
            if ignored:
                self._log("Игнорируются (заданы в логе): "
                          + ", ".join(ignored) + "\n")
        if target_mode:
            self._log(f"Режим:  целевой размер {self.target_size_var.get()} МБ "
                      f"→ {quality:.2f} Мбит/с\n")
        if scale_filter:
            self._log(f"Рескейлинг: {scale_filter}\n")
        if fps_value > 0:
            self._log(f"FPS:   → {fps_value:g}\n")
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
        self._update_min_height()
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
            # Кнопка выше строки статуса: без пересчёта минимум остаётся
            # заниженным и при сжатии окна кнопка обрезается.
            self._update_min_height()

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
