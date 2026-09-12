from __future__ import annotations

import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys


def package_license(package: str, destination: Path) -> None:
    distribution = importlib.metadata.distribution(package)
    files = [file for file in distribution.files or () if Path(str(file)).name.lower() in {"license", "license.txt", "copying.txt"}]
    if not files:
        raise RuntimeError(f"License file not found for {package}")
    source = Path(distribution.locate_file(files[0]))
    shutil.copy2(source, destination / f"{package}-{distribution.version}-LICENSE{source.suffix}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: collect_licenses.py DESTINATION FFMPEG_EXE")
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=True)
    for package in ("numpy", "tkinterdnd2", "pyinstaller"):
        package_license(package, destination)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, destination / f"Python-{sys.version_info.major}.{sys.version_info.minor}-LICENSE.txt")
    tcl_license = Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"
    if tcl_license.exists():
        shutil.copy2(tcl_license, destination / "Tcl-Tk-license.terms")
    ffmpeg = subprocess.run([sys.argv[2], "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    (destination / "FFmpeg-build-information.txt").write_text(ffmpeg.stdout, encoding="utf-8")


if __name__ == "__main__":
    main()
