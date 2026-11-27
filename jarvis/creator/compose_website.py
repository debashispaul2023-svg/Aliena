"""C4 website composer: HTML/CSS/JS, React (Vite) and Next.js sites from a validated spec.

All user text is escaped for its output context (HTML text/attr via h(), JS/JSON via js()).
Nothing is run, installed or fetched."""

from __future__ import annotations

from typing import Any

from jarvis.creator.composers import Composer
from jarvis.creator.spec_utils import (SpecError, clean_color, clean_list, clean_text, h, js, pyname,
                                       reject_unknown, slugify)

SECTION_TYPES = ("about", "services", "menu", "gallery", "testimonials", "faq", "contact")
CARD_TYPES = {"services", "menu", "gallery", "testimonials", "faq"}
FRAMEWORKS = ("html", "react", "nextjs")


def normalize(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("spec must be a dict")
    reject_unknown(spec, {"site_name", "tagline", "description", "framework", "layout", "theme", "sections",
                          "contact_form", "api"})
    name = clean_text(spec.get("site_name"), "site_name", maxlen=60)
    framework = spec.get("framework", "html")
    if framework not in FRAMEWORKS:
        raise SpecError(f"framework must be one of {FRAMEWORKS}")
    layout = spec.get("layout", "multi_page" if framework == "html" else "single_page")
    if layout not in ("single_page", "multi_page") or (framework != "html" and layout == "multi_page"):
        raise SpecError("layout invalid (react/nextjs support single_page only)")
    theme = spec.get("theme") or {}
    if not isinstance(theme, dict):
        raise SpecError("theme must be a dict")
    reject_unknown(theme, {"primary", "accent", "dark_mode"}, "theme")
    sections, seen = [], set()
    for i, sec in enumerate(clean_list(spec.get("sections"), "sections", max_items=7, min_items=1)):
        if not isinstance(sec, dict):
            raise SpecError("each section must be a dict")
        reject_unknown(sec, {"type", "title", "text", "items"}, "section")
        t = sec.get("type")
        if t not in SECTION_TYPES:
            raise SpecError(f"section type must be one of {SECTION_TYPES}")
        if t in seen:
            raise SpecError(f"duplicate section type: {t}")
        seen.add(t)
        items = []
        for it in clean_list(sec.get("items"), "items", max_items=12):
            if not isinstance(it, dict):
                raise SpecError("each item must be a dict")
            reject_unknown(it, {"title", "text", "price"}, "item")
            items.append({"title": clean_text(it.get("title"), "item.title", maxlen=80),
                          "text": clean_text(it.get("text", ""), "item.text", allow_empty=True),
                          "price": clean_text(it.get("price", ""), "item.price", maxlen=20, allow_empty=True)})
        if t in CARD_TYPES and not items:
            raise SpecError(f"section '{t}' needs at least one item")
        sections.append({"type": t, "title": clean_text(sec.get("title", t.capitalize()), "section.title", maxlen=60),
                         "text": clean_text(sec.get("text", ""), "section.text", allow_empty=True), "items": items})
    api = spec.get("api") or {}
    if not isinstance(api, dict):
        raise SpecError("api must be a dict")
    reject_unknown(api, {"enabled"}, "api")
    has_contact = "contact" in seen
    return {
        "site_name": name, "tagline": clean_text(spec.get("tagline", ""), "tagline", allow_empty=True),
        "description": clean_text(spec.get("description", f"{name} website"), "description"),
        "framework": framework, "layout": layout,
        "theme": {"primary": clean_color(theme.get("primary"), "theme.primary", "#2563eb"),
                  "accent": clean_color(theme.get("accent"), "theme.accent", "#f59e0b"),
                  "dark_mode": bool(theme.get("dark_mode", True))},
        "sections": sections, "contact_form": bool(spec.get("contact_form", has_contact)) and has_contact,
        "api": {"enabled": bool(api.get("enabled", False)) and has_contact},
    }


# ---------------- shared assets ----------------
def _css(theme: dict) -> str:
    css = """/* generated: responsive, mobile-first */
:root { --primary: __P__; --accent: __A__; --bg: #ffffff; --fg: #1b1f24; --muted: #5b6573; --card: #f4f6f9; --radius: 12px; }
__DARK__
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--fg); line-height: 1.6; }
.skip-link { position: absolute; left: -999px; top: 0; background: var(--primary); color: #fff; padding: .5rem 1rem; }
.skip-link:focus { left: 0; z-index: 10; }
.container { width: min(100% - 2rem, 68rem); margin-inline: auto; }
.site-header { position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid #8884; z-index: 5; }
.nav { display: flex; align-items: center; justify-content: space-between; padding: .75rem 0; flex-wrap: wrap; gap: .5rem; }
.brand { font-weight: 700; color: var(--primary); text-decoration: none; display: flex; align-items: center; gap: .5rem; }
.nav-toggle { display: inline-block; background: none; border: 1px solid #8886; border-radius: 8px; padding: .35rem .75rem; color: inherit; cursor: pointer; }
.nav-links { display: none; list-style: none; margin: 0; padding: 0; width: 100%; flex-direction: column; gap: .25rem; }
.nav-links.open { display: flex; }
.nav-links a { display: block; padding: .5rem 0; color: inherit; text-decoration: none; }
.nav-links a:hover, .nav-links a[aria-current="page"] { color: var(--primary); }
.hero { padding: 3rem 0; background: linear-gradient(135deg, var(--primary), var(--accent)); color: #fff; }
.hero h1 { margin: 0 0 .5rem; font-size: clamp(1.75rem, 5vw, 3rem); }
.hero p { margin: 0; font-size: 1.125rem; max-width: 40rem; }
section { padding: 2.5rem 0; }
section h2 { margin-top: 0; color: var(--primary); }
.cards { list-style: none; padding: 0; margin: 0; display: grid; gap: 1rem; grid-template-columns: 1fr; }
.card { background: var(--card); border-radius: var(--radius); padding: 1rem 1.25rem; }
.card h3 { margin: 0 0 .25rem; }
.card img { max-width: 100%; border-radius: 8px; }
.price { display: inline-block; margin-top: .5rem; font-weight: 700; color: var(--accent); }
details { background: var(--card); border-radius: var(--radius); padding: .75rem 1rem; margin-bottom: .75rem; }
summary { cursor: pointer; font-weight: 600; }
form { display: grid; gap: .75rem; max-width: 32rem; }
label { display: grid; gap: .25rem; font-weight: 600; }
input, textarea { font: inherit; padding: .6rem .75rem; border: 1px solid #8887; border-radius: 8px; background: var(--bg); color: var(--fg); }
input:focus-visible, textarea:focus-visible, button:focus-visible, a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
button.primary { background: var(--primary); color: #fff; border: 0; border-radius: 8px; padding: .7rem 1.2rem; font: inherit; cursor: pointer; }
.field-error, .form-status { color: #b42318; font-size: .9rem; min-height: 1.2em; }
.form-status.ok { color: #067647; }
.site-footer { padding: 1.5rem 0; border-top: 1px solid #8884; color: var(--muted); font-size: .9rem; }
@media (min-width: 40rem) { .cards { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 52rem) {
  .nav-toggle { display: none; }
  .nav-links { display: flex; flex-direction: row; width: auto; gap: 1.25rem; }
  .cards { grid-template-columns: repeat(3, 1fr); }
}
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""
    dark = ("@media (prefers-color-scheme: dark) { :root { --bg: #0f1216; --fg: #e8ecf1; --muted: #9aa5b4; --card: #1a2028; } }"
            if theme["dark_mode"] else "")
    return css.replace("__P__", theme["primary"]).replace("__A__", theme["accent"]).replace("__DARK__", dark)


def _logo(name: str, theme: dict) -> str:
    initial = h(name[:1].upper())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="{h(name)} logo">'
            f'<rect width="64" height="64" rx="14" fill="{theme["primary"]}"/>'
            f'<text x="32" y="43" font-family="sans-serif" font-size="34" text-anchor="middle" fill="#ffffff">{initial}</text></svg>\n')


def _placeholder() -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 240" role="img" aria-label="placeholder image">'
            '<rect width="400" height="240" fill="#cbd5e1"/><path d="M0 200 120 110 200 170 290 90 400 190V240H0Z" fill="#94a3b8"/></svg>\n')


def _openapi(name: str) -> str:
    return f"""openapi: 3.0.3
info:
  title: {js(name + ' API')}
  version: 0.1.0
  description: DRAFT contract for the contact form. Not implemented by this scaffold.
paths:
  /api/contact:
    post:
      summary: Submit a contact message
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name, email, message]
              properties:
                name: {{ type: string, maxLength: 80 }}
                email: {{ type: string, format: email }}
                message: {{ type: string, maxLength: 2000 }}
      responses:
        "201": {{ description: Created }}
        "422": {{ description: Validation error }}
