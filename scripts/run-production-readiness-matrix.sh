#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WORKSPACE="workspace"
OUT=""
INSPECT_EXISTING=0
RUN_MODE=0
PDF_SPECS=()
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/run-production-readiness-matrix.sh --inspect-existing [--workspace workspace] [--out path.json]
  bash scripts/run-production-readiness-matrix.sh --run --pdf ticket:basename:path[:source_kind] [--pdf ...] [--workspace workspace] [--out path.json]

Artifact-inspection mode is read-only. Optional run mode invokes the orchestrator
only for explicitly listed PDFs that already exist at the orchestrator expected
workspace/input/<ticket>/<basename>.pdf path.
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

ARGS=("--workspace" "$WORKSPACE")
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
