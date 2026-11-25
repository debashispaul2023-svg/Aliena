"""HUD open/minimize/restore logic tests.

PyQt6 is not installed in CI/sandbox, so a minimal behavioural Qt stub models
visibility, timers, focus and signals. This verifies Aliena's control logic,
NOT real window-manager behaviour (see report: real-GUI run still required).
"""
import sys, types, threading, time
import pytest


class _E:
    def __getattr__(self, n): return _E()
    def __or__(self, o): return self
    def __call__(self, *a, **k): return _E()
    def __int__(self): return 0
    def __eq__(self, o): return isinstance(o, _E)
    def __hash__(self): return 0
    def __rand__(self, o): return True


class _Sig:
    def __init__(self): self.slots = []
    def connect(self, f): self.slots.append(f)
    def emit(self, *a):
        for f in list(self.slots): f(*a)


class _Pt:
    def __init__(self, x=0, y=0): self.x, self.y = x, y
    def __sub__(self, o): return _Pt(self.x - o.x, self.y - o.y)
    def manhattanLength(self): return abs(self.x) + abs(self.y)
    def topLeft(self): return self


class _W:
    instances = []
    def __init__(self, *a, **k):
        self._vis = False; self._text = ""; self._focus = False
        self.shows = 0; self.clicked = _Sig(); self.returnPressed = _Sig()
        self.timeout = _Sig(); self.triggered = _Sig(); self._active = False; self.parent = a[0] if a and isinstance(a[0], _W) else None
        self.children = []
        if self.parent: self.parent.children.append(self)
        _W.instances.append(self)
    def show(self):
        if not self._vis:
            self._vis = True; self.showEvent(None)
            for c in self.children:  # Qt sends show/hide events to child widgets
                if not isinstance(c, _Timer): c.show()
        self.shows += 1
    def hide(self):
        if self._vis:
            self._vis = False; self.hideEvent(None)
            for c in self.children:
                if not isinstance(c, _Timer): c.hide()
    def showEvent(self, e): pass
    def hideEvent(self, e): pass
    def isVisible(self): return self._vis
    def setVisible(self, v): self.show() if v else self.hide()
    def setFocus(self): _W.focus = self
    def raise_(self): pass
    def activateWindow(self): pass
    def text(self): return self._text
    def setText(self, t): self._text = t
    def clear(self): self._text = ""
    def frameGeometry(self): return _Pt()
    def move(self, *a): pass
    def pos(self): return _Pt()
    def width(self): return 100
    def height(self): return 100
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        return lambda *a, **k: _E()


class _Timer(_W):
    singles = []
    def start(self, ms=0): self._active = True
    def stop(self): self._active = False
    def isActive(self): return self._active
    @staticmethod
    def singleShot(ms, fn): fn()


class _App(_W):
    @staticmethod
    def primaryScreen():
        g = types.SimpleNamespace(right=lambda: 1920, bottom=lambda: 1080)
        return types.SimpleNamespace(availableGeometry=lambda: g)


def _install_stub():
    qw = types.ModuleType("PyQt6.QtWidgets")
    for n in ("QLabel", "QWidget", "QSystemTrayIcon", "QMenu", "QLineEdit", "QPushButton"):
        setattr(qw, n, type(n, (_W,), {}))
    qw.QApplication = _App
    qc = types.ModuleType("PyQt6.QtCore")
    qc.Qt = _E(); qc.QObject = type("QObject", (_W,), {})
    qc.pyqtSignal = lambda *a: _Sig(); qc.QTimer = _Timer
    qg = types.ModuleType("PyQt6.QtGui")
    for n in ("QIcon", "QAction", "QPixmap", "QColor", "QFont", "QPainter", "QBrush", "QPen"):
        setattr(qg, n, type(n, (_W,), {}))
    pkg = types.ModuleType("PyQt6")
    sys.modules.update({"PyQt6": pkg, "PyQt6.QtWidgets": qw, "PyQt6.QtCore": qc, "PyQt6.QtGui": qg})


@pytest.fixture(scope="module")
def m():
    _install_stub()
    sys.modules.pop("jarvis.app.main", None)
    import importlib
    return importlib.import_module("jarvis.app.main")


@pytest.fixture
def ui(m):
    m.signals = None
    w = m.JarvisUI()
    state = {"opens": 0}
    pet = m.DesktopPet(w.toggle_hud)
    return w, pet


def click(pet, moved=False):
    class Ev:
        def __init__(s, x): s.x = x
        def button(s): return _E()
        def buttons(s): return 1
        def globalPosition(s): return types.SimpleNamespace(toPoint=lambda: _Pt(s.x, 0))
    pet.mousePressEvent(Ev(0))
    if moved: pet.mouseMoveEvent(Ev(50))
    pet.mouseReleaseEvent(Ev(50 if moved else 0))


def test_1_startup_hidden(ui):
    w, pet = ui
    assert not w.isVisible()                      # HUD hidden at startup
    assert not w.avatar._timer.isActive()         # no animation loop running