"""


_SCHEMA = """-- DRAFT schema for contact messages. Review before applying.
CREATE TABLE IF NOT EXISTS contact_messages (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _docs(s: dict, files: list[str]) -> dict[str, str]:
    structure = "\n".join(f"- `{f}`" for f in sorted(files))
    api = ("\n## API integration (draft)\n\nThe contact form posts JSON to `/api/contact`. `api/openapi.yaml` and "
           "`db/schema.sql` are drafts; no backend is generated by this composer. Wire one up yourself or generate a "
           "backend project and map the route.\n") if s["api"]["enabled"] else ""
    readme = (f"# {s['site_name']}\n\n{s['description']}\n\nGenerated by the Aliena Creator Engine "
              f"(website composer, framework: {s['framework']}). Scaffold: review before publishing.\n\n"
              f"## Structure\n\n{structure}\n{api}")
    return {"README.md": readme}


# ---------------- HTML framework ----------------
def _page_name(sec: dict) -> str:
    return f"{sec['type']}.html"


def _nav(s: dict, current: str) -> str:
    multi = s["layout"] == "multi_page"
    links = []
    home = "index.html" if multi else "#top"
    links.append(("Home", home, "index.html"))
    for sec in s["sections"]:
        href = _page_name(sec) if multi else f"#{sec['type']}"
        links.append((sec["title"], href, _page_name(sec)))
    items = "\n".join(
        f'        <li><a href="{h(href)}"{" aria-current=" + chr(34) + "page" + chr(34) if multi and page == current else ""}>{h(label)}</a></li>'
        for label, href, page in links)
    return f"""    <nav class="nav container" aria-label="Main">
      <a class="brand" href="{"index.html" if multi else "#top"}"><img src="assets/logo.svg" alt="" width="32" height="32">{h(s['site_name'])}</a>
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="nav-links">Menu</button>
      <ul id="nav-links" class="nav-links">
{items}
      </ul>
    </nav>"""


def _section_html(sec: dict, s: dict) -> str:
    t, title, text = sec["type"], h(sec["title"]), h(sec["text"])
    body = f"      <p>{text}</p>\n" if text else ""
    if t == "about":
        pass
    elif t == "faq":
        body += "".join(f"      <details><summary>{h(i['title'])}</summary><p>{h(i['text'])}</p></details>\n"
                        for i in sec["items"])
    elif t in CARD_TYPES:
        cards = []
        for i in sec["items"]:
            img = '<img src="assets/placeholder.svg" alt="" width="400" height="240" loading="lazy">' if t == "gallery" else ""
            price = f'<span class="price">{h(i["price"])}</span>' if i["price"] else ""
            p = f"<p>{h(i['text'])}</p>" if i["text"] else ""
            cards.append(f'        <li class="card">{img}<h3>{h(i["title"])}</h3>{p}{price}</li>')
        body += '      <ul class="cards">\n' + "\n".join(cards) + "\n      </ul>\n"
    elif t == "contact":
        if s["contact_form"]:
            body += """      <form id="contact-form" novalidate>
        <label>Name<input name="name" type="text" autocomplete="name" required maxlength="80"><span class="field-error" data-for="name"></span></label>
        <label>Email<input name="email" type="email" autocomplete="email" required><span class="field-error" data-for="email"></span></label>
        <label>Message<textarea name="message" rows="5" required maxlength="2000"></textarea><span class="field-error" data-for="message"></span></label>
        <button class="primary" type="submit">Send message</button>
        <p class="form-status" role="status" aria-live="polite"></p>
      </form>
"""
    return f'    <section id="{t}" aria-labelledby="{t}-title">\n      <h2 id="{t}-title">{title}</h2>\n{body}    </section>\n'


def _page(s: dict, current: str, inner: str, title: str, scripts: list[str]) -> str:
    tags = "".join(f'  <script src="{x}" defer></script>\n' for x in scripts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)}</title>
  <meta name="description" content="{h(s['description'])}">
  <link rel="icon" href="assets/logo.svg" type="image/svg+xml">
  <link rel="stylesheet" href="css/styles.css">
