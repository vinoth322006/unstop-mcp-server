"""Build every release artifact into dist/release/.

    python packaging/build_release.py            # everything this OS can build
    python packaging/build_release.py --skip-exe # wheel + sdist only

Produces:
  unstop_mcp-<v>-py3-none-any.whl, unstop_mcp-<v>.tar.gz   pip / pipx / uv
  unstop-mcp-<v>-windows-x64.exe                           standalone, no Python needed   (Windows)
  unstop-mcp-<v>.mcpb                                      Claude Desktop one-click extension (Windows)
  SHA256SUMS.txt
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
OUT = ROOT / "dist" / "release"
WORK = ROOT / "build" / "release"
MCPB_CLI = "@anthropic-ai/mcpb@2.1.2"


def run(cmd: list[str], **kw: object) -> None:
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)  # noqa: S603


def version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from unstop_mcp import __version__

    return __version__


def build_python() -> None:
    print("[1/4] wheel + sdist")
    run([sys.executable, "-m", "build", "--outdir", str(OUT)])


def pyinstaller(onefile: bool, name: str, dist: Path) -> Path:
    args = [
        sys.executable, "-m", "PyInstaller", str(PKG / "entry.py"),
        "--name", name, "--console", "--noconfirm", "--clean",
        "--icon", str(PKG / "icon.ico"),
        "--distpath", str(dist), "--workpath", str(WORK / f"pyi-{name}"), "--specpath", str(WORK),
        "--collect-submodules", "unstop_mcp", "--collect-submodules", "mcp", "--collect-submodules", "uvicorn",
        "--copy-metadata", "mcp", "--copy-metadata", "httpx", "--copy-metadata", "pydantic",
        "--exclude-module", "tkinter", "--exclude-module", "pytest",
        "--onefile" if onefile else "--onedir",
    ]
    run(args)
    return dist / (f"{name}.exe" if onefile else name)


def tool_listing() -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    from unstop_mcp.config import Settings
    from unstop_mcp.server import build_runtime, build_server

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(data_dir=Path(tmp), _env_file=None)  # type: ignore[call-arg]
        rt = build_runtime(settings)
        mcp = build_server(settings, rt)
        tools = asyncio.run(mcp.list_tools())
        prompts = asyncio.run(mcp.list_prompts())
        asyncio.run(rt.http.aclose())
    first = lambda s: (s or "").strip().splitlines()[0].strip()  # noqa: E731
    return (
        [{"name": t.name, "description": first(t.description)} for t in tools],
        [{"name": p.name, "description": first(p.description),
          "arguments": [a.name for a in (p.arguments or [])],
          "text": f"Use the Unstop tools to help with: {p.title or p.name}."} for p in prompts],
    )


def build_windows(v: str) -> None:
    print("[2/4] standalone Windows executable")
    exe = pyinstaller(True, "unstop-mcp", WORK / "onefile")
    target = OUT / f"unstop-mcp-{v}-windows-x64.exe"
    shutil.copy2(exe, target)
    smoke(target)

    print("[3/4] Claude Desktop extension (.mcpb)")
    folder = pyinstaller(False, "unstop-mcp", WORK / "onedir")
    stage = WORK / "mcpb"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(folder, stage / "server")
    shutil.copy2(PKG / "icon.png", stage / "icon.png")
    tools, prompts = tool_listing()
    manifest = json.loads((PKG / "manifest.template.json").read_text(encoding="utf-8"))
    manifest["version"] = v
    manifest["tools"] = tools
    manifest["prompts"] = prompts
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("npx (Node.js) is required to validate and pack the .mcpb")
    run([npx, "-y", MCPB_CLI, "validate", str(stage / "manifest.json")])
    run([npx, "-y", MCPB_CLI, "pack", str(stage), str(OUT / f"unstop-mcp-{v}.mcpb")])


def smoke(exe: Path) -> None:
    out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=120, check=True)  # noqa: S603
    assert version() in out.stdout, out.stdout
    print(f"  smoke test ok: {out.stdout.strip()}")


def checksums() -> None:
    print("[4/4] checksums")
    lines = []
    for f in sorted(OUT.iterdir()):
        if f.is_file() and f.name != "SHA256SUMS.txt":
            lines.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    # LF endings on every OS so `sha256sum -c` works on macOS/Linux too.
    (OUT / "SHA256SUMS.txt").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    for line in lines:
        print("  " + line)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-exe", action="store_true")
    args = ap.parse_args()
    v = version()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    build_python()
    if sys.platform == "win32" and not args.skip_exe:
        build_windows(v)
    checksums()
    print(f"\nDone: {OUT}")


if __name__ == "__main__":
    main()
