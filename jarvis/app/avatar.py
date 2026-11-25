"""Aliena avatar emotion + animation logic (UI side, no Qt, no backend imports).

AvatarController decides which emotion PNG to show and how to move it for the
four animation states (idle / talking / thinking / happy). DesktopPet in
main.py feeds it time and draws the resulting Pose.
"""
import math
import os
from dataclasses import dataclass

EMOTIONS = (  # == PNG stems in assets/aliena/emotions (see manifest.json there)
    "normal", "happy", "laugh", "sad", "angry",
    "thinking", "surprised", "shy", "sleepy", "excited",
    "confused", "embarrassed", "pouting", "wink", "cute",
    "calm", "talking", "pondering", "joyful", "shocked",
)
STATES = ("idle", "talking", "thinking", "happy")

# Existing Aliena moods (emit_mood / [idle][happy][angry] reply tags) -> emotion
MOOD_TO_EMOTION = {"idle": "normal", "happy": "happy", "angry": "angry"}

_KEYWORDS = (  # (emotion, substrings) checked in order against reply text
    ("sad", ("i'm sorry", "i am sorry", "sad ", "unfortunately")),
    ("confused", ("couldn't", "could not", "not sure", "don't understand", "failed", "not available")),
    ("surprised", ("wow", "whoa", "no way", "really?!")),
    ("sleepy", ("bye", "go to sleep", "call my name again", "goodnight")),
    ("excited", ("let's go", "awesome", "amazing")),
    ("shy", ("thank you", "you're sweet", "flatter")),
    ("happy", ("yay", "great", "glad", "happy")),
)


def emotion_for_mood(mood):
    mood = (mood or "").strip().lower()
    if mood in EMOTIONS:
        return mood
    return MOOD_TO_EMOTION.get(mood, "normal")


def emotion_from_text(text):
    """Best-effort emotion for a spoken reply; 'normal' when nothing matches."""
    t = (text or "").lower()
    for emotion, words in _KEYWORDS:
        if any(w in t for w in words):
            return emotion
    return "normal"


def asset_dir(base_dir):
    return os.path.join(base_dir, "assets", "aliena", "emotions")


def asset_path(base_dir, emotion):
    return os.path.join(asset_dir(base_dir), f"{emotion}.png")


def missing_assets(base_dir):
    return [e for e in EMOTIONS if not os.path.isfile(asset_path(base_dir, e))]


@dataclass(frozen=True)
class Pose:
    frame: str           # emotion name == PNG file stem
    dy: float = 0.0      # vertical offset, px (negative = up)
    scale: float = 1.0
    angle: float = 0.0   # degrees


class AvatarController:
    EMOTION_HOLD = 5.0      # s a non-normal emotion stays before easing back to normal
    HAPPY_STATE_HOLD = 2.5  # s the "happy" animation state lasts
    TALK_FLAP = 0.18        # s per mouth frame while talking

    def __init__(self, now=0.0):
        self.emotion = "normal"
        self.state = "idle"
        self._emotion_until = None
        self._state_until = None
        self._t0 = now

    def set_emotion(self, name, now=0.0, hold=None):
        name = emotion_for_mood(name)
        self.emotion = name
        h = self.EMOTION_HOLD if hold is None else hold
        self._emotion_until = None if name == "normal" or h <= 0 else now + h

    def set_state(self, state, now=0.0):
        if state not in STATES:
            state = "idle"
        self.state = state
        self._state_until = now + self.HAPPY_STATE_HOLD if state == "happy" else None

    def tick(self, now):
        if self._emotion_until is not None and now >= self._emotion_until:
            self.emotion, self._emotion_until = "normal", None
        if self._state_until is not None and now >= self._state_until:
            self.state, self._state_until = "idle", None
        t = now - self._t0
        two_pi = 2 * math.pi
        if self.state == "talking":
            # stay in character if a strong emotion is active; otherwise flap
            # normal <-> talking (open-mouth frame from the sheet)
            frame = self.emotion
            if self.emotion == "normal" and int(t / self.TALK_FLAP) % 2 == 1:
                frame = "talking"
            return Pose(frame, dy=-3.0 * abs(math.sin(two_pi * t * 2.5)))
        if self.state == "thinking":
            frame = "thinking" if self.emotion == "normal" else self.emotion
            return Pose(frame, dy=1.5 * math.sin(two_pi * t / 2.4), angle=2.5 * math.sin(two_pi * t / 3.0))
        if self.state == "happy":
            frame = "happy" if self.emotion == "normal" else self.emotion
            return Pose(frame, dy=-7.0 * abs(math.sin(two_pi * t * 1.4)))
        # idle: slow breathing
        return Pose(self.emotion, dy=2.0 * math.sin(two_pi * t / 3.2),
                    scale=1.0 + 0.012 * math.sin(two_pi * t / 3.2))
