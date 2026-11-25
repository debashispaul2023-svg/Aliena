from pathlib import Path
def test_files_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'frontend' / 'index.html').exists()