</head>
<body id="top">
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
{_nav(s, current)}
  </header>
  <main id="main">
{inner}  </main>
  <footer class="site-footer"><div class="container">&copy; {h(s['site_name'])}. Generated scaffold.</div></footer>
{tags}</body>
</html>
"""


def _hero(s: dict) -> str:
    tag = f"<p>{h(s['tagline'])}</p>" if s["tagline"] else ""
    return f'    <div class="hero"><div class="container"><h1>{h(s["site_name"])}</h1>{tag}</div></div>\n'


_MAIN_JS = """(function () {
  'use strict';
  var toggle = document.querySelector('.nav-toggle');
  var links = document.getElementById('nav-links');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      var open = links.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
  }
  var form = document.getElementById('contact-form');
  if (!form) { return; }
  var status = form.querySelector('.form-status');
  function setError(name, msg) {
    var el = form.querySelector('[data-for="' + name + '"]');
    if (el) { el.textContent = msg; }
  }
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var data = { name: form.name.value.trim(), email: form.email.value.trim(), message: form.message.value.trim() };
    var ok = true;
    setError('name', data.name ? '' : 'Please enter your name.');
    setError('email', /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(data.email) ? '' : 'Please enter a valid email.');
    setError('message', data.message ? '' : 'Please enter a message.');
    ok = data.name && /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(data.email) && data.message;
    if (!ok) { status.textContent = 'Please fix the errors above.'; status.className = 'form-status'; return; }
    if (window.submitContact) {
      window.submitContact(data).then(function () {
        status.textContent = 'Thank you! Your message was sent.'; status.className = 'form-status ok'; form.reset();
      }).catch(function () {
        status.textContent = 'Sorry, sending failed. Please try again later.'; status.className = 'form-status';
      });
    } else {
      status.textContent = 'Thank you! (Demo: no backend is connected.)'; status.className = 'form-status ok'; form.reset();
    }
  });
})();
"""

_API_JS = """window.submitContact = function (data) {
  return fetch('/api/contact', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  }).then(function (response) {
    if (!response.ok) { throw new Error('request failed'); }
    return response.json().catch(function () { return {}; });
  });
};
"""


def _site_test(pages: list[str]) -> str:
    return f'''"""Structure checks for the generated site. Run by you (e.g. python -m unittest); never run by Aliena."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = {pages!r}


