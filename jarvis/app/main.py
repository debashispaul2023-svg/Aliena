# #__________required to install_________

#pip install speechrecognition pyttsx3 opencv-python numpy pywhatkit psutil pyautogui screen-brightness-control keyboard mss google-generativeai AppOpener PyQt6 Pillow requests pyperclip

import os
import re
import sys
import json
import time
import platform
import smtplib
import imaplib
import email as email_lib
import threading
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
import math

# Optional desktop / voice / vision dependencies — soft import so missing
# packages produce diagnostics instead of a hard crash at import time.
_OPTIONAL_IMPORT_ERRORS: list[str] = []

def _optional_import(name: str, import_fn):
    try:
        return import_fn()
    except Exception as exc:  # ImportError and backend init issues
        _OPTIONAL_IMPORT_ERRORS.append(f"{name}: {exc}")
        return None

pyperclip = _optional_import("pyperclip", lambda: __import__("pyperclip"))
sr = _optional_import("speech_recognition", lambda: __import__("speech_recognition"))
pyttsx3 = _optional_import("pyttsx3", lambda: __import__("pyttsx3"))
cv2 = _optional_import("cv2", lambda: __import__("cv2"))
np = _optional_import("numpy", lambda: __import__("numpy"))
pywhatkit = _optional_import("pywhatkit", lambda: __import__("pywhatkit"))
psutil = _optional_import("psutil", lambda: __import__("psutil"))
pyautogui = _optional_import("pyautogui", lambda: __import__("pyautogui"))
sbc = _optional_import("screen_brightness_control", lambda: __import__("screen_brightness_control"))
keyboard = _optional_import("keyboard", lambda: __import__("keyboard"))
mss = _optional_import("mss", lambda: __import__("mss"))
_appopener = _optional_import("AppOpener", lambda: __import__("AppOpener"))
app_open = getattr(_appopener, "open", None) if _appopener else None
app_close = getattr(_appopener, "close", None) if _appopener else None
Image = _optional_import("PIL.Image", lambda: __import__("PIL.Image", fromlist=["Image"]))

_qt_widgets = _optional_import("PyQt6.QtWidgets", lambda: __import__("PyQt6.QtWidgets", fromlist=["QApplication"]))
_qt_core = _optional_import("PyQt6.QtCore", lambda: __import__("PyQt6.QtCore", fromlist=["Qt"]))
_qt_gui = _optional_import("PyQt6.QtGui", lambda: __import__("PyQt6.QtGui", fromlist=["QIcon"]))

if _qt_widgets:
    QApplication = _qt_widgets.QApplication
    QLabel = _qt_widgets.QLabel
    QWidget = _qt_widgets.QWidget
    QSystemTrayIcon = _qt_widgets.QSystemTrayIcon
    QMenu = _qt_widgets.QMenu
    QLineEdit = _qt_widgets.QLineEdit
    QPushButton = _qt_widgets.QPushButton
else:
    QApplication = QLabel = QWidget = QSystemTrayIcon = QMenu = QLineEdit = QPushButton = None

if _qt_core:
    Qt = _qt_core.Qt
    QObject = _qt_core.QObject
    pyqtSignal = _qt_core.pyqtSignal
    QTimer = _qt_core.QTimer
else:
    Qt = QObject = pyqtSignal = QTimer = None

if _qt_gui:
    QIcon = _qt_gui.QIcon
    QAction = _qt_gui.QAction
    QPixmap = _qt_gui.QPixmap
    QColor = _qt_gui.QColor
    QFont = _qt_gui.QFont
    QPainter = _qt_gui.QPainter
    QBrush = _qt_gui.QBrush
    QPen = _qt_gui.QPen
else:
    QIcon = QAction = QPixmap = QColor = QFont = QPainter = QBrush = QPen = None

DESKTOP_AVAILABLE = all(x is not None for x in (QApplication, pyttsx3, sr))

# ================= MODULAR IMPORTS (Phase 1) =================
from jarvis.config import load_config, save_config
from jarvis.logger import setup_logging, log_and_print
from jarvis.ai.client import GeminiClient
from jarvis.memory import MemoryStore
from jarvis.memory.store import (
    CATEGORY_LONG_TERM,
    CATEGORY_USER_PROFILE,
    CATEGORY_PREFERENCE,
    CATEGORY_GOAL,
    CATEGORY_PROJECT,
)
from jarvis.skills import SkillRegistry, ExperienceStore, LearningPipeline

# ================= PATHS =================
# Base directory is the directory that contains the config file.
# When running as a module or script, we use the resolved base from config
# (cwd or JARVIS_BASE_DIR). This keeps jarvis_*.json next to where the user runs it.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Override: prefer the config module's resolution for data files
from jarvis.config import _resolve_base_dir
BASE_DIR = str(_resolve_base_dir())
CONFIG_FILE = os.path.join(BASE_DIR, "jarvis_config.json")
NOTES_FILE = os.path.join(BASE_DIR, "jarvis_notes.json")
MEMORY_FILE = os.path.join(BASE_DIR, "jarvis_memory.json")
MEMORY_DB = os.path.join(BASE_DIR, "jarvis_memory.db")
SKILLS_DB = os.path.join(BASE_DIR, "jarvis_skills.db")
LOG_FILE = os.path.join(BASE_DIR, "jarvis.log")

# ================= LOGGING =================
logger = setup_logging(log_file=LOG_FILE)

# ================= CONFIG =================
config = load_config(BASE_DIR)
if not os.path.exists(CONFIG_FILE):
    save_config(config, BASE_DIR)

# ================= AI CLIENT (graceful if key missing) =================
ai_client = GeminiClient()
if not ai_client.available:
    log_and_print(
        f"AI features disabled: {ai_client.last_error}. "
        "Set GEMINI_API_KEY to enable conversation, code generation, etc.",
        "warning",
    )
# Compatibility alias so any remaining model.generate_content calls work
model = ai_client

# ================= PERMANENT MEMORY (SQLite) =================
memory_store = MemoryStore(MEMORY_DB)
try:
    migrated = memory_store.migrate_from_json(
        MEMORY_FILE, backup_dir=os.path.join(BASE_DIR, "jarvis_backup")
    )
    if migrated:
        log_and_print(f"Migrated {migrated} conversation turns from jarvis_memory.json into SQLite.")
except Exception as e:
    log_and_print(f"Memory migration skipped or failed: {e}", "warning")

# ================= SKILL LIBRARY + EXPERIENCE (SQLite, separate DB) =================
skill_registry = SkillRegistry(SKILLS_DB)
experience_store = ExperienceStore(SKILLS_DB)
learning_pipeline = LearningPipeline(skill_registry, experience_store)

# ================= MULTI-AGENT ORCHESTRATOR (Phase 4) =================
try:
    from jarvis.core import Orchestrator

    orchestrator = Orchestrator(
        workspace=os.path.join(BASE_DIR, "orchestration_workspace"),
        skill_registry=skill_registry,
        memory_store=memory_store,
        experience_store=experience_store,
        learning_pipeline=learning_pipeline,
    )
except Exception as e:
    orchestrator = None
    log_and_print(f"Orchestrator init deferred: {e}", "warning")

