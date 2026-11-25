import os
import pytest
from PIL import Image
from jarvis.app import avatar as av

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REQUIRED = ["normal", "happy", "sad", "angry", "thinking", "surprised", "shy", "sleepy",
            "excited", "confused", "embarrassed", "pouting", "wink", "cute"]


def test_all_20_assets_valid_and_manifest_matches():
    import json, importlib.util
    assert av.missing_assets(ROOT) == []
    spec = importlib.util.spec_from_file_location("v", os.path.join(ROOT, "tools", "validate_aliena_emotions.py"))
    v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
    errs, info = v.validate()          # pixel conservation vs the reference sheet, padding, RGBA, canvas
    assert errs == [] and info["outputs"] == 20
    man = json.load(open(os.path.join(av.asset_dir(ROOT), "manifest.json")))
    assert set(man["emotions"]) == set(av.EMOTIONS)
    for e in REQUIRED + ["laugh", "calm", "talking", "pondering", "joyful", "shocked"]:
        im = Image.open(av.asset_path(ROOT, e))
        assert im.mode == "RGBA" and im.size[0] < 1536     # a single avatar, never the full sheet
        assert im.getchannel("A").getpixel((0, 0)) == 0


def test_mood_mapping_and_text_emotion():
    assert av.emotion_for_mood("idle") == "normal"
    assert av.emotion_for_mood("angry") == "angry"
    assert av.emotion_for_mood("wink") == "wink"
    assert av.emotion_for_mood("bogus") == "normal"
    assert av.emotion_from_text("Aw, I couldn't quite process that one, sorry!") == "confused"
    assert av.emotion_from_text("Opening Chrome") == "normal"


def test_idle_state_breathes_and_keeps_emotion():
    c = av.AvatarController(now=0)
    poses = [c.tick(t / 10) for t in range(40)]
    assert {p.frame for p in poses} == {"normal"}
    assert len({round(p.dy, 2) for p in poses}) > 5


def test_talking_flaps_mouth_then_returns_to_idle():
    c = av.AvatarController(now=0)
    c.set_state("talking", now=0)
    frames = {c.tick(t * 0.05).frame for t in range(20)}
    assert frames == {"normal", "talking"}
    c.set_state("idle", now=1)
    assert c.tick(1.1).frame == "normal"


def test_talking_keeps_strong_emotion():
    c = av.AvatarController(now=0)
    c.set_emotion("angry", now=0)
    c.set_state("talking", now=0)
    assert {c.tick(t * 0.05).frame for t in range(20)} == {"angry"}


def test_thinking_state():
    c = av.AvatarController(now=0)
    c.set_state("thinking", now=0)
    p = c.tick(0.7)
    assert p.frame == "thinking" and p.angle != 0


def test_happy_state_expires_and_emotion_reverts():
    c = av.AvatarController(now=0)
    c.set_state("happy", now=0)
    assert c.tick(0.3).frame == "happy" and c.tick(0.3).dy < 0
    assert c.tick(3.0).frame == "normal" and c.state == "idle"
    c.set_emotion("sad", now=10)
    assert c.tick(12).frame == "sad"
    assert c.tick(15.1).frame == "normal"      # eases back after EMOTION_HOLD


@pytest.mark.parametrize("e", REQUIRED)
def test_every_emotion_selectable(e):
    c = av.AvatarController(now=0)
    c.set_emotion(e, now=0)
    assert c.tick(0.1).frame == e
