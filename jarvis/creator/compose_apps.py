"""C5/C6 composers: modular Python software, Expo/React Native mobile scaffold, pygame game scaffold.

Deterministic, escaped per output context, never executed. Generated programs are scaffolds whose
runtime behaviour is NOT verified by Aliena (execution is blocked)."""

from __future__ import annotations

import json
import sys

from jarvis.creator.composers import Composer
from jarvis.creator.spec_utils import (SpecError, clean_color, clean_identifier, clean_list, clean_text, js,
                                       pyname, reject_unknown, slugify)


def safe_pkg(name: str) -> str:
    p = pyname(name)
    return "app_" + p if p in sys.stdlib_module_names or p in {"test", "tests", "src", "app"} else p


def _int(spec: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = spec.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
        raise SpecError(f"{key} must be an integer in {lo}..{hi}")
    return v


GITIGNORE = ".env\n__pycache__/\n*.pyc\nnode_modules/\n.pytest_cache/\n"


# ======================= Python software =======================
def norm_python(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("spec must be a dict")
    reject_unknown(spec, {"project_name", "description", "commands", "log_level"})
    name = clean_text(spec.get("project_name"), "project_name", maxlen=60)
    cmds, seen = [], set()
    for c in clean_list(spec.get("commands"), "commands", max_items=6, min_items=1):
        if not isinstance(c, dict):
            raise SpecError("each command must be a dict")
        reject_unknown(c, {"name", "description"}, "command")
        cn = clean_identifier(c.get("name"), "command.name")
        if cn in seen or cn in ("registry", "init"):
            raise SpecError(f"duplicate or reserved command name: {cn}")
        seen.add(cn)
        cmds.append({"name": cn, "description": clean_text(c.get("description", f"Run {cn}"), "command.description", maxlen=100)})
    level = spec.get("log_level", "INFO")
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise SpecError("log_level invalid")
    return {"project_name": name, "description": clean_text(spec.get("description", f"{name} tool"), "description"),
            "commands": cmds, "log_level": level}


def build_python(s: dict) -> dict[str, str]:
    pkg, slug = safe_pkg(s["project_name"]), slugify(s["project_name"])
    base = f"src/{pkg}"
    f: dict[str, str] = {
        "pyproject.toml": (f'[project]\nname = {json.dumps(slug)}\nversion = "0.1.0"\ndescription = {json.dumps(s["description"])}\n'
                           f'requires-python = ">=3.11"\ndependencies = []\n\n[project.scripts]\n{slug} = "{pkg}.cli:main"\n\n'
                           '[tool.setuptools.packages.find]\nwhere = ["src"]\n'),
        ".gitignore": GITIGNORE,
        "env.example": f"# Optional overrides (no secrets needed)\n{pkg.upper()}_CONFIG=config/default.toml\n",
        "config/default.toml": f'[logging]\nlevel = "{s["log_level"]}"\n',
        f"{base}/__init__.py": f'"""{s["project_name"].replace(chr(34), "")}"""\n\n__version__ = "0.1.0"\n',
        f"{base}/__main__.py": "from .cli import main\n\nraise SystemExit(main())\n",
        f"{base}/config.py": f'''import os
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.toml"


def load_config(path=None) -> dict:
    """Load TOML config; env {pkg.upper()}_CONFIG overrides the default path."""
    target = Path(path or os.environ.get("{pkg.upper()}_CONFIG", DEFAULT_PATH))
    if not target.is_file():
        return {{}}
    with target.open("rb") as fh:
        return tomllib.load(fh)
''',
        f"{base}/logging_setup.py": '''import logging


def configure(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
''',
        f"{base}/registry.py": '''_COMMANDS = {}


def register(name, help_text):
    """Decorator registering a command handler under a unique name."""
    def decorator(func):
        if name in _COMMANDS:
            raise ValueError(f"command already registered: {name}")
        _COMMANDS[name] = (func, help_text)
        return func
    return decorator


def commands():
    return dict(_COMMANDS)
''',
        f"{base}/commands/__init__.py": "".join(f"from . import {c['name']}\n" for c in s["commands"]) +
                                         "\n__all__ = [" + ", ".join(repr(c["name"]) for c in s["commands"]) + "]\n",
        f"{base}/cli.py": f'''import argparse
import logging

from . import commands as _commands  # noqa: F401  (importing registers the commands)
from .config import load_config
from .logging_setup import configure
from .registry import commands

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog={slug!r}, description={s["description"]!r})
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_func, help_text) in sorted(commands().items()):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--text", default="")
        p.add_argument("--upper", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    configure(load_config().get("logging", {{}}).get("level", "INFO"))
    func = commands()[args.command][0]
    log.debug("running %s", args.command)
    print(func(args.text, args.upper))
    return 0
''',
    }
    for c in s["commands"]:
        f[f"{base}/commands/{c['name']}.py"] = f'''from ..registry import register


@register({c["name"]!r}, {c["description"]!r})
def run(text: str = "", upper: bool = False) -> str:
    """Starting-point handler: formats the input. Replace with real logic."""
    result = f"[{c["name"]}] {{text}}".strip()
    return result.upper() if upper else result
'''
    tests = ['"""CLI tests (unittest). Run by you with PYTHONPATH=src; never run by Aliena."""',
             "import contextlib", "import io", "import unittest", "", f"from {pkg}.cli import main",
             f"from {pkg}.registry import commands", "", "", "class TestCli(unittest.TestCase):",
             "    def run_cli(self, *argv):", "        out = io.StringIO()", "        with contextlib.redirect_stdout(out):",
             "            code = main(list(argv))", "        return code, out.getvalue()", "",
             "    def test_all_commands_registered(self):",
             f"        self.assertEqual(sorted(commands()), {sorted(c['name'] for c in s['commands'])!r})", ""]
    for c in s["commands"]:
        n = c["name"]
        tests += [f"    def test_{n}(self):", f"        code, out = self.run_cli({n!r}, '--text', 'hi')",
                  "        self.assertEqual(code, 0)", f"        self.assertEqual(out.strip(), '[{n}] hi')", "",
                  f"    def test_{n}_upper(self):", f"        code, out = self.run_cli({n!r}, '--text', 'hi', '--upper')",
                  f"        self.assertEqual(out.strip(), '[{n}] hi'.upper())", ""]
    tests += ["    def test_unknown_command_exits(self):", "        with self.assertRaises(SystemExit) as cm:",
              "            with contextlib.redirect_stderr(io.StringIO()):", "                main(['nope'])",
              "        self.assertEqual(cm.exception.code, 2)", "", "", 'if __name__ == "__main__":', "    unittest.main()", ""]
    f["tests/test_cli.py"] = "\n".join(tests)
    f["docs/ARCHITECTURE.md"] = (f"# Architecture: {s['project_name']}\n\n- `cli.py`: argument parsing, dispatch\n- `registry.py`: command registry\n"
                                 "- `commands/`: one module per command (starting-point handlers)\n- `config.py`: TOML configuration\n"
                                 "- `logging_setup.py`: logging\n")
    f["README.md"] = (f"# {s['project_name']}\n\n{s['description']}\n\nModular Python CLI scaffold generated by Aliena Creator. "
                      f"Handlers are starting points, not finished logic. Run: `PYTHONPATH=src python -m {pkg} <command> --text hello`. "
                      "Tests: `PYTHONPATH=src python -m unittest discover -s tests`.\n")
    return f


# ======================= Mobile (Expo / React Native) =======================
def norm_mobile(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("spec must be a dict")
    reject_unknown(spec, {"app_name", "description", "theme", "screens"})
    name = clean_text(spec.get("app_name"), "app_name", maxlen=40)
    theme = spec.get("theme") or {}
    reject_unknown(theme, {"primary"}, "theme")
    screens, seen = [], set()
    for sc in clean_list(spec.get("screens"), "screens", max_items=5, min_items=1):
        if not isinstance(sc, dict):
            raise SpecError("each screen must be a dict")
        reject_unknown(sc, {"name", "title", "kind", "text", "items", "fields"}, "screen")
        sn = clean_identifier(sc.get("name"), "screen.name")
        if sn in seen:
            raise SpecError(f"duplicate screen: {sn}")
        seen.add(sn)
        kind = sc.get("kind", "text")
        if kind not in ("text", "list", "form"):
            raise SpecError("screen kind must be text, list or form")
        items = [{"title": clean_text(i.get("title") if isinstance(i, dict) else None, "item.title", maxlen=80),
                  "text": clean_text(i.get("text", ""), "item.text", allow_empty=True)}
                 for i in clean_list(sc.get("items"), "items", max_items=20)]
        fields = [{"name": clean_identifier(fd.get("name") if isinstance(fd, dict) else None, "field.name"),
                   "label": clean_text(fd.get("label", ""), "field.label", maxlen=40)}
                  for fd in clean_list(sc.get("fields"), "fields", max_items=8)]
        if kind == "list" and not items or kind == "form" and not fields:
            raise SpecError(f"screen '{sn}' of kind {kind} needs items/fields")
        screens.append({"name": sn, "title": clean_text(sc.get("title", sn.capitalize()), "screen.title", maxlen=30),
                        "kind": kind, "text": clean_text(sc.get("text", ""), "screen.text", allow_empty=True),
                        "items": items, "fields": fields})
    return {"app_name": name, "description": clean_text(spec.get("description", f"{name} app"), "description"),
            "theme": {"primary": clean_color(theme.get("primary"), "theme.primary", "#2563eb")}, "screens": screens}


def build_mobile(s: dict) -> dict[str, str]:
    slug = slugify(s["app_name"])
    content = {"name": s["app_name"], "description": s["description"], "screens": s["screens"]}
    initial = s["app_name"][:1].upper().replace("&", "").replace("<", "")
    f = {
        "package.json": ('{\n  "name": ' + js(slug) + ',\n  "version": "0.1.0",\n  "main": "App.js",\n'
                         '  "scripts": { "start": "expo start", "test": "jest" },\n'
                         '  "dependencies": { "expo": "^51.0.0", "expo-status-bar": "~1.12.1", "react": "18.2.0", "react-native": "0.74.5" },\n'
                         '  "devDependencies": { "jest": "^29.7.0", "jest-expo": "~51.0.0" },\n  "jest": { "preset": "jest-expo" }\n}\n'),
        "app.json": '{\n  "expo": { "name": ' + js(s["app_name"]) + ', "slug": ' + js(slug) + ', "version": "0.1.0", "orientation": "portrait" }\n}\n',
        ".gitignore": GITIGNORE,
        "src/data/content.js": "export const content = " + js(content) + ";\n",
        "src/theme.js": f"export const theme = {{ primary: {js(s['theme']['primary'])}, background: '#ffffff', text: '#1b1f24', card: '#f4f6f9' }};\n",
        "src/components/TabBar.js": """import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';

export default function TabBar({ screens, active, onChange }) {
  return (
    <View style={styles.bar} accessibilityRole="tablist">
      {screens.map((s) => (
        <Pressable key={s.name} style={styles.tab} onPress={() => onChange(s.name)} accessibilityRole="tab"
          accessibilityState={{ selected: s.name === active }}>
          <Text style={[styles.label, s.name === active && styles.active]}>{s.title}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row', borderTopWidth: 1, borderColor: '#8884' },
  tab: { flex: 1, padding: 14, alignItems: 'center' },
  label: { color: theme.text },
  active: { color: theme.primary, fontWeight: '700' },
});
""",
        "src/components/TextScreen.js": """import { StyleSheet, Text, View } from 'react-native';

export default function TextScreen({ screen }) {
  return (
    <View style={styles.box}>
      <Text style={styles.title}>{screen.title}</Text>
      <Text>{screen.text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({ box: { padding: 20 }, title: { fontSize: 22, fontWeight: '700', marginBottom: 8 } });
""",
        "src/components/ListScreen.js": """import { FlatList, StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';

export default function ListScreen({ screen }) {
  return (
    <View style={styles.box}>
      <Text style={styles.title}>{screen.title}</Text>
      {screen.text ? <Text>{screen.text}</Text> : null}
      <FlatList
        data={screen.items}
        keyExtractor={(item, index) => item.title + index}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>{item.title}</Text>
            {item.text ? <Text>{item.text}</Text> : null}
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  box: { padding: 20, flex: 1 },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 8 },
  card: { backgroundColor: theme.card, borderRadius: 10, padding: 12, marginTop: 10 },
  cardTitle: { fontWeight: '600' },
});
""",
        "src/components/FormScreen.js": """import { useState } from 'react';
import { Button, StyleSheet, Text, TextInput, View } from 'react-native';
import { theme } from '../theme';

export default function FormScreen({ screen }) {
  const [values, setValues] = useState({});
  const [message, setMessage] = useState('');

  function submit() {
    const missing = screen.fields.filter((f) => !(values[f.name] || '').trim());
    setMessage(missing.length ? 'Please fill in: ' + missing.map((f) => f.label).join(', ') : 'Saved locally (demo: no backend).');
  }

  return (
    <View style={styles.box}>
      <Text style={styles.title}>{screen.title}</Text>
      {screen.fields.map((f) => (
        <View key={f.name} style={styles.row}>
          <Text>{f.label}</Text>
          <TextInput style={styles.input} value={values[f.name] || ''} accessibilityLabel={f.label}
            onChangeText={(t) => setValues({ ...values, [f.name]: t })} />
        </View>
      ))}
      <Button title="Submit" color={theme.primary} onPress={submit} />
      <Text accessibilityLiveRegion="polite">{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { padding: 20 },
  title: { fontSize: 22, fontWeight: '700', marginBottom: 8 },
  row: { marginBottom: 12 },
  input: { borderWidth: 1, borderColor: '#8887', borderRadius: 8, padding: 8 },
});
""",
        "App.js": """import { useState } from 'react';
import { SafeAreaView, StyleSheet, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { content } from './src/data/content';
import TabBar from './src/components/TabBar';
import TextScreen from './src/components/TextScreen';
import ListScreen from './src/components/ListScreen';
import FormScreen from './src/components/FormScreen';

const VIEWS = { text: TextScreen, list: ListScreen, form: FormScreen };

export default function App() {
  const [active, setActive] = useState(content.screens[0].name);
  const screen = content.screens.find((s) => s.name === active) || content.screens[0];
  const View_ = VIEWS[screen.kind] || TextScreen;
  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.body}><View_ screen={screen} /></View>
      <TabBar screens={content.screens} active={active} onChange={setActive} />
      <StatusBar style="auto" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1, backgroundColor: '#ffffff' }, body: { flex: 1 } });
""",
        "__tests__/content.test.js": (f"import {{ content }} from '../src/data/content';\n\ndescribe('content', () => {{\n"
                                      f"  test('has {len(s['screens'])} screens', () => {{\n    expect(content.screens).toHaveLength({len(s['screens'])});\n  }});\n"
                                      "  test('screen names are unique', () => {\n    const names = content.screens.map((s) => s.name);\n    expect(new Set(names).size).toBe(names.length);\n  });\n});\n"),
        "assets/images/logo.svg": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{s["theme"]["primary"]}"/>'
                                   f'<text x="32" y="43" font-family="sans-serif" font-size="34" text-anchor="middle" fill="#ffffff">{initial}</text></svg>\n'),
        "assets/manifest.json": json.dumps({"images": ["assets/images/logo.svg"], "note": "Expo requires PNG for app icons: export logo.svg to PNG yourself."}, indent=2) + "\n",
        "assets/README.md": "# Assets\n\n- `images/`: logos and artwork (SVG source)\n- `manifest.json`: asset inventory\n\nExpo app icons need PNG exports of the SVGs.\n",
        "docs/SCREENS.md": f"# Screens: {s['app_name']}\n\n" + "\n".join(f"- `{x['name']}` ({x['kind']}): {x['title']}" for x in s["screens"]) + "\n",
        "README.md": (f"# {s['app_name']}\n\n{s['description']}\n\nExpo / React Native scaffold generated by Aliena Creator with simple "
                      "state-based tab navigation (no navigation library). Not built or run by Aliena. Install dependencies yourself "
                      "(`npm install`), then `npx expo start`. Tests: `npm test`.\n"),
    }
    return f


# ======================= Game (pygame) =======================
def norm_game(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("spec must be a dict")
    reject_unknown(spec, {"game_name", "description", "width", "height", "player_speed", "items", "hazards",
                          "lives", "seed", "colors"})
    colors = spec.get("colors") or {}
    reject_unknown(colors, {"background", "player", "item", "hazard"}, "colors")
    name = clean_text(spec.get("game_name"), "game_name", maxlen=40)
    return {"game_name": name, "description": clean_text(spec.get("description", f"{name} game"), "description"),
            "width": _int(spec, "width", 640, 320, 1280), "height": _int(spec, "height", 480, 240, 960),
            "player_speed": _int(spec, "player_speed", 5, 1, 20), "items": _int(spec, "items", 5, 1, 30),
            "hazards": _int(spec, "hazards", 3, 0, 15), "lives": _int(spec, "lives", 3, 1, 9),
            "seed": _int(spec, "seed", 42, 0, 2**31 - 1),
            "colors": {"background": clean_color(colors.get("background"), "colors.background", "#14141e"),
                       "player": clean_color(colors.get("player"), "colors.player", "#4ade80"),
                       "item": clean_color(colors.get("item"), "colors.item", "#facc15"),
                       "hazard": clean_color(colors.get("hazard"), "colors.hazard", "#f87171")}}


_LOGIC = '''"""Pure game logic (no pygame import): deterministic for a given seed, so it can be unit tested."""
import random
from dataclasses import dataclass, field

PLAYER_RADIUS = 12
ITEM_RADIUS = 8
HAZARD_RADIUS = 14


@dataclass
class GameState:
    width: int
    height: int
    player: list
    items: list
    hazards: list  # each [x, y, vx]
    score: int
    lives: int
    ticks: int
    over: bool
    rng: random.Random = field(repr=False)


def _spawn(rng, width, height):
    return [float(rng.randint(20, width - 20)), float(rng.randint(20, height - 20))]


def new_game(cfg, seed=None):
    rng = random.Random(cfg["seed"] if seed is None else seed)
    width, height = cfg["width"], cfg["height"]
    items = [_spawn(rng, width, height) for _ in range(cfg["items"])]
    hazards = []
    for _ in range(cfg["hazards"]):
        x, y = _spawn(rng, width, height)
        hazards.append([x, y, float(rng.choice((-2, -1, 1, 2)))])
    return GameState(width, height, [width / 2, height / 2], items, hazards, 0, cfg["lives"], 0, False, rng)


def _hit(a, b, radius):
    dx, dy = a[0] - b[0], a[1] - b[1]
    return dx * dx + dy * dy <= radius * radius


def step(state, dx, dy, cfg):
    """Advance one tick. dx, dy in {-1, 0, 1}. Returns the same (mutated) state."""
    if state.over:
        return state
    speed = cfg["player_speed"]
    state.player[0] = min(max(state.player[0] + dx * speed, 0), state.width)
    state.player[1] = min(max(state.player[1] + dy * speed, 0), state.height)
    for hz in state.hazards:
        hz[0] += hz[2]
        if hz[0] < 0 or hz[0] > state.width:
            hz[2] = -hz[2]
            hz[0] = min(max(hz[0], 0), state.width)
    for item in state.items:
        if _hit(state.player, item, PLAYER_RADIUS + ITEM_RADIUS):
            state.score += 1
            item[0], item[1] = _spawn(state.rng, state.width, state.height)
    for hz in state.hazards:
        if _hit(state.player, hz, PLAYER_RADIUS + HAZARD_RADIUS):
            state.lives -= 1
            hz[0], hz[1] = _spawn(state.rng, state.width, state.height)
            if state.lives <= 0:
                state.over = True
                break
    state.ticks += 1
    return state
'''

_GAME_CONFIG = '''import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "game.json"
_RANGES = {"width": (320, 1280), "height": (240, 960), "player_speed": (1, 20), "items": (1, 30),
           "hazards": (0, 15), "lives": (1, 9), "seed": (0, 2**31 - 1)}


def load_config(path=None) -> dict:
    with Path(path or DEFAULT_PATH).open("r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    for key, (lo, hi) in _RANGES.items():
        value = cfg.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
            raise ValueError(f"config {key} must be an integer in {lo}..{hi}")
    return cfg
'''

_GAME_MAIN = '''import pygame

from .config import load_config
from .logic import HAZARD_RADIUS, ITEM_RADIUS, PLAYER_RADIUS, new_game, step


def run(config_path=None) -> None:
    cfg = load_config(config_path)
    pygame.init()
    screen = pygame.display.set_mode((cfg["width"], cfg["height"]))
    pygame.display.set_caption(cfg["title"])
    font = pygame.font.SysFont(None, 28)
    clock = pygame.time.Clock()
    state = new_game(cfg)
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                state = new_game(cfg)
        keys = pygame.key.get_pressed()
        dx = int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT])
        dy = int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP])
        step(state, dx, dy, cfg)
        colors = cfg["colors"]
        screen.fill(pygame.Color(colors["background"]))
        for item in state.items:
            pygame.draw.circle(screen, pygame.Color(colors["item"]), (int(item[0]), int(item[1])), ITEM_RADIUS)
        for hz in state.hazards:
            pygame.draw.circle(screen, pygame.Color(colors["hazard"]), (int(hz[0]), int(hz[1])), HAZARD_RADIUS)
        pygame.draw.circle(screen, pygame.Color(colors["player"]), (int(state.player[0]), int(state.player[1])), PLAYER_RADIUS)
        hud = f"Score {state.score}   Lives {state.lives}"
        screen.blit(font.render(hud, True, (255, 255, 255)), (10, 10))
        if state.over:
            screen.blit(font.render("Game over - press R to restart", True, (255, 255, 255)), (10, 40))
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()
'''


def build_game(s: dict) -> dict[str, str]:
    pkg, slug = safe_pkg(s["game_name"]), slugify(s["game_name"])
    cfg = {"title": s["game_name"], **{k: s[k] for k in ("width", "height", "player_speed", "items", "hazards", "lives", "seed")},
           "colors": s["colors"]}
    t = ['"""Logic tests (unittest). Run by you with PYTHONPATH=src; never run by Aliena."""', "import unittest", "",
         f"from {pkg}.logic import new_game, step", "", f"CFG = {cfg!r}", "", "", "class TestLogic(unittest.TestCase):",
         "    def test_player_is_clamped_to_bounds(self):", "        state = new_game(CFG)",
         "        step(state, -1, -1, dict(CFG, player_speed=10_000))", "        self.assertEqual(state.player, [0, 0])", "",
         "    def test_same_seed_same_world(self):", "        a, b = new_game(CFG), new_game(CFG)",
         "        moves = [(1, 0), (0, 1), (-1, 0), (0, -1)] * 25",
         "        for dx, dy in moves:", "            step(a, dx, dy, CFG)", "            step(b, dx, dy, CFG)",
         "        self.assertEqual((a.player, a.items, a.hazards, a.score, a.lives), (b.player, b.items, b.hazards, b.score, b.lives))", "",
         "    def test_different_seed_differs(self):", "        self.assertNotEqual(new_game(CFG, seed=1).items, new_game(CFG, seed=2).items)", "",
         "    def test_collecting_item_scores(self):", "        state = new_game(CFG)", "        state.hazards = []",
         "        state.items[0] = list(state.player)", "        step(state, 0, 0, CFG)", "        self.assertEqual(state.score, 1)", ""]
    if s["hazards"] > 0:
        t += ["    def test_hazard_costs_a_life(self):", "        state = new_game(CFG)", "        state.items = []",
              "        state.hazards = [[state.player[0], state.player[1], 0.0]]", "        step(state, 0, 0, CFG)",
              f"        self.assertEqual(state.lives, {s['lives'] - 1})", "",
              "    def test_game_over_at_zero_lives(self):", "        state = new_game(CFG)", "        state.items = []", "        state.lives = 1",
              "        state.hazards = [[state.player[0], state.player[1], 0.0]]", "        step(state, 0, 0, CFG)",
              "        self.assertTrue(state.over)", "        ticks = state.ticks", "        step(state, 1, 1, CFG)",
              "        self.assertEqual(state.ticks, ticks)", ""]
    t += ["", 'if __name__ == "__main__":', "    unittest.main()", ""]
    svg = lambda body: f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">{body}</svg>\n'
    c = s["colors"]
    return {
        "requirements.txt": "pygame>=2.5\n", ".gitignore": GITIGNORE,
        "config/game.json": json.dumps(cfg, indent=2) + "\n",
        f"src/{pkg}/__init__.py": "", f"src/{pkg}/__main__.py": "from .main import run\n\nrun()\n",
        f"src/{pkg}/config.py": _GAME_CONFIG, f"src/{pkg}/logic.py": _LOGIC, f"src/{pkg}/main.py": _GAME_MAIN,
        "tests/test_logic.py": "\n".join(t),
        "assets/images/player.svg": svg(f'<circle cx="16" cy="16" r="12" fill="{c["player"]}"/>'),
        "assets/images/item.svg": svg(f'<circle cx="16" cy="16" r="8" fill="{c["item"]}"/>'),
        "assets/images/hazard.svg": svg(f'<circle cx="16" cy="16" r="14" fill="{c["hazard"]}"/>'),
        "assets/sounds/README.md": "# Sounds\n\nPlace `.wav`/`.ogg` files here and reference them from `main.py`. None are generated.\n",
        "assets/manifest.json": json.dumps({"images": ["assets/images/player.svg", "assets/images/item.svg", "assets/images/hazard.svg"],
                                            "sounds": [], "note": "The scaffold draws shapes with pygame; SVGs are reference art."}, indent=2) + "\n",
        "docs/DESIGN.md": (f"# Design: {s['game_name']}\n\nCollector game: move with the arrow keys, collect items, avoid hazards.\n\n"
                           f"- Window {s['width']}x{s['height']}, speed {s['player_speed']}, {s['items']} items, {s['hazards']} hazards, {s['lives']} lives, seed {s['seed']}\n"
                           "- `logic.py` is pure and deterministic; `main.py` is the pygame front end; `config/game.json` holds tunables.\n"),
        "README.md": (f"# {s['game_name']}\n\n{s['description']}\n\npygame scaffold generated by Aliena Creator. Not run by Aliena. "
                      f"Install pygame yourself, then `PYTHONPATH=src python -m {pkg}`. Tests: `PYTHONPATH=src python -m unittest discover -s tests`.\n"),
    }


COMPOSERS = [
    Composer("python_software", "1.0.0", "python_app", "Modular Python CLI application", norm_python, build_python),
    Composer("mobile_app", "1.0.0", "mobile_scaffold", "Expo / React Native app scaffold", norm_mobile, build_mobile),
    Composer("game_collector", "1.0.0", "game_scaffold", "pygame collector game scaffold", norm_game, build_game),
]