# ================= RESOURCE ACQUISITION (Phases B–F) =================
resource_handler = None
resource_acquisition = None
try:
    from jarvis.resources import (
        DownloadManager,
        ResourceRegistry,
        ResourceAcquisitionService,
        AcquisitionPolicy,
    )
    from jarvis.resources.commands import ResourceCommandHandler
    from jarvis.ai.resource_finder import ResourceFinder
    from jarvis.ai.providers.multi import MultiSearchAdapter
    from jarvis.ai.providers.web_search import DuckDuckGoHTMLAdapter
    from jarvis.ai.providers.pypi import PyPISearchAdapter
    from jarvis.ai.providers.github import GitHubSearchAdapter

    _res_root = os.path.join(BASE_DIR, "JarvisResources")
    _res_db = os.path.join(BASE_DIR, "jarvis_resources.db")
    _res_registry = ResourceRegistry(_res_db)
    _res_downloader = DownloadManager(_res_root)
    try:
        _res_finder = ResourceFinder(
            adapter=MultiSearchAdapter(
                [PyPISearchAdapter(), GitHubSearchAdapter(), DuckDuckGoHTMLAdapter()]
            )
        )
    except Exception:
        _res_finder = ResourceFinder()
    resource_acquisition = ResourceAcquisitionService(
        finder=_res_finder,
        downloader=_res_downloader,
        registry=_res_registry,
        policy=AcquisitionPolicy(auto_download_public=False),
        resource_root=_res_root,
    )
    if orchestrator is not None:
        orchestrator.resource_finder = _res_finder
        orchestrator.resource_acquisition = resource_acquisition

    def _resource_speak(msg: str) -> None:
        try:
            speak(msg)
        except Exception:
            log_and_print(msg)

    resource_handler = ResourceCommandHandler(
        service=resource_acquisition,
        speak=_resource_speak,
    )
except Exception as e:
    resource_acquisition = None
    resource_handler = None
    log_and_print(f"Resource acquisition init deferred: {e}", "warning")

