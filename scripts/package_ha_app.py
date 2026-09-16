"""Produce a reviewable HA OS local-app build context. Downloads nothing."""

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-image", required=True,
                        help="docker.io/library/python:3.X.Y-slim-bookworm@sha256:<64 hex>")
    parser.add_argument("--output", default="deploy/ha-app/build/kebnekaise")
    args = parser.parse_args()
    if not re.fullmatch(r"docker\.io/library/python:3\.(?:11|12|13|14)\.\d+-slim-(?:bookworm|trixie)@sha256:[a-f0-9]{64}", args.python_image):
        parser.error("Ange en exakt version och verifierad SHA-256 från Docker Official Image python")
    target = Path(args.output)
    if target.exists():
        parser.error("Målkatalogen finns redan; välj en ny katalog för den nya versionen")
    target.mkdir(parents=True)
    shutil.copytree(ROOT / "kebnekaise", target / "kebnekaise", ignore=shutil.ignore_patterns("__pycache__"))
    (target / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/daily_backup.py", target / "scripts/daily_backup.py")
    for name in ("config.json", "runner.py"):
        shutil.copy2(ROOT / "deploy/ha-app" / name, target / name)
    template = (ROOT / "deploy/ha-app/Dockerfile.template").read_text()
    (target / "Dockerfile").write_text(template.replace("@@PYTHON_IMAGE@@", args.python_image))
    print(f"Byggkontext skapad: {target}. Ingen image hämtad, byggd eller installerad.")


if __name__ == "__main__":
    main()
