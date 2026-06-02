#!/usr/bin/env python3
"""M1 Acceptance Smoke Tests"""
import json, sys, os, shutil, subprocess, tempfile
from pathlib import Path

TEST_FILE = Path(__file__).resolve()
TOOLS_DIR = TEST_FILE.parents[1]   # app/tools
APP_DIR = TOOLS_DIR.parent          # app

def run_writer(job_dir, out="STATUS.json"):
    r = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "packaging/status_json_writer.py"),
         str(job_dir), "--out", out],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(APP_DIR)},
    )
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else {}, r.stderr

def run_packager(job_dir, remediated_pdf, output_dir, source_pdf=None, skip_pdf=False):
    cmd = [sys.executable, str(TOOLS_DIR / "packaging/package_deliverables.py"),
           str(job_dir), str(remediated_pdf),
           "--output-dir", str(output_dir)]
    if source_pdf:
        cmd += ["--source-pdf", str(source_pdf)]
    if skip_pdf:
        cmd += ["--skip-pdf"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(APP_DIR)})
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else {}, r.stderr

passed, failed = 0, []

def check(name, condition, detail=""):
    global passed
    if condition:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name} {detail}")

print("\n=== T1: stale STATUS.json cannot override FAIL ===")
d = Path(tempfile.mkdtemp(prefix="m1_t1_"))
(d / "audit").mkdir()
(d / "STATUS.json").write_text(json.dumps({"overall_result": "PASS", "gates": {}}))
(d / "audit/orchestrator_outcome.json").write_text(
    json.dumps({"overall_result": "FAIL", "critical_fails": ["verapdf_pdfua1"],
                "total_iterations": 5, "has_hermes": False}))
pdf = d / "remediated.pdf"
pdf.write_bytes(b"%PDF-1.4\n")
out = Path(tempfile.mkdtemp(prefix="m1_t1_out_"))
rc, pkg_out, _ = run_packager(d, pdf, out, skip_pdf=True)
check("packager exits 0 with --skip-pdf", rc == 0, f"got {rc}")
check("overall_result is FAIL", pkg_out.get("overall_result") == "FAIL",
      f"got {pkg_out.get('overall_result')}")
check("AUDIT_REPORT.md written", (out / f"{pdf.stem}_AUDIT_REPORT.md").exists())
shutil.rmtree(d); shutil.rmtree(out)

print("\n=== T2: REVIEW_REQUIRED overrides stale PASS ===")
d = Path(tempfile.mkdtemp(prefix="m1_t2_"))
(d / "audit").mkdir()
(d / "STATUS.json").write_text(json.dumps({"overall_result": "PASS", "gates": {}}))
(d / "audit/orchestrator_outcome.json").write_text(
    json.dumps({"overall_result": "REVIEW_REQUIRED", "critical_fails": [],
                "total_iterations": 3, "has_hermes": True}))
pdf = d / "remediated.pdf"
pdf.write_bytes(b"%PDF-1.4\n")
out = Path(tempfile.mkdtemp(prefix="m1_t2_out_"))
rc, pkg_out, _ = run_packager(d, pdf, out)
check("packager exits 0", rc == 0, f"got {rc}")
check("overall_result is REVIEW_REQUIRED",
      pkg_out.get("overall_result") == "REVIEW_REQUIRED",
      f"got {pkg_out.get('overall_result')}")
check("remediated PDF IS copied (REVIEW passes through)",
      (out / f"{pdf.stem}_remediated.pdf").exists())
shutil.rmtree(d); shutil.rmtree(out)

print("\n=== T3: absent orchestrator_outcome falls back to STATUS.json ===")
d = Path(tempfile.mkdtemp(prefix="m1_t3_"))
(d / "audit").mkdir()
(d / "STATUS.json").write_text(json.dumps({"overall_result": "FAIL", "gates": {}}))
pdf = d / "remediated.pdf"
pdf.write_bytes(b"%PDF-1.4\n")
out = Path(tempfile.mkdtemp(prefix="m1_t3_out_"))
rc, pkg_out, _ = run_packager(d, pdf, out, skip_pdf=True)
check("packager exits 0", rc == 0, f"got {rc}")
check("overall_result is FAIL via STATUS.json fallback",
      pkg_out.get("overall_result") == "FAIL",
      f"got {pkg_out.get('overall_result')}")
shutil.rmtree(d); shutil.rmtree(out)

print("\n=== T4: agreeing inputs produce clean STATUS.json ===")
d = Path(tempfile.mkdtemp(prefix="m1_t4_"))
(d / "audit").mkdir()
(d / "STATUS.json").write_text(json.dumps({"overall_result": "PASS", "gates": {}}))
(d / "audit/orchestrator_outcome.json").write_text(
    json.dumps({"overall_result": "PASS", "critical_fails": [],
                "total_iterations": 2, "has_hermes": False}))
