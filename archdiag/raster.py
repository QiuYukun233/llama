"""Best-effort SVG → PNG using whatever is installed (cairosvg, rsvg-convert, chromium, soffice)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile


def svg_to_png(svg: str, out_path: str, scale: float = 2.0) -> None:
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=out_path, scale=scale)
        return
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as td:
        svg_path = os.path.join(td, "d.svg")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-z", str(scale), "-o", out_path, svg_path], check=True)
            return
        chrome = next((c for c in (
            os.environ.get("ARCHDIAG_CHROME"), shutil.which("chromium"), shutil.which("chromium-browser"),
            shutil.which("google-chrome"), shutil.which("headless_shell"),
            "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
        ) if c and os.path.exists(c)), None)
        if chrome:
            import re
            m = re.search(r'width="(\d+)" height="(\d+)"', svg)
            w, h = (int(m.group(1)), int(m.group(2))) if m else (1200, 800)
            subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                            f"--force-device-scale-factor={scale}", f"--window-size={w},{h}",
                            f"--screenshot={os.path.abspath(out_path)}", "file://" + svg_path],
                           check=True, capture_output=True)
            return
        if shutil.which("soffice"):
            subprocess.run(["soffice", "--headless", "--convert-to", "png", "--outdir", td, svg_path],
                           check=True, capture_output=True)
            shutil.move(os.path.join(td, "d.png"), out_path)
            return
    raise RuntimeError("无法生成 PNG：请安装 cairosvg（pip install cairosvg）或 rsvg-convert / chromium / libreoffice")
