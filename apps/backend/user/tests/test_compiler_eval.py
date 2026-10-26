"""Keeps the compiler eval runnable (it measures accuracy; this only checks it runs).

Runs the script in its own process: it builds its own throwaway database and
must not share this test session's engine.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "evals" / "run_compiler_eval.py"
CASES = Path(__file__).resolve().parents[1] / "evals" / "cases.jsonl"
CATALOG = Path(__file__).resolve().parents[1] / "evals" / "catalog.json"


def test_eval_files_are_consistent():
    servers = {s["name"]: {t["name"] for t in s["tools"]} for s in json.loads(CATALOG.read_text())["servers"]}
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        for exp in ([c["expect"]] if c.get("expect") else []) + c.get("also_ok", []):
            assert exp["tool"] in servers[exp["server"]], c["id"]


def test_eval_runs_and_reports(tmp_path):
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--limit", "4", "--no-embeddings", "--json", str(out)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    report = json.loads(out.read_text())
    assert report["retrieval_mode"].startswith("lexical")
    assert report["overall"]["cases"] == 4
    assert 0 <= report["overall"]["hit@1"] <= 1