class TestSiteStructure(unittest.TestCase):
    def test_pages_exist(self):
        for page in PAGES:
            self.assertTrue((ROOT / page).is_file(), page)

    def test_local_references_resolve(self):
        for page in PAGES:
            text = (ROOT / page).read_text(encoding="utf-8")
            for ref in re.findall(r'(?:href|src)="([^"#:]+)"', text):
                self.assertTrue((ROOT / ref).exists(), f"{{page}} -> {{ref}}")


if __name__ == "__main__":
    unittest.main()
'''


def _build_html(s: dict) -> dict[str, str]:
    files: dict[str, str] = {"css/styles.css": _css(s["theme"]), "assets/logo.svg": _logo(s["site_name"], s["theme"]),
                             "js/main.js": _MAIN_JS}
    scripts = ["js/main.js"]
    if s["api"]["enabled"]:
        files["js/api.js"] = _API_JS
        files["api/openapi.yaml"] = _openapi(s["site_name"])
        files["db/schema.sql"] = _SCHEMA
        scripts = ["js/api.js", "js/main.js"]
    if any(sec["type"] == "gallery" for sec in s["sections"]):
        files["assets/placeholder.svg"] = _placeholder()
    multi = s["layout"] == "multi_page"
    pages = ["index.html"]
    if multi:
        summary = "".join(f'      <li class="card"><h3><a href="{_page_name(sec)}">{h(sec["title"])}</a></h3></li>\n'
                          for sec in s["sections"])
        inner = _hero(s) + f'    <section class="container"><ul class="cards">\n{summary}    </ul></section>\n'
        files["index.html"] = _page(s, "index.html", inner, s["site_name"], scripts)
        for sec in s["sections"]:
            inner = f'    <div class="container">\n{_section_html(sec, s)}    </div>\n'
            files[_page_name(sec)] = _page(s, _page_name(sec), inner, f"{sec['title']} - {s['site_name']}", scripts)
            pages.append(_page_name(sec))
    else:
        inner = _hero(s) + '    <div class="container">\n' + "".join(_section_html(x, s) for x in s["sections"]) + "    </div>\n"
        files["index.html"] = _page(s, "index.html", inner, s["site_name"], scripts)
    files["tests/test_site_structure.py"] = _site_test(pages)
    files.update(_docs(s, list(files) + ["README.md"]))
    return files


# ---------------- React / Next.js ----------------
def _site_data(s: dict) -> str:
    data = {"name": s["site_name"], "tagline": s["tagline"], "description": s["description"],
            "sections": s["sections"], "contactForm": s["contact_form"], "apiEnabled": s["api"]["enabled"]}
    return "export const site = " + js(data) + ";\n"


def _components(prefix_client: str) -> dict[str, str]:
    c = prefix_client
    return {
        "Navbar.jsx": c + """import { useState } from 'react';

export default function Navbar({ site }) {
  const [open, setOpen] = useState(false);
  return (
    <header className="site-header">
      <nav className="nav container" aria-label="Main">
        <a className="brand" href="#top">{site.name}</a>
        <button className="nav-toggle" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Menu</button>
        <ul className={open ? 'nav-links open' : 'nav-links'}>
          {site.sections.map((s) => (
            <li key={s.type}><a href={'#' + s.type} onClick={() => setOpen(false)}>{s.title}</a></li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
""",
        "Hero.jsx": """export default function Hero({ site }) {
  return (
    <div className="hero">
      <div className="container">
        <h1>{site.name}</h1>
        {site.tagline ? <p>{site.tagline}</p> : null}
      </div>
    </div>
  );
}
""",
        "Section.jsx": """export default function Section({ section }) {
  const { type, title, text, items } = section;
  return (
    <section id={type} aria-labelledby={type + '-title'}>
      <h2 id={type + '-title'}>{title}</h2>
      {text ? <p>{text}</p> : null}
      {type === 'faq'
        ? items.map((i) => (
            <details key={i.title}><summary>{i.title}</summary><p>{i.text}</p></details>
          ))
        : items.length > 0 && (
            <ul className="cards">
              {items.map((i) => (
                <li className="card" key={i.title}>
                  <h3>{i.title}</h3>
                  {i.text ? <p>{i.text}</p> : null}
                  {i.price ? <span className="price">{i.price}</span> : null}
                </li>
              ))}
            </ul>
          )}
    </section>
  );
}
""",
        "ContactForm.jsx": c + """import { useState } from 'react';

const EMAIL = /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/;

export default function ContactForm({ apiEnabled }) {
  const [values, setValues] = useState({ name: '', email: '', message: '' });
  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState('');

  function validate(v) {
    const e = {};
    if (!v.name.trim()) e.name = 'Please enter your name.';
    if (!EMAIL.test(v.email.trim())) e.email = 'Please enter a valid email.';
    if (!v.message.trim()) e.message = 'Please enter a message.';
    return e;
  }

  async function onSubmit(event) {
    event.preventDefault();
    const e = validate(values);
    setErrors(e);
    if (Object.keys(e).length) { setStatus('Please fix the errors above.'); return; }
    if (!apiEnabled) { setStatus('Thank you! (Demo: no backend is connected.)'); return; }
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      setStatus(res.ok ? 'Thank you! Your message was sent.' : 'Sorry, sending failed.');
    } catch (err) {
      setStatus('Sorry, sending failed.');
    }
  }

  const field = (name, label, props) => (
    <label>
      {label}
      {props.rows ? (
        <textarea {...props} value={values[name]} onChange={(ev) => setValues({ ...values, [name]: ev.target.value })} />
      ) : (
        <input {...props} value={values[name]} onChange={(ev) => setValues({ ...values, [name]: ev.target.value })} />
      )}
      <span className="field-error">{errors[name] || ''}</span>
    </label>
  );

  return (
    <form onSubmit={onSubmit} noValidate>
      {field('name', 'Name', { type: 'text', name: 'name', maxLength: 80 })}
      {field('email', 'Email', { type: 'email', name: 'email' })}
      {field('message', 'Message', { name: 'message', rows: 5, maxLength: 2000 })}
      <button className="primary" type="submit">Send message</button>
      <p className="form-status" role="status" aria-live="polite">{status}</p>
    </form>
  );
}
""",
        "Footer.jsx": """export default function Footer({ site }) {
  return (
    <footer className="site-footer">
      <div className="container">&copy; {site.name}. Generated scaffold.</div>
    </footer>
  );
}
""",
    }


def _app_body() -> str:
    return """      <a className="skip-link" href="#main">Skip to content</a>
      <Navbar site={site} />
      <main id="main">
        <Hero site={site} />
        <div className="container">
          {site.sections.map((s) => (
            <div key={s.type}>
              <Section section={s} />
              {s.type === 'contact' && site.contactForm ? <ContactForm apiEnabled={site.apiEnabled} /> : null}
            </div>
          ))}
        </div>
      </main>
      <Footer site={site} />
"""


def _extras(s: dict, files: dict[str, str]) -> None:
    if s["api"]["enabled"]:
        files["api/openapi.yaml"] = _openapi(s["site_name"])
        files["db/schema.sql"] = _SCHEMA
    files.update(_docs(s, list(files) + ["README.md"]))


def _build_react(s: dict) -> dict[str, str]:
    slug = slugify(s["site_name"])
    files = {
        "package.json": ('{\n  "name": ' + js(slug) + ',\n  "private": true,\n  "version": "0.1.0",\n  "type": "module",\n'
                         '  "scripts": { "dev": "vite", "build": "vite build" },\n'
                         '  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },\n'
                         '  "devDependencies": { "@vitejs/plugin-react": "^4.3.0", "vite": "^5.4.0" }\n}\n'),
        "vite.config.js": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\n\nexport default defineConfig({ plugins: [react()] });\n",
        "index.html": ('<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                       f'  <title>{h(s["site_name"])}</title>\n  <meta name="description" content="{h(s["description"])}">\n</head>\n'
                       '<body id="top">\n  <div id="root"></div>\n  <script type="module" src="/src/main.jsx"></script>\n</body>\n</html>\n'),
        "src/main.jsx": "import React from 'react';\nimport { createRoot } from 'react-dom/client';\nimport App from './App.jsx';\nimport './styles.css';\n\ncreateRoot(document.getElementById('root')).render(<App />);\n",
        "src/siteData.js": _site_data(s),
        "src/styles.css": _css(s["theme"]),
        "src/App.jsx": ("import { site } from './siteData.js';\nimport Navbar from './components/Navbar.jsx';\nimport Hero from './components/Hero.jsx';\n"
                        "import Section from './components/Section.jsx';\nimport ContactForm from './components/ContactForm.jsx';\n"
                        "import Footer from './components/Footer.jsx';\n\nexport default function App() {\n  return (\n    <>\n"
                        + _app_body() + "    </>\n  );\n}\n"),
    }
    for name, body in _components("").items():
        files[f"src/components/{name}"] = body
    _extras(s, files)
    return files


def _build_next(s: dict) -> dict[str, str]:
    slug = slugify(s["site_name"])
    files = {
        "package.json": ('{\n  "name": ' + js(slug) + ',\n  "private": true,\n  "version": "0.1.0",\n'
                         '  "scripts": { "dev": "next dev", "build": "next build", "start": "next start" },\n'
                         '  "dependencies": { "next": "^14.2.0", "react": "^18.3.1", "react-dom": "^18.3.1" }\n}\n'),
        "next.config.js": "/** @type {import('next').NextConfig} */\nmodule.exports = { reactStrictMode: true };\n",
        "lib/siteData.js": _site_data(s),
        "app/globals.css": _css(s["theme"]),
        "app/layout.js": ("import './globals.css';\nimport { site } from '../lib/siteData.js';\n\n"
                          "export const metadata = { title: site.name, description: site.description };\n\n"
                          "export default function RootLayout({ children }) {\n  return (\n    <html lang=\"en\">\n      <body id=\"top\">{children}</body>\n    </html>\n  );\n}\n"),
        "app/page.js": ("import { site } from '../lib/siteData.js';\nimport Navbar from '../components/Navbar.jsx';\nimport Hero from '../components/Hero.jsx';\n"
                        "import Section from '../components/Section.jsx';\nimport ContactForm from '../components/ContactForm.jsx';\n"
                        "import Footer from '../components/Footer.jsx';\n\nexport default function Home() {\n  return (\n    <>\n"
                        + _app_body() + "    </>\n  );\n}\n"),
    }
    for name, body in _components("'use client';\n\n").items():
        if name in ("Hero.jsx", "Section.jsx", "Footer.jsx"):
            body = body  # server components
        files[f"components/{name}"] = body
    _extras(s, files)
    return files


def build(s: dict) -> dict[str, str]:
    return {"html": _build_html, "react": _build_react, "nextjs": _build_next}[s["framework"]](s)


COMPOSERS = [Composer("website", "1.0.0", "website", "Responsive website (HTML / React / Next.js)", normalize, build)]
