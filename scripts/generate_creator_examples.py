"""Generate the example projects under examples/creator/ with the Creator Engine.

Nothing generated is executed. Existing example directories are never overwritten."""

import io
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from jarvis.creator.engine import CreatorEngine  # noqa: E402

EXAMPLES = {
    "example-website": 'create a website called "Sunrise Bakery" with a menu, an about page, a faq and a contact form',
    "example-python-app": 'create a python command line tool called "Log Scanner" that scans log files',
}


def extract_safely(data: bytes, dest: Path) -> int:
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            parts = info.filename.split("/")[1:]  # drop the project root folder
            if not parts or any(p in ("", ".", "..") for p in parts) or info.filename.startswith("/"):
                raise SystemExit(f"unsafe zip entry: {info.filename}")
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            n += 1
    return n


def main() -> int:
    out_root = REPO / "examples" / "creator"
    with tempfile.TemporaryDirectory() as tmp:
        engine = CreatorEngine(Path(tmp))
        for name, request in EXAMPLES.items():
            dest = out_root / name
            if dest.exists():
                print(f"skip {name}: already exists (never overwritten)")
                continue
            res = engine.create(request)
            if res.status != "delivered":
                print(f"FAILED {name}: {res.status} {res.error or res.message}")
                return 1
            zip_name = engine.ws.list_artifacts(res.project_id, "deliveries")[0]
            count = extract_safely(engine.ws.read_artifact(res.project_id, "deliveries", zip_name), dest)
            print(f"{name}: {res.status}, {count} files, runtime_verified={res.runtime_verified}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
