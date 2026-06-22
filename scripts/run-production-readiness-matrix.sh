#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WORKSPACE="workspace"
OUT=""
INSPECT_EXISTING=0
RUN_MODE=0
PROFILE="all"
MANIFEST=""
PDF_SPECS=()
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/run-production-readiness-matrix.sh --inspect-existing [--profile all|production|fixtures|historical|actionable] [--manifest path.json] [--workspace workspace] [--out path.json]
  bash scripts/run-production-readiness-matrix.sh --run --pdf ticket:basename:path[:source_kind] [--pdf ...] [--profile all|production|fixtures|historical|actionable] [--manifest path.json] [--workspace workspace] [--out path.json]

Artifact-inspection mode is read-only. Optional run mode invokes the orchestrator
only for explicitly listed PDFs that already exist at the orchestrator expected
workspace/input/<ticket>/<basename>.pdf path.

Profiles:
  all         all classified rows that are not otherwise filtered by the selected profile
  production representative/private local PDFs intended to count toward production readiness
  fixtures   controlled or synthetic fixtures such as WEBUI-E2E rows
  historical development probes, TEST/SMOKE/PROBE rows, timestamped reruns, stale/incomplete rows
  actionable production rows with blocking classifications or recurring blocker evidence
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --inspect-existing)
      INSPECT_EXISTING=1
      shift
      ;;
    --run)
      RUN_MODE=1
      shift
      ;;
    --pdf)
      [[ $# -ge 2 ]] || { echo "ERROR: --pdf requires ticket:basename:path[:source_kind]" >&2; exit 2; }
      PDF_SPECS+=("$2")
      shift 2
      ;;
    --workspace)
      [[ $# -ge 2 ]] || { echo "ERROR: --workspace requires a path" >&2; exit 2; }
      WORKSPACE="$2"
      shift 2
      ;;
    --profile)
      [[ $# -ge 2 ]] || { echo "ERROR: --profile requires all|production|fixtures|historical|actionable" >&2; exit 2; }
      PROFILE="$2"
      shift 2
      ;;
    --manifest)
      [[ $# -ge 2 ]] || { echo "ERROR: --manifest requires a path" >&2; exit 2; }
      MANIFEST="$2"
      shift 2
      ;;
    --out)
      [[ $# -ge 2 ]] || { echo "ERROR: --out requires a path" >&2; exit 2; }
      OUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$PROFILE" in
  all|production|fixtures|historical|actionable) ;;
  *) echo "ERROR: unknown --profile: $PROFILE" >&2; usage >&2; exit 2 ;;
esac

ARGS=("--workspace" "$WORKSPACE" "--profile" "$PROFILE")
if [[ -n "$MANIFEST" ]]; then
  ARGS+=("--manifest" "$MANIFEST")
fi
if [[ "$INSPECT_EXISTING" == "1" || "$RUN_MODE" == "0" ]]; then
  ARGS+=("--inspect-existing")
fi
if [[ "$RUN_MODE" == "1" ]]; then
  if [[ ${#PDF_SPECS[@]} -eq 0 ]]; then
    echo "ERROR: --run requires at least one --pdf ticket:basename:path[:source_kind]" >&2
    exit 2
  fi
  for spec in "${PDF_SPECS[@]}"; do
    ARGS+=("--pdf" "$spec")
  done
fi
if [[ -n "$OUT" ]]; then
  ARGS+=("--out" "$OUT")
fi

PYTHONPATH=app "$PYTHON_BIN" app/tools/audit/production_readiness_matrix.py "${ARGS[@]}"
