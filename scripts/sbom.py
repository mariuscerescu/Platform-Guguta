#!/usr/bin/env python3
"""SBOM generation + vulnerability scanning for the Guguță stack (R05, R42).

Usage:
    uv run python scripts/sbom.py

Generates:
- SBOM (CycloneDX JSON) for the Python runtime
- pip-audit vulnerability scan
- npm audit for the frontend (if node_modules exist)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, cwd: str | Path = ROOT) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    print(r.stdout[-2000:] if r.stdout else "(no stdout)")
    if r.returncode != 0:
        print(f"  exit code: {r.returncode}")
    return r


def main() -> None:
    print("=== SBOM + Vulnerability scan ===\n")

    # 1. CycloneDX SBOM for Python packages
    print("--- 1. CycloneDX SBOM ---")
    r = _run([
        sys.executable, "-m", "pip", "install", "--quiet",
        "cyclonedx-bom>=4,<5",
    ])
    r = _run([
        sys.executable, "-m", "cyclonedx_py", "requirements",
        str(ROOT / "uv.lock"), "--format", "json",
        "--output", str(ROOT / "sbom-cyclonedx.json"),
    ])
    if (ROOT / "sbom-cyclonedx.json").exists():
        print("  SBOM written: sbom-cyclonedx.json")
    else:
        # fallback: simple JSON list of installed packages
        r = _run([sys.executable, "-m", "pip", "list", "--format=json"])
        packages = json.loads(r.stdout) if r.stdout else []
        sbom = {"components": [{"name": p["name"], "version": p["version"]} for p in packages]}
        (ROOT / "sbom-cyclonedx.json").write_text(json.dumps(sbom, indent=2))
        print(f"  SBOM (simple): {len(packages)} packages")

    # 2. pip-audit
    print("\n--- 2. pip-audit (Python vulnerability scan) ---")
    r = _run([sys.executable, "-m", "pip_audit", "--desc"])
    if r.returncode != 0 and "No known vulnerabilities" not in (r.stdout or ""):
        print("  !! VULNERABILITIES FOUND — review output above")

    # 3. npm audit (frontend)
    fe = ROOT / "frontend-guguta"
    if (fe / "node_modules").exists():
        print("\n--- 3. npm audit (frontend) ---")
        r = _run(["npm", "audit", "--json"], cwd=str(fe))
        if r.stdout:
            try:
                audit = json.loads(r.stdout)
                vulns = audit.get("metadata", {}).get("vulnerabilities", {})
                total = vulns.get("total", 0)
                print(f"  npm audit: {total} vulnerabilities")
            except json.JSONDecodeError:
                print("  (npm audit output not JSON)")
    else:
        print("\n--- 3. npm audit: SKIPPED (no node_modules) ---")

    print("\n=== SBOM + scan complete ===")


if __name__ == "__main__":
    main()
