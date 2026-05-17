"""
Run ConformU's `alpacaprotocol` test against this Alpaca server.

What it does:
  - Starts main.py in a subprocess (or attaches to a running server).
  - Waits for /management/v1/configureddevices to respond.
  - For each configured device, invokes the ConformU CLI.
  - Parses the log for the errors / issues / information summary.
  - Prints a one-page report.
  - Updates README.md between <!-- conformu:start --> and
    <!-- conformu:end --> markers with the latest counts.

Usage:
    python test_conformu.py [--host HOST] [--port PORT]

The conformu binary is located via $PATH or these fallbacks:
  - /Applications/ConformU.app/Contents/Resources/conformu  (macOS .app)
  - /usr/local/bin/conformu                                 (Linux/install)

Pass criterion: `issues == 0`. `errors` may be non-zero on hosts without
real hardware attached (e.g. NotConnectedException) and is reported but
not counted against pass.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml


# Some repos define custom YAML tags (e.g. `!env`) on top of the safe loader.
# We only need a couple of scalar values from config.yaml, so treat any
# unknown tag as a passthrough rather than crashing on first encounter.
def _yaml_passthrough(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


yaml.SafeLoader.add_multi_constructor("!", _yaml_passthrough)


REPO = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO / "config.yaml"
README_PATH = REPO / "README.md"

CONFORMU_CANDIDATES = [
    "/Applications/ConformU.app/Contents/Resources/conformu",
    "/usr/local/bin/conformu",
    "/opt/conformu/conformu",
]

# ASCOM device-type names → Alpaca URL path segment
DEVICE_TYPE_TO_URL = {
    "Filter Wheel": "filterwheel",
    "Camera": "camera",
    "Focuser": "focuser",
    "Dome": "dome",
    "Telescope": "telescope",
    "Rotator": "rotator",
    "Switch": "switch",
    "CoverCalibrator": "covercalibrator",
    "SafetyMonitor": "safetymonitor",
    "ObservingConditions": "observingconditions",
}

SUMMARY_RE = re.compile(
    r"Found (?P<errors>\d+) errors?, (?P<issues>\d+) issues? "
    r"and (?P<info>\d+) information"
)
VERSION_RE = re.compile(r"Conform Universal (?P<v>[\d.]+(?:\s*\([^)]+\))?)")


def find_conformu() -> str:
    if path := shutil.which("conformu"):
        return path
    for cand in CONFORMU_CANDIDATES:
        if Path(cand).exists():
            return cand
    sys.exit("conformu binary not found; install ConformU or add it to PATH.")


def conformu_version(binary: str) -> str:
    out = subprocess.run([binary, "--version"], capture_output=True, text=True)
    m = VERSION_RE.search(out.stdout + out.stderr)
    return m.group("v").strip() if m else "unknown"


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) == 0


def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    url = f"http://{host}:{port}/management/v1/configureddevices"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def configured_devices(host: str, port: int) -> list:
    url = f"http://{host}:{port}/management/v1/configureddevices"
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())["Value"]


def run_one(binary: str, url: str, logfile: Path) -> dict:
    subprocess.run(
        [binary, "alpacaprotocol", url, "-n", str(logfile)],
        capture_output=True, text=True,
    )
    text = logfile.read_text(errors="replace")
    m = SUMMARY_RE.search(text)
    if not m:
        return {"errors": -1, "issues": -1, "info": -1, "raw_tail": text[-500:]}
    return {
        "errors": int(m.group("errors")),
        "issues": int(m.group("issues")),
        "info": int(m.group("info")),
    }


def render_readme_section(version: str, results: list) -> str:
    today = datetime.date.today().isoformat()
    rows = []
    for r in results:
        status = "✓ PASS" if r["issues"] == 0 else "✗ FAIL"
        rows.append(
            f"| {r['label']} | {r['errors']} | {r['issues']} | "
            f"{r['info']} | {status} |"
        )
    return "\n".join([
        "<!-- conformu:start -->",
        f"Last tested with **ConformU {version}** on {today}",
        f"(`python test_conformu.py`):",
        "",
        "| Device | Errors | Issues | Info | Status |",
        "|--------|:------:|:------:|:----:|:------:|",
        *rows,
        "",
        "_Errors may be non-zero when no hardware is attached "
        "(NotConnectedException is the expected response). "
        "**Issues == 0** indicates Alpaca protocol conformance._",
        "<!-- conformu:end -->",
    ])


def update_readme(version: str, results: list) -> None:
    if not README_PATH.exists():
        return
    text = README_PATH.read_text()
    section = render_readme_section(version, results)
    marker_re = re.compile(
        r"<!-- conformu:start -->.*?<!-- conformu:end -->",
        re.DOTALL,
    )
    if marker_re.search(text):
        new_text = marker_re.sub(section, text)
    else:
        new_text = (
            text.rstrip()
            + "\n\n---\n\n## ASCOM Conformance\n\n"
            + section
            + "\n"
        )
    README_PATH.write_text(new_text)
    print(f"  → updated {README_PATH.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--no-readme", action="store_true",
        help="Skip updating README.md with the result table",
    )
    args = parser.parse_args()

    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    port = args.port or cfg.get("server", {}).get("port", 5000)

    binary = find_conformu()
    version = conformu_version(binary)

    print(f"ConformU {version}")
    print(f"Server:  http://{args.host}:{port}")
    print()

    # Start server if not already up
    server_proc = None
    if not port_in_use(args.host, port):
        # If config.yaml references env vars via `!env NAME`, supply a
        # dummy value for any that are unset — the conformance test
        # doesn't need real hardware credentials.
        env = os.environ.copy()
        raw_cfg = CONFIG_PATH.read_text() if CONFIG_PATH.exists() else ""
        for match in re.finditer(r"!env\s+(\w+)", raw_cfg):
            name = match.group(1)
            if name not in env:
                env[name] = "test_conformu_placeholder"
        print("Starting server (main.py)...")
        server_log = open("/tmp/test_conformu_server.log", "w")
        server_proc = subprocess.Popen(
            [sys.executable, str(REPO / "src" / "main.py")],
            cwd=REPO, env=env, stdout=server_log, stderr=subprocess.STDOUT,
        )
        if not wait_for_server(args.host, port):
            server_proc.terminate()
            sys.exit("Server failed to start within 10s")
        print("  ready.")
    else:
        print("Using already-running server on that port.")

    try:
        devices = configured_devices(args.host, port)
        if not devices:
            sys.exit("No configured devices reported by /management/v1/configureddevices")

        log_dir = Path(os.environ.get("CONFORMU_LOG_DIR", "/tmp"))
        log_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for d in devices:
            dev_type = d["DeviceType"]
            dev_num = d["DeviceNumber"]
            dev_name = d["DeviceName"]
            url_seg = DEVICE_TYPE_TO_URL.get(dev_type)
            if not url_seg:
                url_seg = dev_type.lower().replace(" ", "")
            url = f"http://{args.host}:{port}/api/v1/{url_seg}/{dev_num}"
            label = f"{dev_name} ({dev_type} #{dev_num})"
            stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
            logfile = log_dir / f"conformu_{url_seg}_{dev_num}_{stamp}.log"

            print(f"Testing {label}")
            print(f"  URL:  {url}")
            print(f"  log:  {logfile}")
            r = run_one(binary, url, logfile)
            r.update(label=label, logfile=str(logfile))
            results.append(r)

            status = "✓ PASS" if r["issues"] == 0 else "✗ FAIL"
            print(
                f"  errors: {r['errors']:>3}   "
                f"issues: {r['issues']:>3}   "
                f"info: {r['info']:>3}   {status}"
            )
            print()
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()

    overall_pass = all(r["issues"] == 0 for r in results)

    print("=" * 56)
    print(f"Overall: {'✓ PASS' if overall_pass else '✗ FAIL'} "
          f"({sum(r['issues'] for r in results)} total issues)")
    print("=" * 56)

    if not args.no_readme:
        update_readme(version, results)

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