(d / "audit/verdict_input.json").write_text(
    json.dumps({"gates": {
        "verapdf_pdfua1": {"result": "PASS", "source": "orchestrator"},
        "metadata_parity": {"result": "PASS", "source": "orchestrator"},
    }, "hermes_signals_count": 0, "deviations_count": 0,
       "total_iterations": 2, "job_hard_cap": 50,
       "experimental_profile_failures": []}))
rc, status_out, stderr = run_writer(d)
check("writer exits 0 for PASS", rc == 0, f"rc={rc} stderr={stderr[:200]}")
check("STATUS.json overall_result is PASS",
      status_out.get("overall_result") == "PASS",
      f"got {status_out.get('overall_result')}")
check("no verdict_mismatch flag",
      "verdict_mismatch" not in status_out,
      f"flags={[k for k in status_out if 'mismatch' in k.lower()]}")
shutil.rmtree(d)

print("\n=== T5: disagreeing inputs produce verdict_mismatch flag ===")
d = Path(tempfile.mkdtemp(prefix="m1_t5_"))
(d / "audit").mkdir()
(d / "STATUS.json").write_text(json.dumps({"overall_result": "PASS", "gates": {}}))
(d / "audit/orchestrator_outcome.json").write_text(
    json.dumps({"overall_result": "FAIL", "critical_fails": ["verapdf_pdfua1"],
                "total_iterations": 3, "has_hermes": False}))
(d / "audit/verdict_input.json").write_text(
    json.dumps({"gates": {
        "verapdf_pdfua1": {"result": "PASS", "source": "orchestrator"},
    }, "hermes_signals_count": 0, "deviations_count": 0,
       "total_iterations": 3, "job_hard_cap": 50,
       "experimental_profile_failures": []}))
rc, status_out, stderr = run_writer(d)
check("writer uses orchestrator FAIL not verdict_input PASS",
      status_out.get("overall_result") == "FAIL",
      f"got {status_out.get('overall_result')}")
check("verdict_mismatch flag recorded",
      "verdict_mismatch" in status_out,
      f"keys={list(status_out.keys())}")
shutil.rmtree(d)

print("\n=== T6: informational profile failure does not hard-fail ===")
from tools.lib.verdict import VerdictInput as VI, verdict as vfunc
from tools.lib.verdict import GateResult
from tools.lib.gates import GateName

vi = VI(
    gates={
        GateName.verapdf_pdfua1: GateResult(GateName.verapdf_pdfua1, "PASS", "test"),
        GateName.verapdf_wcag:   GateResult(GateName.verapdf_wcag,   "PASS", "test"),
    },
    hermes_signals_count=0, deviations_count=0,
    total_iterations=1, job_hard_cap=50,
    experimental_profile_failures=["verapdf_iso"],
)
res = vfunc(vi)
check("overall is REVIEW_REQUIRED (ISO flagged but not hard-FAIL)",
      res.overall == "REVIEW_REQUIRED", f"got {res.overall}")
check("ISO is informational_flags not critical_fails",
      GateName.verapdf_iso in res.informational_flags,
      f"flags={[str(g) for g in res.informational_flags]}")
check("critical_fails empty", len(res.critical_fails) == 0,
      f"critical={[str(g) for g in res.critical_fails]}")

print("\n=== T7: legacy gate names canonicalise cleanly ===")
from tools.lib.gates import canonicalize_gate_key
legacy_tests = [
    ("verapdf_pdfua", "verapdf_pdfua1"),
    ("verapdf_post", "verapdf_pdfua1"),
    ("metadata_post", "metadata_parity"),
    ("metadata_parity_final", "metadata_parity"),
    ("verapdf_pdfua1", "verapdf_pdfua1"),
    ("parse_summary", "parse_summary"),
]
all_legacy_ok = True
for raw, expected in legacy_tests:
    try:
        got = canonicalize_gate_key(raw)
        if got != expected:
            print(f"  FAIL canonicalize({raw!r}) -> {got}, expected {expected}")
            all_legacy_ok = False
    except KeyError as e:
        print(f"  FAIL canonicalize({raw!r}) raised KeyError: {e}")
        all_legacy_ok = False
if all_legacy_ok:
    print("  PASS all legacy aliases map correctly")
    passed += 1
else:
    failed.append("legacy_name_canonicalisation")

# T8: final compile check on all four touched files
print("\n=== T8: all touched files compile cleanly ===")
import py_compile
files = [
    str(TOOLS_DIR / 'lib/__init__.py'),
    str(TOOLS_DIR / 'lib/gates.py'),
    str(TOOLS_DIR / 'lib/verdict.py'),
    str(TOOLS_DIR / 'packaging/status_json_writer.py'),
    str(TOOLS_DIR / 'packaging/package_deliverables.py'),
    str(TOOLS_DIR / 'packaging/package_scaffold.py'),
]
all_compile_ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"  FAIL compile {f}: {e}")
        all_compile_ok = False
if all_compile_ok:
    print("  PASS all files compile")
    passed += 1
else:
    failed.append("compile_check")

# Summary
print(f"\n=== Summary: {passed} passed, {len(failed)} failed ===")
for f in failed:
    print(f"  FAILED: {f}")
sys.exit(1 if failed else 0)