def test_2_3_5_toggle_cycle(ui):
    w, pet = ui
    click(pet); assert w.isVisible()              # first click opens
    assert w.avatar._timer.isActive()
    click(pet); assert not w.isVisible()          # second click minimizes
    assert not w.avatar._timer.isActive()
    click(pet); assert w.isVisible()              # restore


def test_4_minimize_button(ui):
    w, pet = ui
    click(pet); assert w.isVisible()
    w.minimize_button.clicked.emit()
    assert not w.isVisible()
    click(pet); assert w.isVisible()


def test_6_repeated_cycles_no_dupes(ui):
    w, pet = ui
    n_windows = sum(isinstance(i, type(w)) for i in _W.instances)
    for _ in range(200):
        click(pet); assert w.isVisible()
        click(pet); assert not w.isVisible()
    assert sum(isinstance(i, type(w)) for i in _W.instances) == n_windows
    assert len(w.avatar._timer.timeout.slots) == 1  # one animate connection only


def test_drag_does_not_toggle(ui):
    w, pet = ui
    click(pet, moved=True)
    assert not w.isVisible()


def test_close_and_esc_minimize_not_quit(ui):
    w, pet = ui
    w.open_hud()
    class Ev:
        ignored = False
        def ignore(s): s.ignored = True
    e = Ev(); w.closeEvent(e)
    assert e.ignored and not w.isVisible()


def test_input_focus_on_open_and_enter_submits(ui, m, monkeypatch):
    w, pet = ui
    got = []
    done = threading.Event()
    monkeypatch.setattr(m, "process_typed_command", lambda t: (got.append(t), done.set()))
    w.open_hud()
    assert _W.focus is w.text_input               # input has keyboard focus
    w.text_input.setText("hello")
    w.text_input.returnPressed.emit()             # Enter
    assert done.wait(2) and got == ["hello"]
    assert w.text_input.text() == ""


def test_minimize_does_not_cancel_background_task(ui, m, monkeypatch):
    w, pet = ui
    release, finished = threading.Event(), threading.Event()
    def slow(t):
        release.wait(5); finished.set()
    monkeypatch.setattr(m, "process_typed_command", slow)
    w.open_hud(); w.text_input.setText("long job")
    w.text_input.returnPressed.emit()
    w.minimize_hud(); w.open_hud(); w.minimize_hud()
    assert not finished.is_set()                  # still running while hidden
    release.set()
    assert finished.wait(2)                       # and completes


def test_8_command_routing_unchanged(m, monkeypatch):
    spoken = []
    monkeypatch.setattr(m, "speak", lambda t: spoken.append(t))
    monkeypatch.setattr(m, "resource_handler", None)
    calls = []
    monkeypatch.setattr(m, "automation", lambda q: calls.append(("automation", q)))
    m.handle_command("open chrome")               # browser/app open route
    assert calls == [("automation", "open chrome")]


def test_pet_wired_to_response_states(ui, m):
    w, pet = ui
    assert pet.controller.tick(0).frame == "normal"          # robot gone; starts Normal/idle
    pet.set_avatar_state("thinking"); assert pet.controller.tick(0.1).frame == "thinking"
    pet.set_avatar_state("talking"); assert pet.controller.state == "talking"
    pet.set_mood("angry"); assert pet.controller.emotion == "angry"      # existing mood signal
    pet.set_emotion("wink"); assert pet.controller.emotion == "wink"     # new emotion signal
    pet.set_mood("happy"); assert pet.controller.state == "happy"
    # exactly one animation timer, connected once
    assert pet._anim_timer.isActive() and len(pet._anim_timer.timeout.slots) == 1


def test_speak_and_command_emit_avatar_events(m, monkeypatch):
    ev = []
    monkeypatch.setattr(m, "emit_avatar_state", lambda s: ev.append(("state", s)))
    monkeypatch.setattr(m, "emit_avatar_emotion", lambda e: ev.append(("emo", e)))
    monkeypatch.setattr(m, "emit_status", lambda t: None)
    monkeypatch.setattr(m, "engine", None)
    m.speak("Aw, I couldn't do that")
    assert ev[0] == ("emo", "confused") and ("state", "talking") in ev and ev[-1] == ("state", "idle")
    ev.clear()
    monkeypatch.setattr(m, "resource_handler", None)
    monkeypatch.setattr(m, "automation", lambda q: None)
    monkeypatch.setattr(m, "emit_command", lambda q: None)
    m.handle_command("open chrome")
    assert ev[0] == ("state", "thinking") and ev[-1] == ("state", "idle")


def test_reply_tag_accepts_new_emotions(m):
    assert m.parse_emotion_reply("[shy] hello there") == ("shy", "hello there")
    assert m.parse_emotion_reply("[happy] yay") == ("happy", "yay")
    assert m.parse_emotion_reply("plain") == ("idle", "plain")