# ================= EMAIL CONFIG (optional) =================
EMAIL_ADDRESS = os.environ.get("JARVIS_EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("JARVIS_EMAIL_APP_PASSWORD")
IMAP_HOST = os.environ.get("JARVIS_IMAP_HOST", "imap.gmail.com")
SMTP_HOST = os.environ.get("JARVIS_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("JARVIS_SMTP_PORT", "587"))

# ================= VOICE ENGINE =================
engine = None
voices = []
if pyttsx3 is not None:
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty("voices") or []
    except Exception as _tts_exc:
        _OPTIONAL_IMPORT_ERRORS.append(f"pyttsx3.init: {_tts_exc}")
        engine = None
        voices = []
else:
    _OPTIONAL_IMPORT_ERRORS.append("pyttsx3: package not installed")


def pick_voice():
    # কনফিগে নির্দিষ্ট index দেওয়া থাকলে সেটাই ব্যবহার হবে
    idx = config.get("voice_index")
    if isinstance(idx, int):
        try:
            return voices[idx].id
        except IndexError:
            pass

    # নাহলে নাম/gender দেখে female ভয়েস অটো-ডিটেক্ট করার চেষ্টা
    female_hints = ["female", "zira", "susan", "samantha", "victoria", "hazel", "sara"]
    for v in voices:
        name = (v.name or "").lower()
        v_id = (v.id or "").lower()
        gender = getattr(v, "gender", None)
        if (gender and "female" in str(gender).lower()) or any(h in name or h in v_id for h in female_hints):
            return v.id

    # কিছু না পেলে ডিফল্ট প্রথম ভয়েস
    return voices[0].id if voices else None


selected_voice_id = pick_voice() if engine is not None else None
if engine is not None:
    if selected_voice_id:
        engine.setProperty("voice", selected_voice_id)
    engine.setProperty("rate", config.get("voice_rate", 180))
    engine.setProperty("volume", config.get("voice_volume", 1.0))
engine_lock = threading.Lock()  # pyttsx3 is not thread-safe

# ================= UI SIGNALS (thread-safe UI updates) =================
if QObject is not None and pyqtSignal is not None:
    class JarvisSignals(QObject):
        status_update = pyqtSignal(str)
        command_update = pyqtSignal(str)
        mood_update = pyqtSignal(str)
        keyboard_mode = pyqtSignal(bool)
else:
    class JarvisSignals:  # type: ignore
        """Stub when PyQt6 is unavailable."""
        status_update = command_update = mood_update = keyboard_mode = None


signals = None  # main() এ QApplication তৈরির পর সেট হবে


def emit_status(text):
    if signals is not None:
        signals.status_update.emit(text)


def emit_command(text):
    if signals is not None:
        signals.command_update.emit(text)


def emit_mood(mood):
    if signals is not None:
        signals.mood_update.emit(mood)


def emit_keyboard_mode(show):
    if signals is not None:
        signals.keyboard_mode.emit(show)


# ================= MOOD DETECTION =================
ANGRY_TRIGGERS = [
    "stupid", "dumb", "shut up", "useless", "idiot", "hate you", "worst",
    "baje", "murkho", "boka", "chup kor", "faltu",
]
HAPPY_TRIGGERS = [
    "love you", "great job", "awesome", "thank you", "thanks", "valo",
    "darun", "excellent", "good job", "best", "amazing",
]


def detect_mood(query):
    q = query.lower()
    if any(word in q for word in ANGRY_TRIGGERS):
        return "angry"
    if any(word in q for word in HAPPY_TRIGGERS):
        return "happy"
    return "idle"


# ================= SPEAK / LISTEN =================
def speak(text):
    try:
        log_and_print(f"Jarvis: {text}")
        emit_status(text)
        # Prefer free Edge neural voice (no API key). ElevenLabs only if key exists.
        try:
            from jarvis.app.tts_edge import synthesize as edge_synthesize
            audio = edge_synthesize(text, voice=config.get("edge_voice", "en-US-JennyNeural"))
            if audio is None:
                from jarvis.app.tts_eleven import synthesize
                audio = synthesize(text, voice_id=config.get("elevenlabs_voice_id"))
            if audio is not None:
                import subprocess
                for player in ("ffplay", "mpv", "aplay"):
                    if subprocess.call(["which", player], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                        subprocess.run(
                            [player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio)]
                            if player == "ffplay"
                            else [player, str(audio)],
                            check=False,
                        )
                        return
                log_and_print(f"ElevenLabs audio saved: {audio}")
                return
        except Exception as exc:
            log_and_print(f"ElevenLabs TTS skipped: {exc}", "error")
        if engine is None:
            return
        with engine_lock:
            engine.say(text)
            engine.runAndWait()
    except Exception as e:
        log_and_print(f"Error in speak: {e}", "error")


def check_microphone_available():
    """মাইক্রোফোন আছে কিনা এবং সেটা আসলে খোলা যায় কিনা — দুটোই চেক করে।"""
    try:
        mic_names = sr.Microphone.list_microphone_names()
        if not mic_names:
            return False
        # তালিকায় নাম থাকলেও ডিভাইসটা আসলে ওপেন করা যায় কিনা সেটা নিশ্চিত করা হচ্ছে
        with sr.Microphone():
            pass
        return True
    except Exception as e:
        log_and_print(f"Microphone check failed, no mic available: {e}", "error")
        return False


def take_command():
    r = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            print("Listening...")
            emit_status("Listening...")
            r.pause_threshold = 1
            r.adjust_for_ambient_noise(source, duration=1)
            audio = r.listen(source, timeout=5, phrase_time_limit=8)
        print("Recognizing...")

        languages = config.get("speech_languages") or ["en-in"]
        query = None
        last_error = None
        for lang in languages:
            try:
                query = r.recognize_google(audio, language=lang)
                break
            except sr.UnknownValueError:
                last_error = "unknown_value"
                continue
            except sr.RequestError as e:
                last_error = e
                continue

        if query is None:
            if isinstance(last_error, sr.RequestError) or (last_error and last_error != "unknown_value"):
                log_and_print(f"Speech recognition service error: {last_error}", "error")
            return "none"

        log_and_print(f"User: {query}")
        return query.lower()
    except sr.WaitTimeoutError:
        return "none"
    except Exception as e:
        log_and_print(f"Error in take_command: {e}", "error")
        return "none"


# ================= CONVERSATION MEMORY =================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_and_print(f"Memory load error: {e}", "error")
    return []


def save_memory(history):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        log_and_print(f"Memory save error: {e}", "error")


conversation_history = load_memory()


def remember(role, text):
    conversation_history.append({"role": role, "text": text, "time": datetime.now().isoformat()})
    max_turns = config.get("max_memory_turns", 6)
    del conversation_history[: max(0, len(conversation_history) - max_turns * 2)]
    save_memory(conversation_history)


def build_context_prompt(query):
    history_lines = [f"{h['role']}: {h['text']}" for h in conversation_history[-config.get('max_memory_turns', 6) * 2:]]
    history_block = "\n".join(history_lines)
    user_name = config.get("user_name", "Sir")
    assistant_name = config.get("assistant_name", "Jarvis")
    personality = config.get("personality_level", "high")
    if personality == "low":
        tone_line = (
            f"Right now keep your tone calm, warm, and a bit more serious/professional — light warmth, "
            f"minimal sass, straight to the point."
        )
    else:
        tone_line = (
            f"You're openly an AI assistant — never pretend to be a human — but your personality is "
            f"full of energy: clever comebacks, playful teasing, a bit dramatic when {user_name} teases you, "
            f"but always warm and genuinely helpful underneath the sass."
        )
    # Inject only relevant long-term memories (not the whole database)
    memory_block = ""
    try:
        relevant = memory_store.relevant_for_prompt(query, limit=8)
        if relevant:
            memory_block = (
                "\nRelevant things you remember about the user / projects:\n"
                + memory_store.format_for_prompt(relevant)
                + "\n"
            )
    except Exception as e:
        log_and_print(f"Memory retrieval error: {e}", "error")

    return (
        f"You are {assistant_name}, a witty, lively AI companion talking to {user_name}. "
        f"{tone_line} Mix natural Banglish/English in your "
        f"replies to match how {user_name} talks. Keep replies short (1-3 sentences), fun, and conversational. "
        f"After the personality, always actually help with whatever {user_name} needs.\n\n"
        f"IMPORTANT FORMAT RULE: Start your reply with exactly one emotion tag on its own — "
        f"either [idle], [happy], or [angry] — representing how you feel about this message, "
        f"then a space, then your actual reply. Use [angry] only if {user_name} is teasing, "
        f"insulting, or being dramatic with you. Use [happy] for good news, compliments, or "
        f"fun topics. Use [idle] otherwise. Example: [happy] Omg yes, let's do that!\n"
        f"{memory_block}\n"
        f"Conversation so far:\n{history_block}\n\n"
        f"{user_name}: {query}\n{assistant_name}:"
    )


def handle_remember_command(query: str) -> bool:
    """'remember this ...' or 'remember that ...' — stores a long-term memory."""
    text = query
    for prefix in ("remember this", "remember that", "remember"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip(" :,-")
            break
    if not text:
        speak("What should I remember?")
        return True
    rec = memory_store.save(
        content=text,
        category=CATEGORY_LONG_TERM,
        tags=["explicit"],
        importance=0.7,
        source="user",
    )
    if rec is None:
        speak("I won't store that — it looks like sensitive information, or it was empty.")
        return True
    speak("Got it. I'll remember that.")
    return True


def handle_forget_command(query: str) -> bool:
    """'forget this ...' — finds candidates and deletes the best match if unambiguous."""
    text = query
    for prefix in ("forget this", "forget that", "forget about", "forget"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip(" :,-")
            break
    if not text:
        speak("What should I forget? Give me a short phrase to match.")
        return True
    candidates = memory_store.delete_by_content_match(text, limit=5)
    # Prefer long-term / profile / preference over conversation noise
    preferred = [
        c
        for c in candidates
        if c.category in (
            CATEGORY_LONG_TERM,
            CATEGORY_USER_PROFILE,
            CATEGORY_PREFERENCE,
            CATEGORY_GOAL,
            CATEGORY_PROJECT,
        )
    ]
    pool = preferred or candidates
    if not pool:
        speak("I couldn't find anything matching that.")
        return True
    if len(pool) > 1:
        # Ambiguous — ask for confirmation by speaking the top match only if unique enough
        # For voice UX we delete only when a single clear match; otherwise report ambiguity.
        speak(
            f"I found {len(pool)} related memories. Be more specific, or say the exact phrase again."
        )
        for c in pool[:3]:
            log_and_print(f"Forget candidate: [{c.category}] {c.content[:80]}")
        return True
    target = pool[0]
    memory_store.delete(target.id)
    speak(f"Okay, I forgot: {target.content[:80]}")
    return True


def handle_what_do_you_remember(query: str) -> bool:
    """'what do you remember about me/this project'."""
    q = query.lower()
    if "project" in q:
        # Extract a rough project name after "about"
        about = q
        for marker in ("about this project", "about the project", "about project", "about"):
            if marker in about:
                about = about.split(marker, 1)[-1].strip()
                break
        results = memory_store.list_by_category(CATEGORY_PROJECT, limit=8)
        if about:
            results = memory_store.search(about, category=CATEGORY_PROJECT, limit=8) or results
        if not results:
            speak("I don't have any project memories stored yet.")
            return True
        speak(f"I have {len(results)} project-related memories.")
        for r in results[:5]:
            speak(r.content[:120])
        return True

    # about me / general
    profile = memory_store.list_by_category(CATEGORY_USER_PROFILE, limit=5)
    prefs = memory_store.list_by_category(CATEGORY_PREFERENCE, limit=5)
    goals = memory_store.list_by_category(CATEGORY_GOAL, limit=5)
    long_term = memory_store.list_by_category(CATEGORY_LONG_TERM, limit=8)
    combined = profile + prefs + goals + long_term
    if not combined:
        speak("I don't have permanent memories about you yet. Say 'remember this' to teach me.")
        return True
    speak(f"Here's what I remember about you. I have {len(combined)} permanent notes.")
    for r in combined[:6]:
        speak(r.content[:120])
    return True


def parse_emotion_reply(raw_text):
    """মডেলের রিপ্লাই থেকে [idle]/[happy]/[angry] ট্যাগ আলাদা করে (mood, clean_text) রিটার্ন করে।"""
    match = re.match(r"^\s*\[(idle|happy|angry)\]\s*(.*)$", raw_text.strip(), re.IGNORECASE | re.DOTALL)
    if match:
        mood = match.group(1).lower()
        clean_text = match.group(2).strip()
        return mood, (clean_text or raw_text.strip())
    return "idle", raw_text.strip()


# ================= CODE GENERATION =================
def generate_code(prompt):
    try:
        full_prompt = f"Write only the clean Python code for: {prompt}. No comments, no explanations, just code."
        response = model.generate_content(full_prompt)
        code = response.text.replace("```python", "").replace("```", "").strip()

        out_path = os.path.join(BASE_DIR, "generated_code.py")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(code)

        log_and_print(f"--- Generated Code Saved to generated_code.py ---\n{code}")
        speak("Done! I saved the code for you.")
        return code
    except Exception as e:
        log_and_print(f"Code Gen Error: {e}", "error")
        speak("I encountered an error generating the code.")
        return ""


# ================= ANALYZE SCREEN =================
def analyze_screen():
    speak("Analyzing your screen, please wait a moment.")
    filename = os.path.join(BASE_DIR, "sct.png")
    try:
        with mss.mss() as sct:
            sct.shot(output=filename)

        img = Image.open(filename)
        try:
            response = model.generate_content(
                ["You are Jarvis. Look at this screenshot and explain what is happening in 2 sentences.", img]
            )
            description = response.text.replace("*", "").strip()
            speak(description)
        finally:
            img.close()
    except Exception as e:
        log_and_print(f"Screen Analysis Error: {e}", "error")
        speak("I encountered an error reading your screen.")
    finally:
        if os.path.exists(filename):
            os.remove(filename)


# ================= TYPE TEXT =================
def type_text(prompt):
    speak("Generating text and preparing to type. You have 3 seconds to click on the text field.")
    try:
        full_prompt = f"Write a professional and concise response for: {prompt}. Provide only the text content."
        response = model.generate_content(full_prompt)
        text_to_type = response.text.replace("*", "").strip()
        time.sleep(3)
        keyboard.write(text_to_type)
        speak("All typed out for you!")
    except Exception as e:
        log_and_print(f"Typing Error: {e}", "error")
        speak("I encountered an error while trying to type.")


# ================= REMINDERS =================
def set_reminder(query):
    """'remind me to <task> in <n> minutes/seconds/hours'"""
    try:
        if " in " not in query:
            speak("Please say the reminder like: remind me to drink water in 10 minutes.")
            return
        task_part, time_part = query.rsplit(" in ", 1)
        task = task_part.replace("remind me to", "").strip()
        time_part = time_part.strip()

        parts = time_part.split()
        amount = int(parts[0])
        unit = parts[1] if len(parts) > 1 else "minutes"

        if "sec" in unit:
            seconds = amount
        elif "hour" in unit:
            seconds = amount * 3600
        else:
            seconds = amount * 60

        speak(f"Okay, I will remind you to {task} in {amount} {unit}.")

        def fire():
            speak(f"Reminder: {task}")

        threading.Timer(seconds, fire).start()
    except Exception as e:
        log_and_print(f"Reminder Error: {e}", "error")
        speak("I couldn't set that reminder. Please try again with a format like: remind me to X in 10 minutes.")


# ================= NOTES / TODO =================
def load_notes():
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_and_print(f"Notes load error: {e}", "error")
    return []


def save_notes(notes):
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(notes, f, indent=2)
    except Exception as e:
        log_and_print(f"Notes save error: {e}", "error")


def add_note(query):
    note_text = query.replace("add note", "").replace("add a note", "").strip()
    if not note_text:
        speak("What should the note say?")
        note_text = take_command()
        if note_text == "none":
            speak("I didn't catch that.")
            return
    notes = load_notes()
    notes.append({"text": note_text, "time": datetime.now().isoformat()})
    save_notes(notes)
    speak("Note saved.")


def list_notes():
    notes = load_notes()
    if not notes:
        speak("You have no saved notes.")
        return
    speak(f"You have {len(notes)} notes.")
    for n in notes[-5:]:
        speak(n["text"])


def clear_notes():
    save_notes([])
    speak("All notes cleared.")


# ================= WEATHER =================
def get_weather(query):
    city = re.sub(r"\bweather\b", "", query)
    city = re.sub(r"^\s*\bin\b\s*", "", city.strip())
    city = city.strip() or config.get("default_city", "")
    try:
        url = f"https://wttr.in/{city}?format=%C+%t"
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        speak(f"Weather {(' in ' + city) if city else ''}: {resp.text.strip()}")
    except Exception as e:
        log_and_print(f"Weather Error: {e}", "error")
        speak("I couldn't fetch the weather right now.")


# ================= SYSTEM INFO =================
def system_info():
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        speak(f"CPU usage is {cpu} percent, and RAM usage is {ram} percent.")
    except Exception as e:
        log_and_print(f"System Info Error: {e}", "error")
        speak("I couldn't read system information.")


# ================= FILE SEARCH =================
def find_file(query):
    filename = query.replace("find file", "").strip()
    if not filename:
        speak("Which file should I search for?")
        return
    speak(f"Searching for {filename}. This may take a moment.")
    search_root = os.path.expanduser("~")
    matches = []
    try:
        for root, _, files in os.walk(search_root):
            for f in files:
                if filename.lower() in f.lower():
                    matches.append(os.path.join(root, f))
                    if len(matches) >= 5:
                        break
            if len(matches) >= 5:
                break
        if matches:
            speak(f"I found {len(matches)} matching files.")
            for m in matches:
                print(m)
        else:
            speak("No matching files found.")
    except Exception as e:
        log_and_print(f"File Search Error: {e}", "error")
        speak("I encountered an error while searching for files.")


# ================= WHATSAPP =================
def send_whatsapp(query):
    """'send whatsapp to +8801XXXXXXXXX saying hello there'"""
    try:
        if "saying" not in query:
            speak("Please say it like: send whatsapp to the number saying your message.")
            return
        target_part, message = query.split("saying", 1)
        phone = target_part.replace("send whatsapp to", "").replace("send whatsapp", "").strip()
        phone = phone.replace(" ", "")
        message = message.strip()
        if not phone.startswith("+"):
            speak("Please include the country code, for example plus 91.")
            return
        pywhatkit.sendwhatmsg_instantly(phone, message, wait_time=15, tab_close=True)
        speak("WhatsApp message sent.")
    except Exception as e:
        log_and_print(f"WhatsApp Error: {e}", "error")
        speak("I couldn't send the WhatsApp message.")


# ================= EMAIL =================
def check_email():
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        speak("Email is not configured. Please set JARVIS_EMAIL_ADDRESS and JARVIS_EMAIL_APP_PASSWORD.")
        return
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST) as mail:
            mail.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            mail.select("inbox")
            status, data = mail.search(None, "UNSEEN")
            unread_ids = data[0].split() if status == "OK" else []
            speak(f"You have {len(unread_ids)} unread emails.")
            for eid in unread_ids[:3]:
                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK":
                    continue
                msg = email_lib.message_from_bytes(msg_data[0][1])
                subject = msg.get("Subject", "No subject")
                sender = msg.get("From", "Unknown sender")
                speak(f"From {sender}, subject: {subject}")
    except Exception as e:
        log_and_print(f"Email Check Error: {e}", "error")
        speak("I couldn't check your email right now.")


def send_email(query):
    """'send email to someone@example.com saying hello there'"""
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        speak("Email is not configured. Please set JARVIS_EMAIL_ADDRESS and JARVIS_EMAIL_APP_PASSWORD.")
        return
    try:
        if "saying" not in query:
            speak("Please say it like: send email to address saying your message.")
            return
        target_part, body = query.split("saying", 1)
        to_addr = target_part.replace("send email to", "").replace("send email", "").strip()
        body = body.strip()

        msg = f"Subject: Message from Jarvis\n\n{body}"
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to_addr, msg)
        speak("Email sent.")
    except Exception as e:
        log_and_print(f"Send Email Error: {e}", "error")
        speak("I couldn't send that email.")


# ================= CALCULATOR =================
def calculate(query):
    expr = query.replace("calculate", "").strip()
    # word replacements
    replacements = {
        "plus": "+", "minus": "-", "times": "*", "multiplied by": "*",
        "divided by": "/", "x": "*", "into": "*",
    }
    for word, sym in replacements.items():
        expr = expr.replace(word, sym)

    # শুধু নিরাপদ ক্যারেক্টার (সংখ্যা, অপারেটর, বন্ধনী, দশমিক) থাকতে দেওয়া হচ্ছে
    if not re.fullmatch(r"[0-9\.\+\-\*/\(\)\s%]+", expr):
        speak("I can only do plain math with numbers, sorry.")
        return
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        speak(f"That's {result}")
    except Exception as e:
        log_and_print(f"Calculator Error: {e}", "error")
        speak("Hmm, I couldn't calculate that.")


# ================= UNIT / CURRENCY CONVERTER =================
UNIT_TABLE = {
    ("km", "miles"): 0.621371, ("miles", "km"): 1.60934,
    ("kg", "lbs"): 2.20462, ("lbs", "kg"): 0.453592,
    ("celsius", "fahrenheit"): lambda c: c * 9 / 5 + 32,
    ("fahrenheit", "celsius"): lambda f: (f - 32) * 5 / 9,
    ("m", "feet"): 3.28084, ("feet", "m"): 0.3048,
}


def convert_units(query):
    match = re.search(r"convert\s+([\d\.]+)\s*([a-zA-Z]+)\s+to\s+([a-zA-Z]+)", query)
    if not match:
        speak("Please say it like: convert 10 km to miles.")
        return
    amount, from_unit, to_unit = float(match.group(1)), match.group(2).lower(), match.group(3).lower()

    # কারেন্সি মনে হলে exchange rate API ব্যবহার হবে
    currency_like = {"usd", "bdt", "eur", "gbp", "inr", "jpy", "cad", "aud"}
    if from_unit in currency_like and to_unit in currency_like:
        try:
            resp = requests.get(f"https://open.er-api.com/v6/latest/{from_unit.upper()}", timeout=8)
            resp.raise_for_status()
            data = resp.json()
            rate = data["rates"][to_unit.upper()]
            speak(f"{amount} {from_unit.upper()} is about {round(amount * rate, 2)} {to_unit.upper()}")
        except Exception as e:
            log_and_print(f"Currency Convert Error: {e}", "error")
            speak("I couldn't fetch the currency rate right now.")
        return

    key = (from_unit, to_unit)
    if key in UNIT_TABLE:
        factor = UNIT_TABLE[key]
        result = factor(amount) if callable(factor) else amount * factor
        speak(f"{amount} {from_unit} is about {round(result, 2)} {to_unit}")
    else:
        speak(f"I don't know how to convert {from_unit} to {to_unit} yet.")


# ================= TIMER / STOPWATCH =================
stopwatch_start = {"time": None}


def set_timer(query):
    match = re.search(r"(\d+)\s*(second|minute|hour)", query)
    if not match:
        speak("Please say it like: set a timer for 5 minutes.")
        return
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount * (3600 if "hour" in unit else 60 if "minute" in unit else 1)
    speak(f"Timer set for {amount} {unit}s.")

    def fire():
        speak("Time's up!")

    threading.Timer(seconds, fire).start()


def stopwatch_control(query):
    if "start" in query:
        stopwatch_start["time"] = time.time()
        speak("Stopwatch started.")
    elif "stop" in query or "check" in query:
        if stopwatch_start["time"] is None:
            speak("Stopwatch isn't running.")
            return
        elapsed = time.time() - stopwatch_start["time"]
        speak(f"Elapsed time is {round(elapsed, 1)} seconds.")
        if "stop" in query:
            stopwatch_start["time"] = None
    else:
        speak("Say stopwatch start, stopwatch check, or stopwatch stop.")


# ================= MUSIC / MEDIA CONTROL =================
def media_control(query):
    try:
        if "next" in query:
            keyboard.send("next track")
            speak("Skipping.")
        elif "previous" in query or "back" in query:
            keyboard.send("previous track")
            speak("Going back a track.")
        elif "pause" in query or "play music" in query or "resume music" in query:
            keyboard.send("play/pause media")
            speak("Toggled playback.")
        else:
            speak("Say next track, previous track, or pause music.")
    except Exception as e:
        log_and_print(f"Media Control Error: {e}", "error")
        speak("I couldn't control the media player.")


# ================= NEWS HEADLINES =================
def get_news():
    try:
        resp = requests.get("https://feeds.bbci.co.uk/news/rss.xml", timeout=8)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        titles = [item.find("title").text for item in root.findall(".//item")[:5]]
        speak("Here are the top headlines.")
        for t in titles:
            speak(t)
    except Exception as e:
        log_and_print(f"News Error: {e}", "error")
        speak("I couldn't fetch the news right now.")


# ================= JOKE =================
def tell_joke():
    try:
        resp = requests.get(
            "https://icanhazdadjoke.com/",
            headers={"Accept": "application/json"},
            timeout=8,
        )
        resp.raise_for_status()
        joke = resp.json().get("joke", "I couldn't think of one, oddly enough.")
        speak(joke)
    except Exception as e:
        log_and_print(f"Joke Error: {e}", "error")
        speak("My joke book is missing right now, sorry!")


# ================= SCREENSHOT (plain capture) =================
def take_screenshot():
    try:
        folder = os.path.join(BASE_DIR, "screenshots")
        os.makedirs(folder, exist_ok=True)
        filename = os.path.join(folder, f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        with mss.mss() as sct:
            sct.shot(output=filename)
        speak("Screenshot saved.")
    except Exception as e:
        log_and_print(f"Screenshot Error: {e}", "error")
        speak("I couldn't take a screenshot.")


# ================= CLIPBOARD =================
def clipboard_control(query):
    try:
        if "read" in query or "what did i copy" in query or "paste" in query:
            content = pyperclip.paste()
            if content:
                speak(f"Your clipboard has: {content[:200]}")
            else:
                speak("Your clipboard is empty.")
        elif "copy" in query:
            text = query.replace("copy", "").strip()
            if not text:
                speak("What should I copy?")
                return
            pyperclip.copy(text)
            speak("Copied to clipboard.")
        else:
            speak("Say read clipboard, or copy followed by some text.")
    except Exception as e:
        log_and_print(f"Clipboard Error: {e}", "error")
        speak("I couldn't access the clipboard.")


# ================= SYSTEM POWER CONTROL =================
def power_control(query):
    system = platform.system()
    try:
        if "shutdown" in query:
            speak("Say confirm shutdown within 10 seconds if you really mean it.")
            confirm = take_command()
            if "confirm" not in confirm:
                speak("Okay, cancelled.")
                return
            speak("Shutting down. Bye for now!")
            if system == "Windows":
                os.system("shutdown /s /t 5")
            else:
                os.system("shutdown -h now")
        elif "restart" in query:
            speak("Say confirm restart within 10 seconds if you really mean it.")
            confirm = take_command()
            if "confirm" not in confirm:
                speak("Okay, cancelled.")
                return
            speak("Restarting now.")
            if system == "Windows":
                os.system("shutdown /r /t 5")
            else:
                os.system("shutdown -r now")
        elif "sleep" in query:
            speak("Putting the system to sleep.")
            if system == "Windows":
                os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            elif system == "Darwin":
                os.system("pmset sleepnow")
            else:
                os.system("systemctl suspend")
    except Exception as e:
        log_and_print(f"Power Control Error: {e}", "error")
        speak("I couldn't do that power action.")


# ================= WIFI / BLUETOOTH TOGGLE (Windows only, best-effort) =================
def connectivity_toggle(query):
    if platform.system() != "Windows":
        speak("Wifi and Bluetooth toggling is only supported on Windows in this build, sorry.")
        return
    try:
        if "wifi" in query:
            state = "enable" if "on" in query else "disable"
            os.system(f'netsh interface set interface "Wi-Fi" admin={state}')
            speak(f"Wifi turned {state}d.")
        elif "bluetooth" in query:
            speak("Bluetooth toggling needs a helper app on Windows — I can't do it directly yet.")
    except Exception as e:
        log_and_print(f"Connectivity Toggle Error: {e}", "error")
        speak("I couldn't change that connectivity setting.")


# ================= TRANSLATION =================
def translate_text(query):
    match = re.search(r"translate (.+) to (\w+)", query)
    if not match:
        speak("Say it like: translate hello to bengali.")
        return
    text, target_lang = match.group(1).strip(), match.group(2).strip()
    try:
        prompt = f"Translate this to {target_lang}, reply with only the translation: {text}"
        response = model.generate_content(prompt)
        speak(response.text.strip())
    except Exception as e:
        log_and_print(f"Translation Error: {e}", "error")
        speak("I couldn't translate that.")


# ================= SUMMARIZATION =================
def summarize_text(query):
    text = query.replace("summarize", "").strip()
    if not text:
        speak("What should I summarize?")
        return
    try:
        prompt = f"Summarize this in 2-3 short sentences: {text}"
        response = model.generate_content(prompt)
        speak(response.text.strip())
    except Exception as e:
        log_and_print(f"Summarize Error: {e}", "error")
        speak("I couldn't summarize that.")


# ================= PERSONALITY / MOOD TOGGLE =================
def set_personality(query):
    if "chill" in query or "calm" in query or "serious" in query:
        config["personality_level"] = "low"
        save_config(config, BASE_DIR)
        speak("Alright, dialing down the drama. I'll keep it chill.")
    elif "sassy" in query or "dramatic" in query or "playful" in query:
        config["personality_level"] = "high"
        save_config(config, BASE_DIR)
        speak("Ooh, bringing the sass back! Watch out.")
    else:
        speak("Say be more chill, or be more sassy.")


# ================= AUTOMATION =================
def automation(query):
    try:
        if "open" in query:
            app = query.replace("open", "").strip()
            speak(f"Opening {app}")
            try:
                app_open(app, match_closest=True, throw_error=True)
            except Exception:
                speak(f"{app} not found on your system. Searching on web.")
                pywhatkit.search(app)

        elif "close" in query:
            app = query.replace("close", "").strip()
            try:
                app_close(app, match_closest=True)
                speak(f"Closing {app}")
            except Exception as e:
                log_and_print(f"Close App Error: {e}", "error")
                speak(f"I couldn't close {app}.")

        elif "play" in query:
            song = query.replace("play", "").strip()
            speak(f"Playing {song} on YouTube")
            pywhatkit.playonyt(song)

        elif any(word in query for word in ["pause", "stop", "resume"]):
            keyboard.press_and_release("space")
            speak("Got it!")

        elif "full screen" in query:
            keyboard.press_and_release("f")

        elif "mute" in query:
            keyboard.press_and_release("m")

        elif "battery" in query:
            battery = psutil.sensors_battery()
            if battery:
                speak(f"System is at {battery.percent} percent.")
            else:
                speak("I couldn't read the battery status on this device.")

        elif "brightness" in query:
            current = sbc.get_brightness()[0]
            if "up" in query:
                new = min(100, current + 20)
            elif "down" in query:
                new = max(0, current - 20)
            else:
                speak("Please say brightness up or brightness down.")
                return
            sbc.set_brightness(new)
            speak(f"Brightness set to {new} percent")

        elif "volume" in query:
            if "up" in query:
                pyautogui.press("volumeup", presses=5)
            elif "down" in query:
                pyautogui.press("volumedown", presses=5)
            else:
                speak("Please say volume up or volume down.")
                return
            speak("Volume adjusted")

    except Exception as e:
        log_and_print(f"Automation Error: {e}", "error")
        speak("I encountered an error performing that action.")


# ================= COMMAND HANDLER =================
def handle_command(query):
    emit_command(query)
    mood = detect_mood(query)
    if mood != "idle":
        emit_mood(mood)
    try:
        # Phase F: natural-language resource commands (find/download/locate/verify/list)
        if resource_handler is not None:
            try:
                if resource_handler.handle(query):
                    return
            except Exception as _res_exc:
                log_and_print(f"Resource command error: {_res_exc}", "error")
                speak(f"Resource command failed: {_res_exc}")
                return

        if "get angry" in query or "be angry" in query:
            emit_mood("angry")
            speak("Fine. FINE. You want angry? You've got angry.")

        elif "be happy" in query or "cheer up" in query:
            emit_mood("happy")
            speak("Yay, happy mode! Much better.")

        elif "calm down" in query or "be normal" in query:
            emit_mood("idle")
            speak("Okay, back to normal.")

        elif "write code" in query:
            generate_code(query.replace("write code", "").strip())

        elif "type" in query:
            type_text(query.replace("type", "").strip())

        elif "what is on my screen" in query:
            analyze_screen()

        elif "remind me" in query:
            set_reminder(query)

        elif "add note" in query:
            add_note(query)

        elif "show notes" in query or "list notes" in query or "my notes" in query:
            list_notes()

        elif "clear notes" in query:
            clear_notes()

        elif "weather" in query:
            get_weather(query)

        elif "system info" in query or "cpu usage" in query or "ram usage" in query:
            system_info()

        elif "find file" in query:
            find_file(query)

        elif "send whatsapp" in query:
            send_whatsapp(query)

        elif "check email" in query or "unread email" in query:
            check_email()

        elif "send email" in query:
            send_email(query)

        elif "calculate" in query:
            calculate(query)

        elif "convert" in query:
            convert_units(query)

        elif "timer" in query:
            set_timer(query)

        elif "stopwatch" in query:
            stopwatch_control(query)

        elif "next track" in query or "previous track" in query or "pause music" in query or "play music" in query or "resume music" in query:
            media_control(query)

        elif "news" in query or "headlines" in query:
            get_news()

        elif "joke" in query:
            tell_joke()

        elif "take screenshot" in query or "screenshot" in query and "what is on my screen" not in query:
            take_screenshot()

        elif "clipboard" in query or query.startswith("copy "):
            clipboard_control(query)

        elif "shutdown" in query or "restart" in query or "power off" in query:
            power_control(query)

        elif "wifi" in query or "bluetooth" in query:
            connectivity_toggle(query)

        elif query.startswith("translate"):
            translate_text(query)

        elif query.startswith("summarize"):
            summarize_text(query)

        elif "be more chill" in query or "be more sassy" in query or "be more calm" in query or "be more dramatic" in query:
            set_personality(query)

        elif any(word in query for word in ["open", "close", "play", "battery", "brightness", "lock", "volume", "pause", "resume", "mute"]):
            automation(query)

        elif "google search" in query:
            search_query = query.replace("google search", "").strip()
            speak(f"Searching Google for {search_query}")
            pywhatkit.search(search_query)

        elif "my name is" in query:
            name = query.replace("my name is", "").strip().title()
            config["user_name"] = name
            save_config(config, BASE_DIR)
            # Also store as a user_profile memory
            memory_store.save(
                content=f"User's name is {name}",
                category=CATEGORY_USER_PROFILE,
                tags=["name"],
                importance=0.9,
                source="user",
            )
            speak(f"Nice to meet you, {name}. I'll remember that.")

        elif query.startswith("remember this") or query.startswith("remember that") or (
            query.startswith("remember ") and "what do you remember" not in query
        ):
            handle_remember_command(query)

        elif query.startswith("forget this") or query.startswith("forget that") or query.startswith(
            "forget about"
        ) or (query.startswith("forget ") and "password" not in query):
            handle_forget_command(query)

        elif "what do you remember" in query or "what do you know about me" in query:
            handle_what_do_you_remember(query)

        elif "list skills" in query or "show skills" in query or "active skills" in query:
            active = skill_registry.list_active(limit=10)
            if not active:
                speak("I have no active skills yet.")
            else:
                speak(f"I have {len(active)} active skills.")
                for s in active[:5]:
                    speak(f"{s.name}, version {s.version}")

        elif query.startswith("find skill") or query.startswith("search skill"):
            q = query.replace("find skill", "").replace("search skill", "").strip()
            hits = skill_registry.find_relevant_active(q, limit=5) if q else skill_registry.list_active(limit=5)
            if not hits:
                # also search non-active for reporting
                hits = skill_registry.search(query=q, limit=5) if q else []
            if not hits:
                speak("No matching skills found.")
            else:
                speak(f"Found {len(hits)} skills.")
                for s in hits[:3]:
                    speak(f"{s.name} is {s.status}, version {s.version}")

        elif "skill status" in query:
            parts = query.replace("skill status", "").strip()
            if not parts:
                speak("Say skill status followed by the skill name.")
            else:
                matches = skill_registry.list_by_name(parts)
                if not matches:
                    matches = skill_registry.search(query=parts, limit=3)
                if not matches:
                    speak("I don't know that skill.")
                else:
                    s = matches[0]
                    speak(
                        f"{s.name} version {s.version} is {s.status}, "
                        f"used {s.usage_count} times, confidence {round(s.confidence, 2)}"
                    )

        elif query.startswith("orchestrate:") or query.startswith("orchestrate "):
            if orchestrator is None:
                speak("Orchestrator is not available right now.")
            else:
                objective = query.split(":", 1)[-1].strip() if ":" in query else query.replace("orchestrate", "", 1).strip()
                if not objective:
                    speak("Say orchestrate followed by the task.")
                else:
                    speak(f"Orchestrating: {objective}")
                    result = orchestrator.run(objective, simple=True, record_experience=True)
                    speak(
                        f"Orchestration {result.status}. "
                        f"{result.final_output.get('completed', 0)} tasks completed, "
                        f"{result.final_output.get('failed', 0)} failed."
                    )
                    log_and_print(f"Orchestration run {result.run_id}: {result.status}")

        elif query.startswith("task status"):
            if orchestrator is None:
                speak("Orchestrator is not available.")
            else:
                rid = query.replace("task status", "").strip()
                run = orchestrator.get_run(rid) if rid else None
                if not run and orchestrator._runs:
                    run = list(orchestrator._runs.values())[-1]
                if not run:
                    speak("No orchestration run found.")
                else:
                    speak(f"Run {run.run_id[:8]} is {run.status} with {len(run.tasks)} tasks.")

        elif query.startswith("task cancel"):
            if orchestrator is None:
                speak("Orchestrator is not available.")
            else:
                rid = query.replace("task cancel", "").strip()
                if not rid and orchestrator._runs:
                    rid = list(orchestrator._runs.keys())[-1]
                ok = orchestrator.cancel_run(rid) if rid else False
                speak("Cancelled." if ok else "Could not cancel that run.")

        else:
            remember("user", query)
            prompt = build_context_prompt(query)
            response = model.generate_content(prompt)
            raw_text = response.text.replace("*", "").strip()
            reply_mood, clean_text = parse_emotion_reply(raw_text)
            emit_mood(reply_mood)
            remember("jarvis", clean_text)
            speak(clean_text)

    except Exception as e:
        log_and_print(f"Command Handler Error: {e}", "error")
        speak("Aw, I couldn't quite process that one, sorry!")


# ================= WAKE WORD & MAIN =================
def process_typed_command(text):
    """টাইপ করা কমান্ড প্রসেস করে — wake word লাগবে না, সরাসরি হ্যান্ডেল হবে।"""
    command = text.strip().lower()
    if not command:
        return
    emit_status(f"Typed: {text.strip()}")
    if "go to sleep" in command or command == "exit" or "exit jarvis" in command:
        speak("Fine, leaving already? Don't miss me too much. Bye!")
        os._exit(0)
    handle_command(command)


def wake_word_listener():
    assistant_name = config.get("assistant_name", "Jarvis")
    user_name = config.get("user_name", "Sir")

    if not check_microphone_available():
        log_and_print("No microphone detected — switching to keyboard input mode.", "error")
        emit_status("No microphone found — type your command below")
        emit_keyboard_mode(True)
        speak(
            f"{assistant_name} in the house, {user_name}. I couldn't find a microphone, "
            f"so type your commands into the box below instead."
        )
        return  # ভয়েস লুপ চালানোর দরকার নেই, UI থেকে টাইপ করা কমান্ড হ্যান্ডেল হবে

    speak(f"{assistant_name} in the house! Miss me, {user_name}?")
    aliases = config.get("wake_word_aliases") or [config.get("wake_word", "jarvis")]

    # একবার wake word বললে conversation_mode চালু হয়ে যাবে, বার বার wake word বলা লাগবে না
    conversation_mode = False
    silence_count = 0
    MAX_SILENCE = 3  # পরপর ৩ বার কিছু না শুনলে conversation mode বন্ধ হয়ে যাবে

    while True:
        query = take_command()

        if query == "none":
            if conversation_mode:
                silence_count += 1
                if silence_count >= MAX_SILENCE:
                    conversation_mode = False
                    silence_count = 0
                    emit_status("Idle (say the wake word to talk again)")
            continue

        silence_count = 0

        if conversation_mode:
            command = query
        else:
            matched_alias = next((a for a in aliases if a in query), None)
            if not matched_alias:
                continue
            command = query.replace(matched_alias, "").strip()
            conversation_mode = True  # wake word শোনা গেছে, এখন থেকে continuous listening

        if "go to sleep" in command or "exit" in command:
            speak("Fine, leaving already? Don't miss me too much. Bye!")
            os._exit(0)

        if "that's all" in command or "sleep now" in command or "stop listening" in command:
            conversation_mode = False
            speak("Okay, call my name again when you need me.")
            continue

        if not command:
            speak("Yeah yeah, I'm listening, go on.")
            continue

        handle_command(command)



# Dummy Qt bases when PyQt6 is unavailable so class definitions import cleanly.
if QWidget is None:
    class QWidget:  # type: ignore
        pass
if QObject is None:
    class QObject:  # type: ignore
        pass
if pyqtSignal is None:
    def pyqtSignal(*_a, **_k):  # type: ignore
        return None
if QColor is None:
    class QColor:  # type: ignore
        def __init__(self, *a, **k):
            pass
        def red(self):
            return 0
        def green(self):
            return 0
        def blue(self):
            return 0
if QTimer is None:
    class QTimer:  # type: ignore
        def __init__(self, *a, **k):
            pass
        def start(self, *a, **k):
            pass
        def timeout(self):
            return type("Sig", (), {"connect": lambda *a, **k: None})()
if QPainter is None:
    class QPainter:  # type: ignore
        pass
if QPen is None:
    class QPen:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QBrush is None:
    class QBrush:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QFont is None:
    class QFont:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QPixmap is None:
    class QPixmap:  # type: ignore
        def __init__(self, *a, **k):
            pass
        def fill(self, *a, **k):
            pass
if Qt is None:
    class Qt:  # type: ignore
        AlignCenter = 0
        FramelessWindowHint = 0
        WindowStaysOnTopHint = 0
        WA_TranslucentBackground = 0
        LeftButton = 1
if QLabel is None:
    class QLabel:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QLineEdit is None:
    class QLineEdit:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QPushButton is None:
    class QPushButton:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QSystemTrayIcon is None:
    class QSystemTrayIcon:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QMenu is None:
    class QMenu:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QAction is None:
    class QAction:  # type: ignore
        def __init__(self, *a, **k):
            pass
if QIcon is None:
    class QIcon:  # type: ignore
        def __init__(self, *a, **k):
            pass

# ================= HUD COLOR PALETTE =================
if QColor is not None:
    HUD_BLUE = QColor("#3ad6ff")
    HUD_BLUE_DIM = QColor("#0d3a52")
    HUD_GOLD = QColor("#ffb400")
    HUD_RED = QColor("#ff3b3b")
    HUD_BG = QColor("#020608")
else:
    HUD_BLUE = HUD_BLUE_DIM = HUD_GOLD = HUD_RED = HUD_BG = None


def mood_color(mood):
    if mood == "angry":
        return HUD_RED
    if mood == "happy":
        return HUD_GOLD
    return HUD_BLUE


# ================= ARC REACTOR HUD (live animation) =================
class MoodAvatar(QWidget):
    """Iron-Man style HUD: pulsing arc-reactor core, counter-rotating segmented
    rings, and a radar sweep, all re-colored to the current mood."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mood = "idle"
        self._tick = 0
        self.setFixedSize(220, 220)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(30)

        self._revert_timer = None

    def set_mood(self, mood):
        self.mood = mood
        if self._revert_timer:
            self._revert_timer.stop()
        # angry/happy states settle back to idle after a few seconds
        if mood in ("angry", "happy"):
            self._revert_timer = QTimer(self)
            self._revert_timer.setSingleShot(True)
            self._revert_timer.timeout.connect(lambda: self.set_mood("idle"))
            self._revert_timer.start(5000)

    def _animate(self):
        self._tick += 1
        self.update()

    def _draw_tick_ring(self, painter, cx, cy, radius, count, length, angle_offset, color, width=2):
        painter.setPen(QPen(color, width))
        for i in range(count):
            a = math.radians((360 / count) * i + angle_offset)
            x1 = cx + radius * math.cos(a)
            y1 = cy + radius * math.sin(a)
            x2 = cx + (radius - length) * math.cos(a)
            y2 = cy + (radius - length) * math.sin(a)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        color = mood_color(self.mood)

        # pulse amount differs a little by mood so the core "breathes"
        if self.mood == "angry":
            pulse = 5 * math.sin(self._tick * 0.5)
            outer_speed, mid_speed = 3.2, -5.0
        elif self.mood == "happy":
            pulse = 4 * abs(math.sin(self._tick * 0.15))
            outer_speed, mid_speed = 1.6, -2.4
        else:
            pulse = 3 * math.sin(self._tick * 0.06)
            outer_speed, mid_speed = 0.6, -1.0

        # outer segmented ring (slow rotation, tick marks)
        outer_r = 100 + pulse * 0.3
        self._draw_tick_ring(painter, cx, cy, outer_r, 36, 6, self._tick * outer_speed, color, 2)
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(int(cx - outer_r), int(cy - outer_r), int(outer_r * 2), int(outer_r * 2))

        # middle dashed ring, counter-rotating, drawn as short arcs
        mid_r = 76
        painter.setPen(QPen(color, 3))
        for i in range(8):
            start_angle = int((self._tick * mid_speed + i * 45) * 16)
            painter.drawArc(int(cx - mid_r), int(cy - mid_r), int(mid_r * 2), int(mid_r * 2), start_angle, 12 * 16)

        # radar sweep line with fading trail
        sweep_angle = math.radians((self._tick * 4) % 360)
        sweep_color = QColor(color)
        for trail in range(6):
            a = sweep_angle - trail * 0.12
            alpha = max(0, 160 - trail * 28)
            sweep_color.setAlpha(alpha)
            painter.setPen(QPen(sweep_color, 2))
            x2 = cx + mid_r * math.cos(a)
            y2 = cy + mid_r * math.sin(a)
            painter.drawLine(cx, cy, int(x2), int(y2))

        # inner core (arc reactor)
        core_r = 34 + pulse
        glow = QColor(color)
        glow.setAlpha(60)
        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - core_r - 8), int(cy - core_r - 8), int((core_r + 8) * 2), int((core_r + 8) * 2))

        painter.setBrush(QBrush(HUD_BG))
        painter.setPen(QPen(color, 3))
        painter.drawEllipse(int(cx - core_r), int(cy - core_r), int(core_r * 2), int(core_r * 2))

        # triangular core detail, like the arc reactor centerpiece
        painter.setPen(QPen(color, 2))
        painter.setBrush(QBrush(color))
        tri_r = core_r * 0.55
        pts = []
        for i in range(3):
            a = math.radians(self._tick * outer_speed * 2 + i * 120)
            pts.append((cx + tri_r * math.cos(a), cy + tri_r * math.sin(a)))
        for i in range(3):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % 3]
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # small readout ticks around the very outer edge
        self._draw_tick_ring(painter, cx, cy, outer_r + 14, 60, 4, -self._tick * 0.4, QColor(color.red(), color.green(), color.blue(), 90), 1)


# ================= HUD FRAME (corner brackets + scanlines) =================
class HUDFrame(QWidget):
    """Decorative overlay: corner brackets and faint horizontal scanlines,
    drawn on top of everything else, re-colored to the current mood."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mood = "idle"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_mood(self, mood):
        self.mood = mood
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        color = mood_color(self.mood)

        # corner brackets
        L = 26
        painter.setPen(QPen(color, 3))
        corners = [(0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)]
        for x, y, dx, dy in corners:
            painter.drawLine(x, y, x + dx * L, y)
            painter.drawLine(x, y, x, y + dy * L)

        # faint scanlines
        scan_color = QColor(color)
        scan_color.setAlpha(14)
        painter.setPen(QPen(scan_color, 1))
        for y in range(0, h, 4):
            painter.drawLine(0, y, w, y)


# ================= UI =================
class JarvisUI(QWidget):
    def __init__(self):
        super().__init__()
        assistant_name = config.get("assistant_name", "Jarvis").upper()
        self.setWindowTitle(assistant_name)
        self.setFixedSize(460, 540)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(
            """
            background-color: #020608;
            color: #3ad6ff;
            border: 1px solid #3ad6ff;
            font-family: 'Consolas', 'Segoe UI', monospace;
            """
        )

        self.title_label = QLabel(f"{assistant_name} \u2022 ONLINE", self)
        self.title_label.setGeometry(0, 14, 460, 26)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; border: none; letter-spacing: 4px; color: #3ad6ff;"
        )

        self.avatar = MoodAvatar(self)
        self.avatar.move((460 - 220) // 2, 46)

        self.status_label = QLabel("STANDBY", self)
        self.status_label.setGeometry(20, 290, 420, 60)
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(
            "font-size: 13px; border: none; color: #7fe8ff; letter-spacing: 1px;"
        )

        self.command_label = QLabel("LAST COMMAND: \u2014", self)
        self.command_label.setGeometry(20, 360, 420, 60)
        self.command_label.setWordWrap(True)
        self.command_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.command_label.setStyleSheet(
            "font-size: 12px; border: none; color: #ffb400;"
        )

        # keyboard fallback: hidden unless no microphone is detected (see update_keyboard_mode)
        self.text_input = QLineEdit(self)
        self.text_input.setGeometry(20, 470, 340, 36)
        self.text_input.setPlaceholderText("Type a command and press Enter\u2026")
        self.text_input.setStyleSheet(
            """
            QLineEdit {
                background-color: #05141c;
                color: #3ad6ff;
                border: 1px solid #3ad6ff;
                padding: 4px 8px;
                font-size: 12px;
            }
            """
        )
        self.text_input.returnPressed.connect(self._submit_typed_command)
        self.text_input.setVisible(False)

        self.send_button = QPushButton("SEND", self)
        self.send_button.setGeometry(370, 470, 70, 36)
        self.send_button.setStyleSheet(
            """
            QPushButton {
                background-color: #05141c;
                color: #ffb400;
                border: 1px solid #ffb400;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0d2530; }
            """
        )
        self.send_button.clicked.connect(self._submit_typed_command)
        self.send_button.setVisible(False)

        # decorative HUD overlay (corner brackets + scanlines), always on top
        self.hud_frame = HUDFrame(self)
        self.hud_frame.setGeometry(0, 0, 460, 540)
        self.hud_frame.raise_()

        self._drag_pos = None

        # System tray icon
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#3ad6ff"))
        self.tray_icon = QSystemTrayIcon(QIcon(pixmap), self)
        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.showNormal)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(lambda: os._exit(0))
        tray_menu.addAction(show_action)
        tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip(f"{config.get('assistant_name', 'Jarvis')} is running")
        self.tray_icon.show()

    def update_status(self, text):
        self.status_label.setText(text.upper())

    def update_command(self, text):
        self.command_label.setText(f"LAST COMMAND: {text}")

    def update_mood(self, mood):
        self.avatar.set_mood(mood)
        self.hud_frame.set_mood(mood)

    def update_keyboard_mode(self, show):
        self.text_input.setVisible(show)
        self.send_button.setVisible(show)
        if show:
            self.status_label.setText("NO MIC \u2014 TYPE A COMMAND BELOW")
            self.text_input.setFocus()

    def _submit_typed_command(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self.update_command(text)
        # handle_command() blocks on speech synthesis / network calls, so run it off the UI thread
        threading.Thread(target=process_typed_command, args=(text,), daemon=True).start()

    # frameless window, so let the user drag it around
    def mousePressEvent(self, event):
        self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()


# ================= MAIN =================
def _print_startup_diagnostics() -> None:
    if _OPTIONAL_IMPORT_ERRORS:
        print("Jarvis optional dependency issues:")
        for err in _OPTIONAL_IMPORT_ERRORS:
            print(f"  - {err}")
    print(f"DESKTOP_AVAILABLE={DESKTOP_AVAILABLE}")
    print(f"DISPLAY={os.environ.get('DISPLAY', '')!r}")
    print(f"TTS_ENGINE={'ready' if engine is not None else 'unavailable'}")
    print(f"STT={'ready' if sr is not None else 'unavailable'}")
    print(f"AI_CLIENT available={getattr(ai_client, 'available', False)}")


if __name__ == "__main__":
    _print_startup_diagnostics()
    if QApplication is None or not DESKTOP_AVAILABLE:
        print(
            "GUI/voice startup blocked: required desktop packages or display missing. "
            "Install requirements.txt and run in a graphical session. "
            "Core modules (memory, skills, orchestrator, AI router) remain usable offline."
        )
        sys.exit(2)

    app = QApplication(sys.argv)

    signals = JarvisSignals()
    window = JarvisUI()
    signals.status_update.connect(window.update_status)
    signals.command_update.connect(window.update_command)
    signals.mood_update.connect(window.update_mood)
    signals.keyboard_mode.connect(window.update_keyboard_mode)

    threading.Thread(target=wake_word_listener, daemon=True).start()

    window.show()
    sys.exit(app.exec())
