#!/usr/bin/env python3
"""
remediate.py
Single-entry-point orchestrator for Montefiore PDF/UA remediation.

Replaces the agent's need to interpret AGENTS.md step-by-step. Handles:
  - Job scaffolding
  - Document tagging against doc_taxonomy.json
  - All pre-flight and audit gates
  - Repair plan generation (veraPDF + table semantics)
  - Iterative repair loop with per-rule and per-job caps
  - Strategy fallback and HERMES_REQUIRED signalling
  - Post-repair validation after each iteration
  - QA gates
  - Outcome-aware packaging (PASS/REVIEW_REQUIRED/FAIL/ESCALATION)
  - Knowledge update (post_job_indexer)

Iteration caps:
  PER_RULE_CAP  = 15   hard cap on strategy attempts per rule
  JOB_WARN_AT   = 20   soft warning logged to STATUS.json
  JOB_HARD_CAP  = 50   absolute safety net — force termination

The agent's role is reduced to:
  1. Call this script
  2. Handle HERMES_REQUIRED signals (write new scripts, register in rule map)
  3. Provide metadata args (--title, --subject, --keywords)

Signal layers:
  Layer 1 — execution signals (exit code, missing output, JSON parse failure)
  Layer 2 — outcome signals (rule still fails after mapped script ran)
  Layer 3 — semantic signals (plan wrong for this document, novel failures)
  HERMES_REQUIRED — agent must write or locate a repair script

Usage:
  remediate.py <workspace> <ticket> <source-pdf-basename>
    --title    "Document Title"
    --subject  "One sentence subject"
    --keywords "keyword1, keyword2, ..."
    [--language en-US]
    [--dry-run]     Print plan without executing

Exit codes:
  0  PASS or REVIEW_REQUIRED
  1  FAIL, ESCALATION, or unresolved DEVIATION
  2  usage/setup error
"""
import sys, json, subprocess, shutil, argparse, os
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from tools.audit.execution_log import build_execution_log_from_repair_steps, write_execution_log
from tools.audit.residual_analysis import analyze_residuals, targetable_failures_from_analysis
from tools.lib.residual_verdict import summarize_residual_analysis, summarize_strategy_indexing, reconcile_hermes_signals

# ── Args ──────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument('workspace')
parser.add_argument('ticket')
parser.add_argument('basename')
parser.add_argument('--title',    default='')
parser.add_argument('--subject',  default='')
parser.add_argument('--keywords', default='')
parser.add_argument('--language', default='en-US')
parser.add_argument('--dry-run',  action='store_true')
args = parser.parse_args()

WORKSPACE  = Path(args.workspace)
TICKET     = args.ticket
BASENAME   = Path(args.basename).stem
SAFE_BASE  = BASENAME.replace(' ', '_').replace('/', '_')
LANGUAGE   = args.language

APP        = Path('/app')
TOOLS      = APP / 'tools'
# Interpreter for all spawned audit/repair/QA/packaging scripts. The Hermes
# base image puts /opt/hermes/.venv first on PATH; that venv has pymupdf but
# NOT pikepdf/pdfplumber/ocrmypdf/etc (deliberately -- see Dockerfile note
# about not disturbing Hermes' pinned dependencies). A bare 'python3' child
# therefore resolves to an interpreter missing required modules whenever the
# orchestrator itself was launched from the venv. Pin the system interpreter,
# overridable for non-container/dev environments.
REMEDIATION_PYTHON = os.environ.get('REMEDIATION_PYTHON', '/usr/bin/python3')
VERAPDF_BIN = Path('/opt/verapdf-greenfield/verapdf')
DEFAULT_VERAPDF_PROFILES = Path(
    os.environ.get(
        'VERAPDF_PROFILE_PATH',
        os.environ.get(
            'VERAPDF_PROFILE_SOURCE',
            '/opt/veraPDF-validation-profiles-integration',
        ),
    )
)
LEGACY_WORKSPACE_PROFILES = (
    WORKSPACE / 'assets' / 'validation_profiles' /
    'veraPDF-validation-profiles-integration'
)
PROFILES = (
    DEFAULT_VERAPDF_PROFILES
    if DEFAULT_VERAPDF_PROFILES.exists()
    else LEGACY_WORKSPACE_PROFILES
)
RULE_MAP   = TOOLS / 'audit' / 'rule_repair_map.json'
TAXONOMY   = TOOLS / 'audit' / 'doc_taxonomy.json'

JOB_NAME   = f'{TICKET}_{SAFE_BASE}'
JOB_DIR    = WORKSPACE / 'jobs'   / JOB_NAME
OUTPUT_DIR = WORKSPACE / 'output' / f'{TICKET}_remediated'
SOURCE_PDF = WORKSPACE / 'input'  / TICKET / f'{BASENAME}.pdf'

# Iteration caps
PER_RULE_CAP = 15
JOB_WARN_AT  = 20
JOB_HARD_CAP = 50

# ── Helpers ───────────────────────────────────────────────────────────────────

deviations        = []
gate_results      = {}
hermes_signals  = []
strategy_attempts = defaultdict(list)  # rule_id -> list of attempt records
start_time        = datetime.now(timezone.utc)
total_iterations  = 0

def emit(phase, step, result, note=None, data=None):
    obj = {'phase': phase, 'step': step, 'result': result}
    if note:  obj['note'] = note
    if data:  obj['data'] = data
    print(json.dumps(obj), flush=True)

def emit_deviation(step, expected, actual, context, layer):
    dev = {
        'layer':     layer,
        'step':      step,
        'expected':  expected,
        'actual':    actual,
        'context':   context,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    deviations.append(dev)
    print(json.dumps({
        'phase':    'DEVIATION',
        'layer':    layer,
        'step':     step,
        'expected': expected,
        'actual':   actual,
        'context':  context
    }), flush=True)

def emit_hermes_required(rule_id, description, failures, reason, attempts=None, artifacts=None):
    signal = {
        'rule_id': rule_id,
        'description': description,
        'failures': failures,
        'reason': reason,
        'strategies_attempted': attempts or [],
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    if artifacts:
        signal['artifacts'] = artifacts
    hermes_signals.append(signal)
    print(json.dumps({
        'phase': 'HERMES_REQUIRED',
        'rule_id': rule_id,
        'reason': reason,
        'data': signal
    }), flush=True)

def run(cmd, label, capture=True, env=None):
    if args.dry_run:
        emit('DRY_RUN', label, 'SKIPPED', note=' '.join(str(c) for c in cmd))
        return 0, '{"result":"PASS"}', ''
    try:
        run_env = None
        if env:
            run_env = os.environ.copy()
            run_env.update({str(k): str(v) for k, v in env.items()})
        r = subprocess.run(
            [str(c) for c in cmd],
            capture_output=capture,
            text=True,
            env=run_env,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return 2, '', str(e)

def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None

def clean_metadata_text(value):
    return ' '.join(str(value or '').split()).strip()


def tesseract_lang(language):
    """Map the job --language (BCP-47-ish, e.g. en-US) to tesseract codes.
    The image ships tesseract-ocr-eng and tesseract-ocr-spa."""
    primary = (language or 'en').split('-')[0].strip().lower()
    return {'en': 'eng', 'es': 'spa'}.get(primary, 'eng')


def summarize_ocr_detector(data):
    """Return a flat summary of per-page char counts plus top-level gate fields."""
    pages = data.get("pages", []) if isinstance(data, dict) else []
    counts = [
        int(p.get("char_count", 0))
        for p in pages
        if isinstance(p, dict)
    ]
    return {
        "char_count_total": sum(counts),
        "char_count_min": min(counts) if counts else None,
        "char_count_max": max(counts) if counts else None,
        "image_only_pages": data.get("image_only_pages", [])
            if isinstance(data, dict) else [],
        "ocr_required": data.get("ocr_required")
            if isinstance(data, dict) else None,
        "result": data.get("result", "ERROR")
            if isinstance(data, dict) else "ERROR",
    }



def load_hermes_gateway_env():
    """Resolve Hermes gateway-facing config without selecting providers/models.

    The orchestrator calls Hermes/Open WebUI as a gateway. It must not choose
    provider API keys or concrete provider model names. Those belong to Hermes.

    Resolution order:
      1. Current process environment.
      2. /opt/data/.env, where Hermes gateway runtime config lives in-container.

    Only gateway-facing values are read here:
      - API_SERVER_KEY
      - API_SERVER_PORT
      - HERMES_GATEWAY_BASE_URL
      - API_SERVER_MODEL_NAME
    """
    allowed = {
        "API_SERVER_KEY",
        "API_SERVER_PORT",
        "HERMES_GATEWAY_BASE_URL",
        "API_SERVER_MODEL_NAME",
    }

    values = {key: os.environ.get(key, "") for key in allowed}

    env_path = Path("/opt/data/.env")
    if not env_path.exists():
        return values

    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()

            if key not in allowed:
                continue

            if values.get(key):
                continue

            values[key] = value.strip().strip('"').strip("'")
    except Exception as exc:
        emit(
            "SETUP",
            "hermes_gateway_env",
            "WARN",
            note=f"Unable to read /opt/data/.env: {type(exc).__name__}: {exc}",
        )

    return values


def strip_json_fence(content):
    content = (content or '').strip()
    if content.startswith('```'):
        parts = content.split('```')
        if len(parts) >= 2:
            content = parts[1].strip()
            if content.startswith('json'):
                content = content[4:].strip()
    return content


def extract_pdf_text_sample(pdf_path, limit=6000):
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        chunks = []
        total = 0
        for page in doc:
            page_text = page.get_text() or ''
            if page_text:
                chunks.append(page_text)
                total += len(page_text)
            if total >= limit:
                break
        doc.close()
        return clean_metadata_text('\n'.join(chunks))[:limit]
    except Exception:
        return ''


def call_hermes_metadata_generator(pdf_path):
    """Generate title/subject/keywords using the current Hermes gateway runtime."""
    import os
    import urllib.request

    text_sample = extract_pdf_text_sample(pdf_path)
    gateway_env = load_hermes_gateway_env()

    api_key = gateway_env.get("API_SERVER_KEY", "")
    port = gateway_env.get("API_SERVER_PORT") or "8642"
    base_url = (
        gateway_env.get("HERMES_GATEWAY_BASE_URL")
        or f"http://127.0.0.1:{port}/v1"
    ).rstrip("/")
    model = gateway_env.get("API_SERVER_MODEL_NAME") or "Hermes Agent"

    if not api_key:
        raise RuntimeError(
            "API_SERVER_KEY is not available from process env or /opt/data/.env "
            "for Hermes gateway metadata generation"
        )

    prompt = (
        'Generate PDF metadata for PDF/UA remediation. Return strict JSON only.\n\n'
        'Required JSON keys:\n'
        '- title: concise human-readable document title\n'
        '- subject: one clear sentence describing the document purpose\n'
        '- keywords: 4 to 8 comma-separated descriptive terms\n\n'
        'Rules:\n'
        '- Use the document text sample when available.\n'
        '- Use the filename/ticket only as supporting context, not as the sole basis unless no text is available.\n'
        '- Do not include unsupported claims.\n'
        '- Do not include author, creator, or producer. Those are enforced separately.\n'
        '- Return JSON only, no markdown and no prose.\n\n'
        f'Ticket: {TICKET}\n'
        f'Filename stem: {BASENAME}\n'
        f'Document text sample:\n{text_sample or "[no extractable text available]"}\n'
    )

    body = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.0,
        'max_tokens': 800,
        'stream': False,
    }).encode('utf-8')

    req = urllib.request.Request(
        base_url + '/chat/completions',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        response = json.loads(resp.read().decode('utf-8'))

    message = response['choices'][0]['message']
    raw_content = message.get('content') or message.get('reasoning_content') or ''
    parsed = json.loads(strip_json_fence(raw_content))

    title = clean_metadata_text(parsed.get('title', ''))
    subject = clean_metadata_text(parsed.get('subject', ''))
    keywords_raw = parsed.get('keywords', '')

    if isinstance(keywords_raw, list):
        keywords = ', '.join(
            clean_metadata_text(k) for k in keywords_raw if clean_metadata_text(k)
        )
    else:
        keywords = clean_metadata_text(keywords_raw)

    if not title:
        raise RuntimeError(f'Hermes metadata JSON missing title: {parsed}')
    if not subject:
        raise RuntimeError(f'Hermes metadata JSON missing subject: {parsed}')
    if not keywords:
        raise RuntimeError(f'Hermes metadata JSON missing keywords: {parsed}')

    return {
        'title': title,
        'subject': subject,
        'keywords': keywords,
        'source': 'hermes_gateway',
        'model': response.get('model', model),
        'base_url': base_url,
        'text_sample_chars': len(text_sample),
        'ticket': TICKET,
        'basename': BASENAME,
    }


def ensure_metadata_inputs_for_repair(pdf_path):
    """Return metadata inputs for fix_metadata_xmp_parity.py or raise.

    Explicit CLI args win. Otherwise Hermes generates metadata from the current
    working artifact. Failure is handled by the repair branch, not by setup exit.
    """
    explicit = {
        'title': clean_metadata_text(args.title),
        'subject': clean_metadata_text(args.subject),
        'keywords': clean_metadata_text(args.keywords),
    }

    if explicit['title'] and explicit['subject'] and explicit['keywords']:
        data = {
            **explicit,
            'source': 'cli_args',
            'ticket': TICKET,
            'basename': BASENAME,
        }
    else:
        data = call_hermes_metadata_generator(pdf_path)

    args.title = data['title']
    args.subject = data['subject']
    args.keywords = data['keywords']

    (AUDIT_DIR / 'metadata_inputs.json').write_text(json.dumps(data, indent=2))
    return data


def approved_alt_map_has_figures(path):
    """Return True only for a usable approved alt map with at least one figure."""
    data = load_json(path)
    if not isinstance(data, dict):
        return False
    figures = data.get('figures')
    return isinstance(figures, dict) and bool(figures)


def get_result(data):
    if data is None: return 'ERROR'
    return data.get('result', 'UNKNOWN')

def write_strategy_log(job):
    log_path = job / 'audit' / 'strategy_attempts.json'
    try:
        log_path.write_text(json.dumps({
            'attempts': {k: v for k, v in strategy_attempts.items()},
            'total_iterations': total_iterations
        }, indent=2))
    except Exception:
        pass

# ── Doc tagging ───────────────────────────────────────────────────────────────



def extract_relevant_verapdf_rule_xml(rule_ids, xml_paths, char_limit=24000):
    """Return compact veraPDF rule XML snippets for residual rules."""
    import xml.etree.ElementTree as ET

    clauses = {str(rule_id).split("/")[-1] for rule_id in rule_ids if rule_id}
    snippets = []
    used = 0

    def local_name(tag):
        return tag.split("}")[-1] if "}" in tag else tag

    for xml_path in xml_paths:
        path = Path(xml_path)
        if not path.exists():
            snippets.append({"source": str(path), "error": "file not found"})
            continue

        try:
            root = ET.parse(str(path)).getroot()
            for elem in root.iter():
                if local_name(elem.tag) != "rule":
                    continue

                clause = elem.get("clause", "")
                if clause not in clauses:
                    continue

                try:
                    failed = int(elem.get("failedChecks") or elem.get("deviations") or 0)
                except Exception:
                    failed = 0

                if failed <= 0:
                    continue

                xml_text = ET.tostring(elem, encoding="unicode")
                if len(xml_text) > 4000:
                    xml_text = xml_text[:4000] + "\n... [truncated]"

                item = {
                    "source": str(path),
                    "specification": elem.get("specification", ""),
                    "clause": clause,
                    "description": elem.get("description", ""),
                    "failed_checks": failed,
                    "xml": xml_text,
                }

                item_size = len(json.dumps(item))
                if used + item_size > char_limit:
                    snippets.append({
                        "source": str(path),
                        "note": "snippet limit reached; inspect full XML artifact",
                    })
                    return snippets

                snippets.append(item)
                used += item_size
        except Exception as exc:
            snippets.append({
                "source": str(path),
                "error": f"{type(exc).__name__}: {exc}",
            })

    return snippets


def list_existing_repair_scripts():
    """List deterministic repair scripts already present in tools/repair."""
    repair_dir = TOOLS / "repair"
    if not repair_dir.exists():
        return []

    scripts = []
    for script in sorted(repair_dir.glob("*.py")):
        try:
            rel = script.relative_to(APP)
        except Exception:
            rel = script
        scripts.append({
            "path": str(rel),
            "name": script.name,
        })
    return scripts


def build_strategy_gap_request(current_pdf, remaining_failures, post_failures_path, residual_plan):
    """Build a structured Hermes strategy-design request for residual failures."""
    rule_ids = [
        failure.get("rule_id", "")
        for failure in remaining_failures
        if failure.get("rule_id")
    ]

    rule_map_data = load_json(RULE_MAP) or {}
    rule_map_rules = rule_map_data.get("rules", {}) if isinstance(rule_map_data, dict) else {}
    rule_map_context = {
        rule_id: rule_map_rules.get(rule_id)
        for rule_id in rule_ids
        if rule_id in rule_map_rules
    }

    xml_paths = [
        AUDIT_DIR / "verapdf_post_pdfua1.xml",
        AUDIT_DIR / "verapdf_post_wcag.xml",
    ]

    return {
        "request_type": "pdfua_residual_strategy_design",
        "ticket": TICKET,
        "job_name": JOB_NAME,
        "job_dir": str(JOB),
        "workspace": str(WORKSPACE),
        "source_pdf": str(SOURCE_PDF),
        "current_pdf": str(current_pdf),
        "safe_to_package_success": False,
        "reason": "final_verapdf_residual_without_ready_remediation_path",
        "doc_tags": doc_tags,
        "residual_failures": remaining_failures,
        "residual_repair_plan": residual_plan,
        "validator_artifacts": {
            "failures_post": str(post_failures_path),
            "pdfua1_xml": str(AUDIT_DIR / "verapdf_post_pdfua1.xml"),
            "wcag_xml": str(AUDIT_DIR / "verapdf_post_wcag.xml"),
        },
        "validator_rule_xml_snippets": extract_relevant_verapdf_rule_xml(
            rule_ids,
            xml_paths,
        ),
        "rule_map_context": rule_map_context,
        "existing_repair_scripts": list_existing_repair_scripts(),
        "strategy_attempts": {
            rule_id: strategy_attempts.get(rule_id, [])
            for rule_id in rule_ids
        },
        "required_response_schema": {
            "result": (
                "USE_EXISTING_SCRIPT | PROPOSE_NEW_SCRIPT | "
                "NEEDS_MORE_EVIDENCE | NOT_AUTOMATABLE"
            ),
            "rule_id": "PDF/UA-1/...",
            "strategy": "stable_snake_case_strategy_name",
            "repair_script": "tools/repair/example.py or null",
            "preconditions": [],
            "pdf_edits": [],
            "validation_plan": [],
            "rule_map_update": {},
            "risks": [],
            "notes": "",
        },
    }


def call_hermes_strategy_designer(request_packet):
    """Ask Hermes gateway for a reusable deterministic strategy proposal.

    Disabled by default in orchestrator mainline. The orchestrator is normally
    run by Hermes/Open WebUI, so nested synchronous calls back into the same
    gateway can hang the active remediation chat. Strategy gaps should be
    written as artifacts and emitted as HERMES_REQUIRED for the outer agent.
    """
    import os
    if os.environ.get("HERMES_ALLOW_IN_PROCESS_STRATEGY_CALL", "") != "1":
        raise RuntimeError(
            "In-process Hermes strategy calls are disabled. Emit "
            "HERMES_REQUIRED with strategy request artifacts instead."
        )
    import urllib.request

    gateway_env = load_hermes_gateway_env()
    api_key = gateway_env.get("API_SERVER_KEY", "")
    port = gateway_env.get("API_SERVER_PORT") or "8642"
    base_url = (
        gateway_env.get("HERMES_GATEWAY_BASE_URL")
        or f"http://127.0.0.1:{port}/v1"
    ).rstrip("/")
    model = gateway_env.get("API_SERVER_MODEL_NAME") or "Hermes Agent"

    if not api_key:
        raise RuntimeError(
            "API_SERVER_KEY is not available from process env or /opt/data/.env "
            "for Hermes gateway strategy design"
        )

    prompt = (
        "You are the Hermes PDF/UA remediation strategy designer.\\n"
        "The orchestrator has a remediation strategy gap. It may be a preflight "
        "failure, residual validator failure, or exhausted mapped strategy. "
        "The request packet defines the stage, evidence, artifacts, and required "
        "response schema.\\n\\n"
        "Do not manually remediate this one document. Do not claim success. "
        "Design a reusable deterministic remediation strategy, or say why more "
        "evidence is required. Prefer existing repair scripts if one can be "
        "safely reused or parameterized. Do not choose provider models or "
        "provider API keys.\\n\\n"
        "Return strict JSON only matching required_response_schema.\\n\\n"
        f"REQUEST_PACKET:\\n{json.dumps(request_packet, indent=2)}\\n"
    )

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 2500,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=180) as resp:
        response = json.loads(resp.read().decode("utf-8"))

    message = response["choices"][0]["message"]
    raw_content = message.get("content") or message.get("reasoning_content") or ""

    try:
        proposal = json.loads(strip_json_fence(raw_content))
    except Exception as exc:
        proposal = {
            "result": "NEEDS_MORE_EVIDENCE",
            "error": f"Could not parse Hermes strategy JSON: {type(exc).__name__}: {exc}",
            "raw_content": raw_content[:4000],
        }

    if isinstance(proposal, dict):
        proposal.setdefault("_hermes_response_model", response.get("model", model))
        proposal.setdefault("_hermes_gateway_base_url", base_url)
    return proposal


def env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def select_residual_self_extension_rule(hermes_items, remaining_failures):
    """Pick exactly one residual rule for the Patch 2 self-extension hook."""
    requested = clean_metadata_text(os.environ.get("HERMES_SELF_EXTENSION_RULE_ID", ""))
    candidates = []
    for item in hermes_items or []:
        rule_id = clean_metadata_text(item.get("rule_id", "")) if isinstance(item, dict) else ""
        if rule_id:
            candidates.append(rule_id)
    for failure in remaining_failures or []:
        rule_id = clean_metadata_text(failure.get("rule_id", "")) if isinstance(failure, dict) else ""
        if rule_id and rule_id not in candidates:
            candidates.append(rule_id)

    if requested:
        return requested if requested in candidates else ""
    return candidates[0] if candidates else ""


def try_residual_self_extension_candidate(
    request_packet,
    request_path,
    current_pdf,
    remaining_failures,
    hermes_items,
):
    """Run one guarded residual self-extension candidate attempt.

    Patch 2 is intentionally conservative: default off, residual-only, one
    attempt, no adoption, no rule-map mutation, and no change to the final PDF
    used by packaging. A successful candidate is recorded as evidence for the
    next adoption/re-entry patch; the existing HERMES_REQUIRED fallback remains
    authoritative for outcome calculation.
    """
    if not env_flag("HERMES_ENABLE_SELF_EXTENSION", False):
        return None

    target_rule_id = select_residual_self_extension_rule(
        hermes_items,
        remaining_failures,
    )
    if not target_rule_id:
        record = {
            "result": "SKIPPED",
            "reason": "no_residual_rule_selected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (AUDIT_DIR / "self_extension_residual_result.json").write_text(
            json.dumps(record, indent=2)
        )
        emit("PLAN", "residual_self_extension", "SKIPPED", data=record)
        return record

    emit(
        "PLAN",
        "residual_self_extension",
        "RUNNING",
        data={"target_rule_id": target_rule_id, "attempt": 1},
    )

    artifacts = {
        "generation_request": AUDIT_DIR / "self_extension_generation_request.json",
        "generation_response": AUDIT_DIR / "self_extension_generation_response.json",
        "candidate_result": AUDIT_DIR / "self_extension_candidate_result.json",
        "residual_result": AUDIT_DIR / "self_extension_residual_result.json",
    }

    try:
        from tools.orchestrate.self_extension_executor import (
            build_residual_script_generation_request,
            execute_residual_candidate,
            generate_candidate_source,
            prepare_candidate_paths,
        )

        attempt = 1
        paths = prepare_candidate_paths(APP, JOB, target_rule_id, attempt)
        generation_request = build_residual_script_generation_request(
            strategy_request=request_packet,
            target_rule_id=target_rule_id,
            attempt=attempt,
            candidate_relative_path=paths.candidate_relative_path,
        )
        artifacts["generation_request"].write_text(
            json.dumps(generation_request, indent=2)
        )

        generation_response = generate_candidate_source(
            generation_request=generation_request,
            job_dir=JOB,
        )
        artifacts["generation_response"].write_text(
            json.dumps(generation_response, indent=2)
        )

        candidate_result = execute_residual_candidate(
            app_dir=APP,
            job_dir=JOB,
            strategy_request_path=request_path,
            target_rule_id=target_rule_id,
            attempt=attempt,
            current_pdf=Path(current_pdf),
            source_pdf=SOURCE_PDF,
            reference_pdf=PASS0,
            script_source=generation_response.get("script_source", ""),
            remediation_python=REMEDIATION_PYTHON,
            verapdf_bin=VERAPDF_BIN,
            profiles=PROFILES,
        )
        artifacts["candidate_result"].write_text(
            json.dumps(candidate_result, indent=2)
        )

        record = {
            "result": candidate_result.get("result", "UNKNOWN"),
            "reason": "candidate_validated_no_adoption" if candidate_result.get("result") == "PASS" else "candidate_rejected_or_failed",
            "target_rule_id": target_rule_id,
            "attempt": attempt,
            "adoption_performed": False,
            "final_pdf_updated": False,
            "existing_residual_gap_fallback_preserved": True,
            "artifacts": {key: str(value) for key, value in artifacts.items()},
            "candidate_relative_path": candidate_result.get("candidate_relative_path"),
            "candidate_output_pdf": candidate_result.get("candidate_output_pdf"),
            "success_predicate": candidate_result.get("success_predicate"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        record = {
            "result": "ERROR",
            "reason": f"{type(exc).__name__}: {exc}",
            "target_rule_id": target_rule_id,
            "attempt": 1,
            "adoption_performed": False,
            "final_pdf_updated": False,
            "existing_residual_gap_fallback_preserved": True,
            "artifacts": {key: str(value) for key, value in artifacts.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    artifacts["residual_result"].write_text(json.dumps(record, indent=2))
    emit(
        "PLAN",
        "residual_self_extension",
        record.get("result", "UNKNOWN"),
        data=record,
    )
    return record


def write_residual_strategy_gap_artifacts(current_pdf, remaining_failures, post_failures_path):
    """Invoke Hermes strategy design for residual final validator failures."""
    if not remaining_failures:
        return None

    emit(
        "PLAN",
        "residual_strategy_gap",
        "RUNNING",
        data={"remaining_failures": len(remaining_failures)},
    )

    lookup_cmd = [
        "python3",
        TOOLS / "audit" / "lookup_repair_plan.py",
        post_failures_path,
        "--map",
        RULE_MAP,
        "--taxonomy",
        TAXONOMY,
    ]
    if doc_tags:
        lookup_cmd.extend(["--doc-tags", ",".join(doc_tags)])

    rc, out, err = run(lookup_cmd, "lookup_repair_plan_post")
    residual_plan_path = AUDIT_DIR / "repair_plan_post.json"
    try:
        residual_plan = json.loads(out)
    except Exception:
        residual_plan = {
            "result": "ERROR",
            "repair_steps": [],
            "hermes_required": [],
            "unknown_rules": [],
            "error": (out + err)[:2000],
        }
    residual_plan_path.write_text(json.dumps(residual_plan, indent=2))

    hermes_items = list(residual_plan.get("hermes_required", []))
    if not hermes_items:
        for failure in remaining_failures:
            rule_id = failure.get("rule_id", "")
            if not rule_id:
                continue
            attempts = strategy_attempts.get(rule_id, [])
            reason = (
                "residual_after_mapped_repairs"
                if attempts else
                "residual_without_repair_step"
            )
            hermes_items.append({
                "rule_id": rule_id,
                "description": failure.get("description", ""),
                "failures": failure.get("failures", 0),
                "reason": reason,
                "strategies_attempted": attempts,
            })

    residual_plan["hermes_required_effective"] = hermes_items
    residual_plan_path.write_text(json.dumps(residual_plan, indent=2))

    request_packet = build_strategy_gap_request(
        current_pdf,
        remaining_failures,
        post_failures_path,
        residual_plan,
    )

    request_path = AUDIT_DIR / "hermes_strategy_request.json"
    proposal_path = AUDIT_DIR / "hermes_strategy_proposal.json"
    gap_path = AUDIT_DIR / "strategy_gap.json"

    request_path.write_text(json.dumps(request_packet, indent=2))

    self_extension_record = try_residual_self_extension_candidate(
        request_packet,
        request_path,
        current_pdf,
        remaining_failures,
        hermes_items,
    )

    proposal = {
        "result": "PENDING_AGENT_ACTION",
        "reason": "strategy_request_written_for_outer_hermes_agent",
        "request": str(request_path),
        "required_action": (
            "Outer Hermes agent must read the strategy request artifact, "
            "decide whether to reuse an existing script, propose a new "
            "deterministic repair, request more evidence, or mark the issue "
            "not automatable, then update/register code and rerun the "
            "orchestrator. The orchestrator must not make an in-process "
            "Hermes gateway strategy call while it is already being run by "
            "Hermes/Open WebUI."
        ),
        "operator_question_allowed": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    proposal_path.write_text(json.dumps(proposal, indent=2))

    artifacts = {
        "strategy_gap": str(gap_path),
        "strategy_request": str(request_path),
        "strategy_proposal": str(proposal_path),
        "repair_plan_post": str(residual_plan_path),
    }
    if self_extension_record:
        artifacts["self_extension_residual_result"] = str(
            AUDIT_DIR / "self_extension_residual_result.json"
        )
        for key, value in self_extension_record.get("artifacts", {}).items():
            artifacts[f"self_extension_{key}"] = value

    for item in hermes_items:
        emit_hermes_required(
            item.get("rule_id", ""),
            item.get("description", ""),
            item.get("failures", 0),
            item.get("reason", "strategy_design_required"),
            item.get("strategies_attempted", []),
            artifacts=artifacts,
        )

    gap_record = {
        "result": "HERMES_REQUIRED",
        "reason": "residual_strategy_design_required",
        "rules": [item.get("rule_id", "") for item in hermes_items],
        "request": str(request_path),
        "proposal": str(proposal_path),
        "repair_plan_post": str(residual_plan_path),
        "proposal_result": proposal.get("result", "UNKNOWN") if isinstance(proposal, dict) else "UNKNOWN",
        "self_extension": self_extension_record,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    gap_path.write_text(json.dumps(gap_record, indent=2))

    emit(
        "PLAN",
        "residual_strategy_gap",
        "HERMES_REQUIRED",
        data=gap_record,
    )

    return gap_record




def build_ocr_strategy_gap_request(ocr_attempt_records, preflight_summary):
    """Build a structured Hermes request for OCR/form-preservation deadlocks."""
    return {
        "request_type": "pdfua_preflight_strategy_design",
        "stage": "ocr_remediation",
        "rule_id": "local/OCR_REQUIRED",
        "ticket": TICKET,
        "job_name": JOB_NAME,
        "job_dir": str(JOB),
        "workspace": str(WORKSPACE),
        "source_pdf": str(SOURCE_PDF),
        "current_pdf": str(PASS0),
        "safe_to_package_success": False,
        "operator_question_allowed": False,
        "reason": "ocr_required_but_no_promotable_strategy",
        "problem": (
            "The source PDF requires OCR, but every available OCR strategy failed. "
            "At least one strategy left pages image-only, and at least one strategy "
            "produced extractable text but failed form-field preservation. This is "
            "a reusable remediation strategy gap, not an operator decision prompt."
        ),
        "doc_tags": doc_tags,
        "preflight_ocr_detection": preflight_summary,
        "ocr_attempts": ocr_attempt_records,
        "existing_repair_scripts": list_existing_repair_scripts(),
        "strategy_attempts": {
            "local/OCR_REQUIRED": strategy_attempts.get("local/OCR_REQUIRED", []),
        },
        "required_response_schema": {
            "result": (
                "USE_EXISTING_SCRIPT | PROPOSE_NEW_SCRIPT | "
                "NEEDS_MORE_EVIDENCE | NOT_AUTOMATABLE"
            ),
            "rule_id": "local/OCR_REQUIRED",
            "strategy": "stable_snake_case_strategy_name",
            "repair_script": "tools/repair/example.py or null",
            "preconditions": [],
            "pdf_edits": [],
            "validation_plan": [],
            "rule_map_update": {},
            "risks": [],
            "notes": "",
        },
    }


def write_ocr_strategy_gap_artifacts(ocr_attempt_records, preflight_summary):
    """Invoke Hermes strategy design when OCR preflight has no safe strategy."""
    emit(
        "PREFLIGHT",
        "ocr_strategy_gap",
        "RUNNING",
        data={"attempts": len(ocr_attempt_records)},
    )

    request_packet = build_ocr_strategy_gap_request(
        ocr_attempt_records,
        preflight_summary,
    )

    request_path = AUDIT_DIR / "ocr_strategy_request.json"
    proposal_path = AUDIT_DIR / "ocr_strategy_proposal.json"
    gap_path = AUDIT_DIR / "ocr_strategy_gap.json"

    request_path.write_text(json.dumps(request_packet, indent=2))

    proposal = {
        "result": "PENDING_AGENT_ACTION",
        "reason": "ocr_strategy_request_written_for_outer_hermes_agent",
        "request": str(request_path),
        "required_action": (
            "Outer Hermes agent must read the OCR strategy request artifact, "
            "decide whether to reuse an existing script, propose a new "
            "deterministic OCR/form-preservation strategy, request more "
            "evidence, or mark the issue not automatable, then update/register "
            "code and rerun the orchestrator. The orchestrator must not make "
            "an in-process Hermes gateway strategy call while it is already "
            "being run by Hermes/Open WebUI."
        ),
        "operator_question_allowed": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    proposal_path.write_text(json.dumps(proposal, indent=2))

    artifacts = {
        "strategy_gap": str(gap_path),
        "strategy_request": str(request_path),
        "strategy_proposal": str(proposal_path),
    }

    emit_hermes_required(
        "local/OCR_REQUIRED",
        (
            "OCR is required, but no current OCR strategy both removes "
            "image-only pages and preserves AcroForm/widget interactivity."
        ),
        len(ocr_attempt_records),
        "preflight_strategy_exhausted",
        attempts=ocr_attempt_records,
        artifacts=artifacts,
    )

    gap_record = {
        "result": "HERMES_REQUIRED",
        "reason": "ocr_preflight_strategy_design_required",
        "rule_id": "local/OCR_REQUIRED",
        "request": str(request_path),
        "proposal": str(proposal_path),
        "proposal_result": (
            proposal.get("result", "UNKNOWN")
            if isinstance(proposal, dict)
            else "UNKNOWN"
        ),
        "operator_question_allowed": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    gap_path.write_text(json.dumps(gap_record, indent=2))

    emit(
        "PREFLIGHT",
        "ocr_strategy_gap",
        "HERMES_REQUIRED",
        data=gap_record,
    )

    return gap_record


def infer_structural_tags(pdf_path):
    """Detect structural document tags using fitz. No LLM call."""
    tags = []
    try:
        import fitz
        doc = fitz.open(str(pdf_path))

        # multi_page
        if len(doc) > 4:
            tags.append('multi_page')

        # form_fields, images_figures, tables (via widget/xobject/struct presence)
        has_widgets    = False
        image_count    = 0
        for page in doc:
            for annot in page.annots() or []:
                if annot.type[0] == 19:  # PDF_ANNOT_WIDGET
                    has_widgets = True
                    break
            try:
                images = page.get_images(full=False)
                image_count += len(images)
            except Exception:
                pass

        if has_widgets:
            tags.append('form_fields')
        if image_count > 0:
            tags.append('images_figures')

        doc.close()
    except Exception:
        pass
    return tags


def infer_content_tags(pdf_path, taxonomy):
    """Use NIM LLM to classify document content against the taxonomy's content-type tags.
    Returns (assigned_tags, proposed_new_tags).
    Falls back to empty lists if NIM is unavailable or extraction fails."""
    if not taxonomy:
        return [], []

    # Extract text sample (first ~3000 chars is sufficient for classification)
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        text_sample = ''
        for page in doc:
            text_sample += page.get_text()
            if len(text_sample) > 3000:
                break
        doc.close()
        text_sample = text_sample[:3000].strip()
    except Exception:
        return [], []

    if not text_sample:
        return [], []

    # Only ask the LLM about content-type tags (structural ones inferred separately)
    content_tag_candidates = [
        t for t in taxonomy.get('tags', [])
        if t['tag'] not in ('multi_page', 'form_fields', 'images_figures', 'tables', 'multi_language')
    ]
    if not content_tag_candidates:
        return [], []

    tag_list_str = '\n'.join(
        f'- {t["tag"]}: {t["description"]}' for t in content_tag_candidates
    )

    prompt = (
        'You are classifying a PDF document against a controlled taxonomy of content-type tags. '
        'Based on the document text sample below, return JSON with two fields:\n'
        '  "assigned_tags": list of taxonomy tags that match the document\n'
        '  "proposed_new_tags": list of {tag, description} for any significant '
        'characteristic not covered by an existing tag (or [] if all relevant aspects are covered)\n\n'
        f'Available content-type tags:\n{tag_list_str}\n\n'
        f'Document text sample:\n{text_sample}\n\n'
        'Return JSON only, no prose:'
    )

    try:
        import os, urllib.request, urllib.error
        # Match the same fallback pattern used by generate_alt_text_drafts.py:
        # prefer VISION_PROVIDER_* vars, fall back to PRIMARY_PROVIDER_* vars.
        api_key = (os.environ.get('VISION_PROVIDER_API_KEY') or
                   os.environ.get('PRIMARY_PROVIDER_API_KEY', ''))
        base_url = (os.environ.get('VISION_PROVIDER_BASE_URL') or
                    os.environ.get('PRIMARY_PROVIDER_BASE_URL', '')).rstrip('/')
        api_url  = base_url + '/chat/completions' if base_url else \
                   'https://integrate.api.nvidia.com/v1/chat/completions'
        model    = os.environ.get('PRIMARY_MODEL', 'stepfun-ai/step-3.5-flash')

        if not api_key:
            return [], []

        body = json.dumps({
            'model': model,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.0,
            'max_tokens': 2000
        }).encode('utf-8')

        req = urllib.request.Request(
            api_url,
            data=body,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type':  'application/json'
            }
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            response = json.loads(resp.read().decode('utf-8'))

        message = response['choices'][0]['message']
        # stepfun-ai/step-3.5-flash is a reasoning model — final answer goes
        # into 'content' but reasoning trace is in 'reasoning_content'.
        # If content is null, the model ran out of tokens before finishing —
        # try to extract JSON from reasoning_content as fallback.
        content = message.get('content') or message.get('reasoning_content') or ''
        content = content.strip()
        if not content:
            return [], []
        # Strip markdown fences if present
        if content.startswith('```'):
            content = content.split('```', 2)[1]
            if content.startswith('json'):
                content = content[4:]
            content = content.strip()

        parsed = json.loads(content)
        valid_tags = {t['tag'] for t in content_tag_candidates}
        assigned   = [t for t in parsed.get('assigned_tags', []) if t in valid_tags]
        proposed   = parsed.get('proposed_new_tags', [])
        proposed   = [p for p in proposed
                      if isinstance(p, dict) and 'tag' in p and 'description' in p]
        return assigned, proposed
    except Exception as e:
        # Emit warning so the issue is visible in orchestrator output
        try:
            emit('SETUP', 'doc_tagging_content', 'WARN',
                 note=f'Content classification NIM call failed: {type(e).__name__}: {e}')
        except Exception:
            pass
        return [], []


def assign_doc_tags(pdf_path, taxonomy):
    """Combine structural and content tag inference into a single result."""
    structural = infer_structural_tags(pdf_path)
    content, proposed = infer_content_tags(pdf_path, taxonomy)
    # Deduplicate, preserve order
    seen = set()
    combined = []
    for t in structural + content:
        if t not in seen:
            seen.add(t)
            combined.append(t)
    return combined, proposed

PASS_CODES = {
    'PASS', 'FIXED', 'ALREADY_CORRECT', 'PASS_WITH_MIXED_PAGES',
    'PASS_WITH_ONLY_NATIVE_TEXT', 'SKIPPED', 'OK', 'PLAN_READY',
    'NO_FAILURES', 'NEEDS_REVIEW'
}

def is_pass(result):
    return result in PASS_CODES

# ── Validate prerequisites ────────────────────────────────────────────────────

def check_prereqs():
    errors = []
    if not Path(REMEDIATION_PYTHON).exists() and shutil.which(REMEDIATION_PYTHON) is None:
        errors.append(f'Remediation python interpreter not found: {REMEDIATION_PYTHON} '
                      '(set REMEDIATION_PYTHON to a python3 with pikepdf/pdfplumber installed)')
    if not SOURCE_PDF.exists():
        errors.append(f'Source PDF not found: {SOURCE_PDF}')
    if not VERAPDF_BIN.exists():
        errors.append(f'veraPDF not found: {VERAPDF_BIN}')
    if not RULE_MAP.exists():
        errors.append(f'Rule map not found: {RULE_MAP}')
    if not PROFILES.exists():
        errors.append(f'veraPDF profiles not found: {PROFILES}')
    return errors

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 0 — Setup
# ─────────────────────────────────────────────────────────────────────────────

emit('SETUP', 'prereq_check', 'RUNNING')
errors = check_prereqs()
if errors:
    for e in errors: emit('SETUP', 'prereq_check', 'FAIL', note=e)
    sys.exit(2)
emit('SETUP', 'prereq_check', 'PASS')

# Scaffold
emit('SETUP', 'scaffold', 'RUNNING')
rc, out, err = run(
    [REMEDIATION_PYTHON, TOOLS/'packaging'/'package_scaffold.py',
     WORKSPACE, TICKET, BASENAME],
    'scaffold',
    env={'PYTHONPATH': str(APP)},
)
try:
    scaffold = json.loads(out)
    JOB  = Path(scaffold['job_dir'])
    OUT  = Path(scaffold['output_dir'])
except Exception:
    JOB  = JOB_DIR
    OUT  = OUTPUT_DIR

if rc != 0:
    emit_deviation('scaffold', 'exit_code=0', f'exit_code={rc}', err, layer=1)
    sys.exit(2)
emit('SETUP', 'scaffold', 'PASS', data={'job_dir': str(JOB), 'output_dir': str(OUT)})

REPAIR_DIR  = JOB / 'repair'
AUDIT_DIR   = JOB / 'audit'
QA_DIR      = JOB / 'qa'
REPORTS_DIR = JOB / 'reports'

# Copy source PDF
PASS0 = REPAIR_DIR / 'pass0_source.pdf'
emit('SETUP', 'copy_source', 'RUNNING')
shutil.copy2(SOURCE_PDF, PASS0)
emit('SETUP', 'copy_source', 'PASS', data={'pass0': str(PASS0)})

# Doc tagging
emit('SETUP', 'doc_tagging', 'RUNNING')
doc_tags             = []
proposed_taxonomy_additions = []
try:
    taxonomy = load_json(TAXONOMY)
    if taxonomy:
        doc_tags, proposed_taxonomy_additions = assign_doc_tags(PASS0, taxonomy)
        emit('SETUP', 'doc_tagging', 'PASS',
             data={'doc_tags':                    doc_tags,
                   'proposed_taxonomy_additions': proposed_taxonomy_additions})
    else:
        emit('SETUP', 'doc_tagging', 'WARN', note='Taxonomy file not loadable')
except Exception as e:
    emit('SETUP', 'doc_tagging', 'WARN', note=f'Doc tagging failed: {e}')

# Persist taxonomy proposals to a sidecar that status_json_writer can pick up
if proposed_taxonomy_additions:
    try:
        (AUDIT_DIR / 'proposed_taxonomy_additions.json').write_text(
            json.dumps(proposed_taxonomy_additions, indent=2)
        )
    except Exception:
        pass

# Persist doc_tags to a sidecar that status_json_writer can pick up
if doc_tags:
    try:
        (AUDIT_DIR / 'doc_tags.json').write_text(
            json.dumps(doc_tags, indent=2)
        )
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Pre-flight
# ─────────────────────────────────────────────────────────────────────────────

# 1a. OCR detection
emit('PREFLIGHT', 'ocr_detection', 'RUNNING')
rc, out, _ = run(
    [REMEDIATION_PYTHON, TOOLS/'audit'/'detect_image_only_pages.py', PASS0,
     '--out', AUDIT_DIR/'detect_image_only_pages.json'],
    'ocr_detection'
)
ocr_data   = load_json(AUDIT_DIR/'detect_image_only_pages.json')
ocr_result = get_result(ocr_data)
gate_results['ocr_detection'] = ocr_result

if ocr_data and ocr_data.get('ocr_required'):
    # ocrmypdf availability check
    cp = subprocess.run(['which', 'ocrmypdf'], capture_output=True)
    if cp.returncode != 0:
        emit_deviation(
            'ocr_remediation', 'ocr_available', 'ocrmypdf_missing',
            'ocrmypdf not in PATH. Install tesseract-ocr and ocrmypdf to '
            'enable automatic OCR.',
            layer=1,
        )
        sys.exit(1)

    emit('PREFLIGHT', 'ocr_remediation_strategies', 'RUNNING')

    ocr_strategies = [
        {
            'strategy': 'ocrmypdf_skip_text',
            'script': 'ocrmypdf',
            # Do not let OCRmyPDF default to PDF/A here; PDF/A conversion can
            # remove interactive form features. The pipeline targets PDF/UA.
            'flags': ['--quiet', '--output-type', 'pdf', '--skip-text'],
        },
        {
            'strategy': 'ocrmypdf_force_ocr',
            'script': 'ocrmypdf',
            # Force OCR is inherently risky for form PDFs because it rasterizes
            # page content. A form-preservation gate below prevents promotion
            # if widgets/AcroForm fields are lost.
            'flags': ['--quiet', '--output-type', 'pdf', '--force-ocr', '--deskew', '--rotate-pages'],
        },
        {
            # Scanned fillable forms: --skip-text skips any page carrying even
            # incidental text (page numbers) while the detector still calls it
            # image-only; --force-ocr rasterizes and destroys AcroForm fields.
            # This repair script overlays an invisible tesseract text layer on
            # the ORIGINAL pages -- geometry, content, and widgets untouched.
            'strategy': 'tesseract_textonly_overlay',
            'script': 'tools/repair/ocr_preserve_forms.py',
            'flags': [],
        },
    ]
    # Default output path names — updated per iteration when a strategy wins
    strategy_output_map = {
        'ocrmypdf_skip_text':           REPAIR_DIR / 'pass0_ocr_skip_text.pdf',
        'ocrmypdf_force_ocr':           REPAIR_DIR / 'pass0_ocr_force_ocr.pdf',
        'tesseract_textonly_overlay':   REPAIR_DIR / 'pass0_ocr_textonly_overlay.pdf',
    }

    ocr_attempt_records = []
    preflight_summary = summarize_ocr_detector(ocr_data)
    prev_ocr_out = None
    ocr_input = PASS0  # snapshot pre-OCR input before any strategy runs

    for strategy in ocr_strategies:
        strategy_name = strategy['strategy']
        output_pdf = strategy_output_map[strategy_name]
        validation_json = AUDIT_DIR / f'detect_image_only_pages_{strategy_name}.json'

        emit('PREFLIGHT', f'ocr_remediation_run:{strategy_name}', 'RUNNING')
        if strategy['script'] == 'ocrmypdf':
            ocr_cmd = ['ocrmypdf', *strategy['flags'], str(PASS0), str(output_pdf)]
        else:
            # Repair-script strategy: standard contract plus this script's
            # language/audit options. Its own JSON result (incl. quality_notes
            # and skew flags) lands in AUDIT_DIR for the attempt record.
            ocr_cmd = [
                REMEDIATION_PYTHON, APP / strategy['script'],
                str(PASS0), str(output_pdf),
                '--out', str(AUDIT_DIR / f'ocr_repair_{strategy_name}.json'),
                '--audit-dir', str(AUDIT_DIR),
                '--language', tesseract_lang(LANGUAGE),
            ]
        rc_ocr, out_ocr, err_ocr = run(ocr_cmd, f'ocr_remediation:{strategy_name}')

        record = {
            'iteration': len(ocr_attempt_records),
            'strategy': strategy_name,
            'script': strategy['script'],
            'flags': strategy['flags'],
            'input_pdf': str(PASS0),
            'output_pdf': str(output_pdf),
            'exit_code': rc_ocr,
            'source_pdf_modified': False,
        }
        if rc_ocr != 0:
            record['result'] = 'FAIL'
            record['error'] = (out_ocr + err_ocr)[:2000]
            record['promotable'] = False
            ocr_attempt_records.append(record)
            strategy_attempts['local/OCR_REQUIRED'].append(record)
            continue

        # Validate the OCR output — no more ocrmypdf flags, just detector
        rc_v, _, _ = run(
            [
                REMEDIATION_PYTHON, TOOLS / 'audit' / 'detect_image_only_pages.py',
                str(output_pdf),
                '--out', str(validation_json),
            ],
            f'ocr_remediation_validate:{strategy_name}',
        )
        val_data = load_json(validation_json)
        val_summary = summarize_ocr_detector(val_data)

        record.update({
            'validation_artifact': str(validation_json),
            'validation_exit_code': rc_v,
            'validation_result': val_summary['result'],
            'ocr_required': val_summary['ocr_required'],
            'char_count_total': val_summary['char_count_total'],
            'char_count_min': val_summary['char_count_min'],
            'char_count_max': val_summary['char_count_max'],
            'image_only_pages': val_summary['image_only_pages'],
        })

        if val_data and not val_data.get('ocr_required'):
            form_validation_json = AUDIT_DIR / f'form_field_preservation_{strategy_name}.json'
            rc_form, _, _ = run(
                [
                    REMEDIATION_PYTHON,
                    TOOLS / 'qa' / 'form_field_preservation_audit.py',
                    str(SOURCE_PDF),
                    str(output_pdf),
                    '--out',
                    str(form_validation_json),
                ],
                f'ocr_remediation_form_preservation:{strategy_name}',
            )
            form_data = load_json(form_validation_json)
            form_result = get_result(form_data)
            record.update({
                'form_preservation_artifact': str(form_validation_json),
                'form_preservation_exit_code': rc_form,
                'form_preservation_result': form_result,
                'source_has_form': bool(form_data.get('source_has_form')) if isinstance(form_data, dict) else None,
                'source_field_count': form_data.get('source_field_count') if isinstance(form_data, dict) else None,
                'output_field_count': form_data.get('output_field_count') if isinstance(form_data, dict) else None,
            })

            if not is_pass(form_result):
                record['result'] = 'FAIL'
                record['promotable'] = False
                record['error'] = (
                    'OCR output failed form field preservation; refusing to '
                    'promote a non-fillable form artifact'
                )
                ocr_attempt_records.append(record)
                strategy_attempts['local/OCR_REQUIRED'].append(record)
                emit(
                    'PREFLIGHT',
                    f'ocr_remediation_form_preservation:{strategy_name}',
                    form_result,
                    data={
                        'artifact': str(output_pdf),
                        'validation_artifact': str(form_validation_json),
                    },
                )
                continue

            record['result'] = 'PASS'
            record['promotable'] = True
            ocr_attempt_records.append(record)
            strategy_attempts['local/OCR_REQUIRED'].append(record)
            # Determine which artifact actually drove the pass for the emit
            if prev_ocr_out is not None:
                emit(
                    'PREFLIGHT', 'ocr_remediation_validate',
                    val_summary['result'],
                    data={
                        'artifact': str(output_pdf),
                        'strategy': strategy_name,
                        'skip_text_failed': True,
                        'validation_artifact': str(validation_json),
                    },
                )
            else:
                emit(
                    'PREFLIGHT', 'ocr_remediation_validate',
                    val_summary['result'],
                    data={
                        'artifact': str(output_pdf),
                        'strategy': strategy_name,
                        'validation_artifact': str(validation_json),
                    },
                )
            PASS0 = output_pdf
            break

        # Validation failed on this strategy
        record['result'] = 'FAIL'
        record['promotable'] = False
        record['error'] = (
            'OCR output still requires OCR after validation '
            f'(char_count_total={val_summary["char_count_total"]}, '
            f'image_only_pages={val_summary["image_only_pages"]})'
        )
        ocr_attempt_records.append(record)
        strategy_attempts['local/OCR_REQUIRED'].append(record)
        prev_ocr_out = output_pdf

    else:
        # All strategies exhausted without a successful validation. This is a
        # remediation strategy gap, not an operator chat prompt.
        gap_record = write_ocr_strategy_gap_artifacts(
            ocr_attempt_records,
            preflight_summary,
        )

        emit(
            'PREFLIGHT',
            'ocr_remediation_strategies',
            'HERMES_REQUIRED',
            data={
                'attempts': ocr_attempt_records,
                'preflight_ocr_detection': preflight_summary,
                'strategy_gap': gap_record,
            },
        )

        write_strategy_log(JOB)

        try:
            (AUDIT_DIR / 'hermes_signals.json').write_text(
                json.dumps(hermes_signals, indent=2)
            )
        except Exception:
            pass

        try:
            (AUDIT_DIR / 'orchestrator_outcome.json').write_text(json.dumps({
                'overall_result': 'ESCALATION',
                'reason': 'ocr_preflight_strategy_gap',
                'critical_fails': ['ocr_remediation'],
                'deviations': deviations,
                'gate_results': gate_results,
                'hermes_signals': hermes_signals,
                'strategy_gap': gap_record,
                'duration_seconds': (
                    datetime.now(timezone.utc) - start_time
                ).total_seconds(),
            }, indent=2))
        except Exception:
            pass

        # Exit 3 means strategy action required. This is intentionally
        # distinct from generic execution failure so the outer Hermes agent
        # continues the HERMES_REQUIRED workflow instead of reporting a
        # terminal operator-facing failure.
        sys.exit(3)

    # At least one strategy validated — record only the winning attempt in the
    # passing emit (failed attempts already recorded above).
    emit(
        'PREFLIGHT', 'ocr_remediation', 'PASS',
        data={
            'source': str(ocr_input),
            'artifact': str(PASS0),
            'strategy': strategy_name,
            'char_count_before': preflight_summary['char_count_total'],
            'char_count_after': val_summary['char_count_total'],
            'image_only_pages_before': preflight_summary['image_only_pages'],
            'image_only_pages_after': val_summary['image_only_pages'],
        },
    )
    gate_results['ocr_detection'] = 'PASS'

else:
    emit('PREFLIGHT', 'ocr_detection', ocr_result)

# 1b. qpdf structural check
emit('PREFLIGHT', 'qpdf_check', 'RUNNING')
rc, out, _ = run(
    ['bash', TOOLS/'audit'/'run_qpdf_check.sh', PASS0, AUDIT_DIR,
     '--out', AUDIT_DIR/'qpdf_check.json'],
    'qpdf_check'
)
qpdf_data   = load_json(AUDIT_DIR/'qpdf_check.json')
qpdf_result = get_result(qpdf_data)
gate_results['qpdf'] = qpdf_result

if not is_pass(qpdf_result):
    emit_deviation('qpdf_check', 'PASS', qpdf_result,
                   qpdf_data.get('errors', '') if qpdf_data else '', layer=1)
    sys.exit(1)
emit('PREFLIGHT', 'qpdf_check', qpdf_result)

# 1c. Struct tree pre-flight
emit('PREFLIGHT', 'struct_tree_check', 'RUNNING')
try:
    import fitz as _fitz
    _doc      = _fitz.open(str(PASS0))
    _catalog  = _doc.pdf_catalog()
    _str_ref  = _doc.xref_get_key(_catalog, 'StructTreeRoot')
    _has_struct = _str_ref[0] != 'null' and bool(_str_ref[1])
    _doc.close()
except Exception:
    _has_struct = None

if _has_struct is False:
    gate_results['struct_tree_check'] = 'FAIL'
    emit('PREFLIGHT', 'struct_tree_check', 'FAIL',
         note='No StructTreeRoot — running fix_untagged_pdf.py to auto-generate structure tree')

    untagged_fix  = TOOLS / 'repair' / 'fix_untagged_pdf.py'
    pass1_tagged  = REPAIR_DIR / 'pass1_fix_untagged.pdf'

    if untagged_fix.exists():
        rc_tag, out_tag, _ = run(
            [REMEDIATION_PYTHON, untagged_fix, PASS0, pass1_tagged,
             '--out', AUDIT_DIR / 'fix_untagged.json'],
            'fix_untagged_pdf'
        )
        if rc_tag == 0 and pass1_tagged.exists():
            emit('PREFLIGHT', 'fix_untagged_pdf', 'FIXED')
            marking_fix  = TOOLS / 'repair' / 'fix_struct_content_marking.py'
            pass2_marked = REPAIR_DIR / 'pass2_fix_struct_content_marking.pdf'
            if marking_fix.exists():
                rc_mark, _, _ = run(
                    [REMEDIATION_PYTHON, marking_fix, pass1_tagged, pass2_marked,
                     '--out', AUDIT_DIR / 'fix_struct_content_marking.json'],
                    'fix_struct_content_marking'
                )
                PASS0 = pass2_marked if (rc_mark == 0 and pass2_marked.exists()) else pass1_tagged
                emit('PREFLIGHT', 'fix_struct_content_marking',
                     'FIXED' if rc_mark == 0 else 'WARN')
            else:
                PASS0 = pass1_tagged
            gate_results['struct_tree_check'] = 'FIXED'
        else:
            emit_deviation('fix_untagged_pdf', 'FIXED', 'FAIL',
                           out_tag[:200] if out_tag else 'no output', layer=1)
            sys.exit(1)
    else:
        emit_deviation('struct_tree_check', 'fix_untagged_pdf.py exists',
                       'script not found', str(untagged_fix), layer=1)
        sys.exit(1)
else:
    gate_results['struct_tree_check'] = 'PASS' if _has_struct else 'UNKNOWN'
    emit('PREFLIGHT', 'struct_tree_check', gate_results['struct_tree_check'])

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Audit gates
# ─────────────────────────────────────────────────────────────────────────────

# 2a. Baseline veraPDF
emit('AUDIT', 'verapdf_baseline', 'RUNNING')
run(['bash', TOOLS/'audit'/'run_verapdf_profiles.sh',
     VERAPDF_BIN, PROFILES, PASS0, AUDIT_DIR],
    'verapdf_baseline')

for src, dst in [
    (AUDIT_DIR/'verapdf_pdfua_ua1.xml',       AUDIT_DIR/'verapdf_pre_pdfua1.xml'),
    (AUDIT_DIR/'verapdf_wcag_2_2_machine.xml', AUDIT_DIR/'verapdf_pre_wcag.xml'),
]:
    if Path(src).exists():
        shutil.copy2(src, dst)

verapdf_summary = load_json(AUDIT_DIR/'verapdf_summary.json')
gate_results['verapdf_baseline'] = get_result(verapdf_summary)
emit('AUDIT', 'verapdf_baseline', gate_results['verapdf_baseline'],
     note='Failures expected — repair plan will address them')

# 2b. Parse veraPDF failures
emit('AUDIT', 'parse_failures', 'RUNNING')
rc, out, _ = run(
    [REMEDIATION_PYTHON, TOOLS/'audit'/'parse_verapdf_summary.py',
     AUDIT_DIR/'verapdf_pre_pdfua1.xml',
     AUDIT_DIR/'verapdf_pre_wcag.xml'],
    'parse_failures'
)
failures_path = AUDIT_DIR / 'failures.json'
try:
    failures_data = json.loads(out)
    failures_path.write_text(json.dumps(failures_data, indent=2))
    emit('AUDIT', 'parse_failures', 'PASS',
         data={'unique_rules': failures_data.get('unique_rules_failing', 0),
               'total_failures': failures_data.get('total_failures', 0)})
except Exception as e:
    emit_deviation('parse_failures', 'valid JSON', f'parse error: {e}', out[:200], layer=1)
    failures_path.write_text('{"result":"PASS","failures_by_rule":[]}')
    failures_data = {'failures_by_rule': []}

# 2c. Metadata audit
emit('AUDIT', 'metadata_parity', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'audit'/'metadata_xmp_parity_audit.py', PASS0,
     '--out', AUDIT_DIR/'metadata_pre.json'], 'metadata_parity')
meta_pre = load_json(AUDIT_DIR/'metadata_pre.json')
gate_results['metadata_pre'] = get_result(meta_pre)
emit('AUDIT', 'metadata_parity', gate_results['metadata_pre'])

# 2d. Preservation audit
emit('AUDIT', 'preservation', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'qa'/'preservation_audit.py', PASS0, PASS0,
     '--out', AUDIT_DIR/'preservation_pre.json'], 'preservation')
pres_pre = load_json(AUDIT_DIR/'preservation_pre.json')
gate_results['preservation_pre'] = get_result(pres_pre)
emit('AUDIT', 'preservation', gate_results['preservation_pre'])

# 2e. Table semantics audit
emit('AUDIT', 'table_semantics', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'audit'/'table_semantics_audit.py', PASS0,
     '--out', AUDIT_DIR/'table_semantics_pre.json'], 'table_semantics')
table_pre = load_json(AUDIT_DIR/'table_semantics_pre.json')
gate_results['table_semantics_pre'] = get_result(table_pre)
th_missing = table_pre.get('th_missing_scope', 0) if table_pre else 0
emit('AUDIT', 'table_semantics', gate_results['table_semantics_pre'])

# 2f. Contrast audit
emit('AUDIT', 'contrast', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'audit'/'contrast_audit.py', PASS0,
     '--out', AUDIT_DIR/'contrast_pre.json'], 'contrast')
contrast_pre = load_json(AUDIT_DIR/'contrast_pre.json')
gate_results['contrast_pre'] = get_result(contrast_pre)
emit('AUDIT', 'contrast', gate_results['contrast_pre'])

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Repair plan
# ─────────────────────────────────────────────────────────────────────────────

emit('PLAN', 'lookup_repair_plan', 'RUNNING')
lookup_cmd = [REMEDIATION_PYTHON, TOOLS/'audit'/'lookup_repair_plan.py',
              failures_path, '--map', RULE_MAP, '--taxonomy', TAXONOMY]
if doc_tags:
    lookup_cmd.extend(['--doc-tags', ','.join(doc_tags)])
rc, out, _ = run(lookup_cmd, 'lookup_repair_plan')
plan_path = AUDIT_DIR / 'repair_plan.json'
try:
    plan_data = json.loads(out)
    plan_path.write_text(json.dumps(plan_data, indent=2))
except Exception:
    plan_data = {'result': 'NO_FAILURES', 'repair_steps': [], 'hermes_required': [], 'unknown_rules': []}
    plan_path.write_text(json.dumps(plan_data, indent=2))

repair_steps       = plan_data.get('repair_steps', [])
hermes_required  = plan_data.get('hermes_required', [])
unknown_rules      = plan_data.get('unknown_rules', [])

# Inject table headers fix if TH scope issues found and not already in plan
table_headers_script = 'tools/repair/fix_table_headers.py'
has_table_fix = any(s['repair_script'] == table_headers_script for s in repair_steps)
if th_missing > 0 and not has_table_fix:
    repair_steps.append({
        'step':            len(repair_steps) + 1,
        'repair_script':   table_headers_script,
        'strategy':        'fix_table_headers',
        'description':     f'TH cells missing Scope attribute ({th_missing} found by table_semantics_audit)',
        'repair_order':    10,
        'run_last':        True,
        'args_pattern':    '<input.pdf> <output.pdf>',
        'rules_addressed': ['table_semantics/TH_missing_scope'],
        'confidence':      'CONFIRMED',
        'pass_rate':       1.0,
        'pass_count':      1,
        'fail_count':      0,
        'all_strategies':  [],
        'notes':           f'Injected: {th_missing} TH cells missing Scope. MUST RUN LAST.'
    })
    repair_steps.sort(key=lambda s: (s.get('run_last', False), s.get('repair_order', 99)))
    for i, s in enumerate(repair_steps, 1):
        s['step'] = i

emit('PLAN', 'lookup_repair_plan', plan_data.get('result', 'UNKNOWN'),
     data={
         'repair_steps':      len(repair_steps),
         'hermes_required': len(hermes_required),
         'unknown_rules':     len(unknown_rules),
         'th_fix_injected':   th_missing > 0 and not has_table_fix
     })

# Emit HERMES_REQUIRED signals for all rules needing agent intervention
for oc in hermes_required:
    emit_hermes_required(
        oc['rule_id'], oc.get('description', ''),
        oc.get('failures', 0), oc['reason'],
        oc.get('strategies_attempted', [])
    )

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — Alt text branch determination
# ─────────────────────────────────────────────────────────────────────────────

ALT_MAP_JOB   = REPORTS_DIR / 'alt_map_approved.json'
ALT_MAP_ASSET = WORKSPACE / 'assets' / 'alt_maps' / f'{SAFE_BASE}_alt_map_approved.json'

alt_branch = 'NONE'
if ALT_MAP_JOB.exists() and approved_alt_map_has_figures(ALT_MAP_JOB):
    alt_branch = 'A_LOCAL'
elif ALT_MAP_ASSET.exists() and approved_alt_map_has_figures(ALT_MAP_ASSET):
    alt_branch = 'A_ASSET'
    shutil.copy2(ALT_MAP_ASSET, ALT_MAP_JOB)
else:
    alt_branch = 'B'

emit('PLAN', 'alt_text_branch', alt_branch)

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5 — Iterative repair loop
# ─────────────────────────────────────────────────────────────────────────────
#
# Each iteration:
#   1. Pick next untried strategy for each unresolved rule
#   2. Run repair script
#   3. Run full validate cycle (veraPDF + preservation + metadata)
#   4. Mark rule resolved or log attempt and try next strategy next iteration
#   5. If per-rule cap hit (15): emit HERMES_REQUIRED, continue with other rules
#   6. If per-job cap hit (50): force termination
#   7. Log all attempts to strategy_attempts.json
#
# ─────────────────────────────────────────────────────────────────────────────

current_pdf  = PASS0
pass_num     = 3  # 0=source, 1=untagged, 2=marking already used if applicable
resolved_rules   = set()
per_rule_counts  = defaultdict(int)

def next_pass(label):
    global pass_num
    p = REPAIR_DIR / f'pass{pass_num}_{label}.pdf'
    pass_num += 1
    return p

def run_validate_cycle(pdf_path, iteration):
    """Run veraPDF + preservation after a repair. Returns (failures_by_rule, pres_result)."""
    # veraPDF post
    run(['bash', TOOLS/'audit'/'run_verapdf_profiles.sh',
         VERAPDF_BIN, PROFILES, pdf_path, AUDIT_DIR],
        f'verapdf_iter{iteration}')
    iter_pdfua = AUDIT_DIR / f'verapdf_iter{iteration}_pdfua1.xml'
    iter_wcag  = AUDIT_DIR / f'verapdf_iter{iteration}_wcag.xml'
    for src, dst in [
        (AUDIT_DIR/'verapdf_pdfua_ua1.xml',       iter_pdfua),
        (AUDIT_DIR/'verapdf_wcag_2_2_machine.xml', iter_wcag),
    ]:
        if Path(src).exists():
            shutil.copy2(src, dst)

    rc2, out2, _ = run(
        [REMEDIATION_PYTHON, TOOLS/'audit'/'parse_verapdf_summary.py',
         iter_pdfua, iter_wcag],
        f'parse_iter{iteration}'
    )
    try:
        post = json.loads(out2)
        failures = post.get('failures_by_rule', [])
    except Exception:
        failures = []

    # Preservation check
    run([REMEDIATION_PYTHON, TOOLS/'qa'/'preservation_audit.py',
         PASS0, pdf_path,
         '--out', AUDIT_DIR/f'preservation_iter{iteration}.json'],
        f'preservation_iter{iteration}')
    pres = load_json(AUDIT_DIR/f'preservation_iter{iteration}.json')

    return failures, get_result(pres)


# Build the ordered list of scripts to execute. Deduplicate by script
# (one script can address multiple rules — execute it once per iteration).
pending_scripts = []
seen_scripts    = set()
for step in sorted(repair_steps, key=lambda s: (s.get('run_last', False), s.get('repair_order', 99))):
    script = step['repair_script']
    if script not in seen_scripts:
        seen_scripts.add(script)
        pending_scripts.append(step)

unresolved_scripts = list(pending_scripts)
iteration          = 0

while unresolved_scripts and total_iterations < JOB_HARD_CAP:
    iteration       += 1
    total_iterations += 1

    if total_iterations == JOB_WARN_AT:
        emit('REPAIR', 'iteration_warning', 'WARN',
             note=f'Job has reached {JOB_WARN_AT} total iterations. Logged to STATUS.json.')

    emit('REPAIR', f'iteration_{iteration}', 'RUNNING',
         data={'scripts_remaining': len(unresolved_scripts),
               'total_iterations':  total_iterations})

    iteration_pdf    = current_pdf
    # Track per-script results within this iteration:
    # script_path_str -> {step, result, executed}
    script_results = {}

    for step in unresolved_scripts:
        script       = step['repair_script']
        rule_ids     = step['rules_addressed']
        script_label = Path(script).stem
        script_path  = APP / script

        # Skip scripts whose rules are ALL already at the per-rule cap.
        # Only emit per_rule_cap_reached for rules that have actually been attempted.
        capped_rules    = [r for r in rule_ids if per_rule_counts[r] >= PER_RULE_CAP]
        uncapped_rules  = [r for r in rule_ids if per_rule_counts[r] <  PER_RULE_CAP]
        if not uncapped_rules:
            for r in capped_rules:
                emit_hermes_required(
                    r, '', 0, 'per_rule_cap_reached',
                    strategy_attempts.get(r, [])
                )
            continue

        if not script_path.exists():
            emit_deviation(script, 'script_exists', 'NOT_FOUND',
                           f'Script not found at {script_path}', layer=1)
            script_results[script] = {'step': step, 'result': 'NOT_FOUND', 'executed': False}
            continue

        output_pdf = next_pass(f'iter{iteration}_{script_label}')

        emit('REPAIR', script_label, 'RUNNING',
             data={'iteration': iteration,
                   'strategy':  step.get('strategy', ''),
                   'rules':     rule_ids})

        # ── Special handling: fix_figure_alt_text ────────────────────────────
        if 'fix_figure_alt_text' in script:
            if alt_branch in ('A_LOCAL', 'A_ASSET'):
                rc, out, err = run(
                    [REMEDIATION_PYTHON, script_path, iteration_pdf, output_pdf,
                     '--alt-map', ALT_MAP_JOB, '--language', LANGUAGE],
                    script_label
                )
            else:
                auto_pdf    = REPAIR_DIR / f'pass{pass_num}_alt_auto.pdf'
                auto_json   = AUDIT_DIR  / 'alt_text_auto_output.json'
                drafts_json = REPORTS_DIR/ 'alt_text_drafts.json'
                review_html = REPORTS_DIR/ 'alt_text_review.html'

                rc_auto, out_auto, _ = run(
                    [REMEDIATION_PYTHON, script_path, iteration_pdf, auto_pdf,
                     '--language', LANGUAGE],
                    f'{script_label}_auto'
                )
                globals()['pass_num'] = pass_num + 1

                # fix_figure_alt_text auto-mode exits 1 with result=NEEDS_REVIEW
                # when placeholders are set — that is the expected success case.
                # Only treat it as a failure if no output PDF was produced.
                if not auto_pdf.exists():
                    emit_deviation(f'{script_label}_auto',
                                   f'auto_pdf exists at {auto_pdf}',
                                   f'rc={rc_auto}, file_missing=True',
                                   'Branch B auto-mode failed to produce intermediate PDF',
                                   layer=1)
                    script_results[script] = {'step': step, 'result': 'AUTO_FAILED', 'executed': False}
                    continue

                # Write auto_json from stdout
                try:
                    auto_data = json.loads(out_auto)
                    auto_json.write_text(json.dumps(auto_data, indent=2))
                except Exception:
                    pass

                # Step B2: generate drafts via Hermes auxiliary vision.
                # This script imports Hermes' auxiliary_client in Hermes mode,
                # so run it under the Hermes runtime venv instead of system
                # python3. Model/provider selection remains dynamic through
                # Hermes call_llm(task='vision') and the admin/config runtime.
                hermes_python = Path('/opt/hermes/.venv/bin/python3')
                draft_python = hermes_python if hermes_python.exists() else Path(REMEDIATION_PYTHON)
                run([draft_python, TOOLS/'repair'/'generate_alt_text_drafts.py',
                     auto_pdf, '--fix-output', auto_json, '--out', drafts_json],
                    f'{script_label}_drafts')

                if not drafts_json.exists():
                    emit_deviation(f'{script_label}_drafts',
                                   f'drafts_json exists at {drafts_json}',
                                   'drafts_json missing',
                                   'Branch B draft generation failed', layer=1)
                    script_results[script] = {'step': step, 'result': 'DRAFTS_FAILED', 'executed': False}
                    continue

                drafts_data = load_json(drafts_json)
                if not drafts_data:
                    emit_deviation(f'{script_label}_drafts', 'valid drafts JSON', 'invalid or unreadable JSON', 'Branch B draft generation produced an unreadable JSON file', layer=1)
                    script_results[script] = {'step': step, 'result': 'DRAFTS_INVALID', 'executed': False}
                    continue
                figures_total = int(drafts_data.get('figures_total') or 0)
                figures_drafted = int(drafts_data.get('figures_drafted') or 0)
                draft_result = drafts_data.get('result', 'UNKNOWN')
                if figures_total > 0 and figures_drafted == 0:
                    emit_deviation(
                        f'{script_label}_drafts',
                        'figures_drafted > 0 when figures_total > 0',
                        f'figures_total={figures_total}, figures_drafted={figures_drafted}, result={draft_result}',
                        json.dumps(drafts_data.get('errors', []))[:500],
                        layer=1
                    )
                    script_results[script] = {'step': step, 'result': 'DRAFTS_EMPTY', 'executed': False}
                    continue

                # Step B3: generate review report
                # generate_alt_text_review_report.py writes the pre-approved map
                # directly via --map-out, and produces the HTML review report.
                rc_review, out_review, _ = run(
                    [REMEDIATION_PYTHON, TOOLS/'repair'/'generate_alt_text_review_report.py',
                     str(auto_pdf),
                     '--draft',   str(drafts_json),
                     '--out',     str(review_html),
                     '--map-out', str(ALT_MAP_JOB)],
                    f'{script_label}_review'
                )

                if not ALT_MAP_JOB.exists():
                    # Fallback: copy drafts directly as approved map
                    shutil.copy2(drafts_json, ALT_MAP_JOB)
                    emit('REPAIR', f'{script_label}_review', 'WARN',
                         note='Review report failed — drafts auto-approved directly')
                else:
                    emit('REPAIR', f'{script_label}_review', 'PASS',
                         note=f'Review HTML: {review_html}')

                alt_branch = 'A_LOCAL'

                # Step B4: apply approved map
                rc, out, err = run(
                    [REMEDIATION_PYTHON, script_path, auto_pdf, output_pdf,
                     '--alt-map', ALT_MAP_JOB, '--language', LANGUAGE],
                    f'{script_label}_apply'
                )

                # Step B5: copy to asset library for future runs
                asset_dir = WORKSPACE / 'assets' / 'alt_maps'
                asset_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ALT_MAP_JOB,
                             asset_dir / f'{SAFE_BASE}_alt_map_approved.json')

        # ── Special handling: fix_metadata_xmp_parity ────────────────────────
        elif 'fix_metadata_xmp_parity' in script:
            try:
                metadata_inputs = ensure_metadata_inputs_for_repair(iteration_pdf)
                emit('REPAIR', 'metadata_inputs', 'PASS', data={
                    'source': metadata_inputs.get('source'),
                    'title': metadata_inputs.get('title'),
                    'subject': metadata_inputs.get('subject'),
                    'keywords': metadata_inputs.get('keywords'),
                })
            except Exception as e:
                out = json.dumps({
                    'result': 'MISSING_REQUIRED_ARGS',
                    'error': f'Could not generate metadata inputs: {type(e).__name__}: {e}',
                })
                err = ''
                rc = 1
                try:
                    (AUDIT_DIR / 'metadata_inputs.json').write_text(json.dumps({
                        'result': 'ERROR',
                        'error': f'{type(e).__name__}: {e}',
                        'ticket': TICKET,
                        'basename': BASENAME,
                        'source': 'hermes_gateway',
                    }, indent=2))
                except Exception:
                    pass
            else:
                rc, out, err = run(
                    [REMEDIATION_PYTHON, script_path, iteration_pdf, output_pdf,
                     '--title',    args.title,
                     '--subject',  args.subject,
                     '--keywords', args.keywords,
                     '--language', LANGUAGE],
                    script_label
                )

        # ── All other scripts ─────────────────────────────────────────────────
        else:
            rc, out, err = run(
                [REMEDIATION_PYTHON, script_path, iteration_pdf, output_pdf],
                script_label
            )

        # ── Layer 1: execution check ──────────────────────────────────────────
        step_data = None
        try:
            step_data = json.loads(out)
        except Exception:
            pass
        this_result = get_result(step_data) if step_data else ('PASS' if rc == 0 else 'ERROR')

        if rc != 0 and not is_pass(this_result):
            # Resolved contract decision #2 (RESIDUAL_AND_CAPTURE_CONTRACT.md):
            # PARTIAL with a valid output PDF is progress, not failure. The
            # chain advances on the improved file and the post-repair residual
            # remains the judge of whether the rule actually cleared. This is
            # deliberately NOT routed through emit_deviation: deviations floor
            # the verdict at REVIEW_REQUIRED, which would contradict
            # residual-is-the-judge for a partial repair that fully clears its
            # rule. The advisory lives in the stream and in script_results.
            if this_result == 'PARTIAL' and output_pdf.exists():
                emit('REPAIR', script_label, 'PARTIAL',
                     data={'iteration': iteration,
                           'output': str(output_pdf),
                           'advisory': 'partial_progress_advanced',
                           'detail': (step_data.get('reason')
                                      or step_data.get('error') or ''
                                      )[:300] if step_data else ''})
                script_results[script] = {'step': step, 'result': 'PARTIAL',
                                          'executed': True, 'partial': True}
                iteration_pdf = output_pdf
                continue
            emit_deviation(script_label, 'exit_code=0 or PASS result',
                           f'exit_code={rc}, result={this_result}',
                           step_data.get('error', err[:300]) if step_data else err[:300],
                           layer=1)
            script_results[script] = {'step': step, 'result': this_result, 'executed': False}
            continue

        if not output_pdf.exists():
            emit_deviation(script_label,
                           f'output_pdf exists at {output_pdf}',
                           'output_pdf missing',
                           f'Script exited {rc} but did not produce output file',
                           layer=1)
            script_results[script] = {'step': step, 'result': this_result, 'executed': False}
            continue

        emit('REPAIR', script_label, this_result,
             data={'iteration': iteration, 'output': str(output_pdf)})

        script_results[script] = {'step': step, 'result': this_result, 'executed': True}
        # Advance PDF for this iteration
        iteration_pdf = output_pdf

    # ── End of iteration — validate ───────────────────────────────────────────
    # If at least one script produced a new PDF, validate. Otherwise (every
    # script in this iteration failed Layer 1), we still need to advance
    # counters and queue strategy fallbacks — but skip the veraPDF check
    # since the PDF didn't change.
    pdf_advanced = (iteration_pdf != current_pdf)

    if pdf_advanced and not args.dry_run:
        emit('VALIDATE', f'iteration_{iteration}', 'RUNNING')
        remaining_failures, pres_result = run_validate_cycle(iteration_pdf, iteration)
        remaining_rule_ids = {f['rule_id'] for f in remaining_failures}
    else:
        remaining_failures   = []
        pres_result          = 'SKIPPED'
        # When no PDF was produced, treat all previously-failing rules as still failing
        remaining_rule_ids = set()
        for step in unresolved_scripts:
            for r in step['rules_addressed']:
                remaining_rule_ids.add(r)
        if not pdf_advanced:
            emit('VALIDATE', f'iteration_{iteration}', 'SKIPPED',
                 note='No script produced an output PDF this iteration. Counters and fallbacks still applied.')

    write_strategy_log(JOB)

    # Build next iteration's unresolved_scripts list, deduplicated by script.
    next_steps_by_script = {}

    for step in unresolved_scripts:
        script   = step['repair_script']
        rule_ids = step['rules_addressed']
        sr       = script_results.get(script)

        # Decide what failure_reason to record for rules whose script failed
        # or didn't produce a passing rule. Three cases:
        #   - script not executed (NOT_FOUND / cap-skipped) — script_results missing
        #   - script executed but exited with error or no output — sr['executed']=False
        #   - script executed cleanly but rule still appears in veraPDF post — rule_persists
        if sr is None:
            # Script was skipped this iteration. The only path to sr=None is
            # the early per-rule cap check, which already emitted
            # per_rule_cap_reached for all addressed rules. Don't requeue.
            continue

        if not sr.get('executed'):
            # Execution failed (script error, missing output, NOT_FOUND, etc).
            # Increment per-rule counters and fall through to next strategy.
            fail_reason = f'execution_failed:{sr.get("result", "UNKNOWN")}'
            still_failing = list(rule_ids)
            resolved      = []
        else:
            this_script_result = sr['result']
            still_failing = [r for r in rule_ids if r in remaining_rule_ids]
            resolved      = [r for r in rule_ids if r not in remaining_rule_ids]
            # Script self-reported success but rule still present in veraPDF post
            fail_reason   = 'rule_still_present_after_repair' \
                            if is_pass(this_script_result) \
                            else f'script_result:{this_script_result}'

        # Log resolved rules
        for r in resolved:
            resolved_rules.add(r)
            strategy_attempts[r].append({
                'iteration': iteration,
                'strategy':  step.get('strategy', ''),
                'script':    script,
                'result':    'PASS'
            })
            emit('VALIDATE', f'rule_resolved/{r}', 'PASS',
                 data={'iteration': iteration})

        if not still_failing:
            continue  # script's rules all resolved — don't queue for next iter

        # Increment per-rule counters and check caps
        any_rule_can_continue = False
        for r in still_failing:
            per_rule_counts[r] += 1
            strategy_attempts[r].append({
                'iteration': iteration,
                'strategy':  step.get('strategy', ''),
                'script':    script,
                'result':    'FAIL',
                'reason':    fail_reason
            })
            if per_rule_counts[r] >= PER_RULE_CAP:
                emit_hermes_required(
                    r, '', 0, 'per_rule_cap_reached',
                    strategy_attempts.get(r, [])
                )
            else:
                any_rule_can_continue = True

        if not any_rule_can_continue:
            continue  # all still-failing rules hit the cap

        # Pick the next untried strategy from this script's all_strategies.
        all_strats = step.get('all_strategies', [])
        tried_strategies = set()
        for r in still_failing:
            for a in strategy_attempts.get(r, []):
                if a.get('strategy'):
                    tried_strategies.add(a['strategy'])

        remaining_strats = [s for s in all_strats
                            if s.get('strategy', '') not in tried_strategies]

        if remaining_strats:
            next_step = dict(step)
            next_strat = remaining_strats[0]
            next_step['repair_script']  = next_strat.get('repair_script', script)
            next_step['strategy']       = next_strat.get('strategy', '')
            # Keep the full remaining list (minus the one we just picked)
            # so the next iteration's fallback computation still sees them.
            next_step['all_strategies'] = remaining_strats[1:]
            next_steps_by_script[next_step['repair_script']] = next_step
        else:
            for r in still_failing:
                if per_rule_counts[r] < PER_RULE_CAP:
                    emit_hermes_required(
                        r, '', 0, 'all_strategies_exhausted',
                        strategy_attempts.get(r, [])
                    )

    unresolved_scripts = list(next_steps_by_script.values())
    current_pdf        = iteration_pdf if pdf_advanced else current_pdf

    if pdf_advanced:
        emit('VALIDATE', f'iteration_{iteration}', 'COMPLETE',
             data={'resolved_cumulative': len(resolved_rules),
                   'still_failing':       len(remaining_rule_ids),
                   'preservation':        pres_result})

if total_iterations >= JOB_HARD_CAP:
    emit('REPAIR', 'job_hard_cap', 'ESCALATION',
         note=f'Job reached {JOB_HARD_CAP} iteration hard cap. Forcing termination.')
    for step in unresolved_scripts:
        for r in step['rules_addressed']:
            emit_hermes_required(r, '', 0, 'job_hard_cap_reached',
                                   strategy_attempts.get(r, []))

FINAL_PDF = current_pdf

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 6 — Post-repair validation
# ─────────────────────────────────────────────────────────────────────────────

emit('VALIDATE', 'final_verapdf', 'RUNNING')
run(['bash', TOOLS/'audit'/'run_verapdf_profiles.sh',
     VERAPDF_BIN, PROFILES, FINAL_PDF, AUDIT_DIR],
    'verapdf_final')

for src, dst in [
    (AUDIT_DIR/'verapdf_pdfua_ua1.xml',           AUDIT_DIR/'verapdf_post_pdfua1.xml'),
    (AUDIT_DIR/'verapdf_wcag_2_2_machine.xml',    AUDIT_DIR/'verapdf_post_wcag.xml'),
    (AUDIT_DIR/'verapdf_iso_32000_1_tagged.xml',  AUDIT_DIR/'verapdf_post_iso.xml'),
    (AUDIT_DIR/'verapdf_pdfua2.xml',              AUDIT_DIR/'verapdf_post_pdfua2.xml'),
]:
    if Path(src).exists():
        shutil.copy2(src, dst)

# Keep verapdf_summary.json as a diagnostic artifact only — it aggregates
# all profiles (informational included) and does NOT drive compliance.
# Only canonical per-profile gates (verapdf_pdfua1, verapdf_wcag,
# metadata_post, preservation_post) determine the compliance outcome.
verapdf_summary = load_json(AUDIT_DIR/'verapdf_summary.json')
emit('AUDIT', 'verapdf_summary', get_result(verapdf_summary),
     note='diagnostic artifact — does not drive compliance outcome')

def _verapdf_xml_result(path):
    """Return PASS / FAIL / UNKNOWN from a veraPDF profile XML file."""
    try:
        import xml.etree.ElementTree as ET
        for _, elem in ET.iterparse(str(path), events=('end',)):
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag in ('validationReport', 'arlingtonReport'):
                if elem.get('isCompliant', 'true').lower() == 'true':
                    return 'PASS'
                for rule in elem.iter():
                    rtag = rule.tag.split('}')[-1] if '}' in rule.tag else rule.tag
                    if rtag == 'rule':
                        failed = int(rule.get('failedChecks', rule.get('deviations', 0)))
                        if failed > 0:
                            return 'FAIL'
                return 'PASS'
    except Exception as e:
        # An unreadable report is an execution signal, not a quiet UNKNOWN:
        # UNKNOWN is not in PASS_CODES, so it silently drives a critical FAIL.
        # Surface the real cause (missing file, stderr-contaminated XML, etc).
        emit_deviation(
            'verapdf_xml_parse',
            f'well-formed veraPDF report XML at {path}',
            f'{type(e).__name__}: {e}',
            'Report XML unreadable -- gate recorded as UNKNOWN (non-pass). '
            'Check the matching .stderr sidecar and that veraPDF ran.',
            layer=1,
        )
        return 'UNKNOWN'
    return 'UNKNOWN'

gate_results['verapdf_pdfua1'] = _verapdf_xml_result(AUDIT_DIR/'verapdf_post_pdfua1.xml')
gate_results['verapdf_wcag']   = _verapdf_xml_result(AUDIT_DIR/'verapdf_post_wcag.xml')
if (AUDIT_DIR/'verapdf_post_iso.xml').exists():
    gate_results['verapdf_iso'] = _verapdf_xml_result(AUDIT_DIR/'verapdf_post_iso.xml')
if (AUDIT_DIR/'verapdf_post_pdfua2.xml').exists():
    gate_results['verapdf_pdfua2'] = _verapdf_xml_result(AUDIT_DIR/'verapdf_post_pdfua2.xml')

rc2, out2, _ = run(
    [REMEDIATION_PYTHON, TOOLS/'audit'/'parse_verapdf_summary.py',
     AUDIT_DIR/'verapdf_post_pdfua1.xml',
     AUDIT_DIR/'verapdf_post_wcag.xml'],
    'parse_post_failures'
)
post_failures_path = AUDIT_DIR / 'failures_post.json'
try:
    post_failures = json.loads(out2)
    post_failures_path.write_text(json.dumps(post_failures, indent=2))
except Exception:
    post_failures = {'failures_by_rule': []}

remaining_failures = post_failures.get('failures_by_rule', [])
execution_log_path = AUDIT_DIR / 'execution_log.json'
residual_analysis_path = AUDIT_DIR / 'residual_analysis.json'
residual_analysis = None
targetable_remaining_failures = remaining_failures
try:
    execution_log = build_execution_log_from_repair_steps(
        job_dir=JOB,
        source_pdf=SOURCE_PDF,
        current_pdf=FINAL_PDF,
        repair_steps=repair_steps,
        strategy_attempts=strategy_attempts,
    )
    write_execution_log(execution_log, execution_log_path)
except Exception as e:
    execution_log = {'repair_steps': []}
    emit('AUDIT', 'execution_log', 'WARN', note=f'execution log unavailable: {type(e).__name__}: {e}')
try:
    residual_analysis = analyze_residuals(
        baseline_failures=load_json(failures_path) or {'failures_by_rule': []},
        post_failures=post_failures,
        repair_plan=load_json(plan_path) or {'repair_steps': []},
        execution_log=execution_log,
        rule_map=load_json(RULE_MAP) or {'rules': {}},
        job_dir=JOB,
        input_paths={
            'baseline_failures': failures_path,
            'post_failures': post_failures_path,
            'repair_plan': plan_path,
            'execution_log': execution_log_path,
            'rule_map': RULE_MAP,
        },
    )
    residual_analysis_path.write_text(json.dumps(residual_analysis, indent=2, sort_keys=True))
    targetable_remaining_failures = targetable_failures_from_analysis(residual_analysis, post_failures)
    emit('AUDIT', 'residual_analysis', 'PASS', data={
        'artifact': str(residual_analysis_path),
        'targetable': len(targetable_remaining_failures),
        'counts_by_outcome': residual_analysis.get('summary', {}).get('counts_by_outcome', {}),
    })
except Exception as e:
    residual_analysis = None
    targetable_remaining_failures = remaining_failures
    try:
        residual_analysis_path.write_text(json.dumps({
            'schema': 'montefiore.residual_analysis',
            'version': '1.0.0',
            'result': 'ERROR',
            'fallback': 'raw_failures_post_remaining_failures',
            'error': f'{type(e).__name__}: {e}',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }, indent=2))
    except Exception:
        pass
    emit('AUDIT', 'residual_analysis', 'WARN', note=f'falling back to raw failures_post routing: {type(e).__name__}: {e}')

hard_pass = is_pass(gate_results['verapdf_pdfua1']) and is_pass(gate_results['verapdf_wcag'])
emit('VALIDATE', 'final_verapdf', 'PASS' if hard_pass else 'FAIL',
     data={'remaining_failures': len(remaining_failures)})

# Metadata post
emit('VALIDATE', 'metadata_post', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'audit'/'metadata_xmp_parity_audit.py', FINAL_PDF,
     '--out', AUDIT_DIR/'metadata_post.json'], 'metadata_post')
meta_post        = load_json(AUDIT_DIR/'metadata_post.json')
meta_post_result = get_result(meta_post)
gate_results['metadata_post'] = meta_post_result
if not is_pass(meta_post_result):
    emit_deviation('metadata_post', 'PASS', meta_post_result,
                   str(meta_post.get('failures', []) if meta_post else ''), layer=2)
emit('VALIDATE', 'metadata_post', meta_post_result)

# Table semantics post
emit('VALIDATE', 'table_semantics_post', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'audit'/'table_semantics_audit.py', FINAL_PDF,
     '--out', AUDIT_DIR/'table_semantics_post.json'], 'table_semantics_post')
table_post        = load_json(AUDIT_DIR/'table_semantics_post.json')
table_post_result = get_result(table_post)
gate_results['table_semantics_post'] = table_post_result
emit('VALIDATE', 'table_semantics_post', table_post_result)

# Preservation post
emit('VALIDATE', 'preservation_post', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'qa'/'preservation_audit.py',
     PASS0, FINAL_PDF,
     '--out', AUDIT_DIR/'preservation_post.json'], 'preservation_post')
pres_post        = load_json(AUDIT_DIR/'preservation_post.json')
pres_post_result = get_result(pres_post)
gate_results['preservation_post'] = pres_post_result
if not is_pass(pres_post_result):
    emit_deviation('preservation_post', 'PASS', pres_post_result,
                   'Content may have been lost during repair', layer=2)
emit('VALIDATE', 'preservation_post', pres_post_result)

# Form field preservation post
emit('VALIDATE', 'form_fields_post', 'RUNNING')
run(
    [
        REMEDIATION_PYTHON,
        TOOLS / 'qa' / 'form_field_preservation_audit.py',
        SOURCE_PDF,
        FINAL_PDF,
        '--out',
        AUDIT_DIR / 'form_fields_post.json',
    ],
    'form_fields_post',
)
form_post = load_json(AUDIT_DIR / 'form_fields_post.json')
form_post_result = get_result(form_post)
gate_results['form_fields_post'] = form_post_result
if not is_pass(form_post_result):
    emit_deviation(
        'form_fields_post',
        'PASS',
        form_post_result,
        json.dumps(form_post.get('failures', []) if form_post else []),
        layer=2,
    )
emit('VALIDATE', 'form_fields_post', form_post_result)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 7 — QA
# ─────────────────────────────────────────────────────────────────────────────

emit('QA', 'render_compare', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'qa'/'render_compare.py',
     PASS0, FINAL_PDF, QA_DIR,
     '--out', AUDIT_DIR/'render_compare.json'], 'render_compare')
rc_data   = load_json(AUDIT_DIR/'render_compare.json')
rc_result = get_result(rc_data)
gate_results['render_compare'] = rc_result
emit('QA', 'render_compare', rc_result)

emit('QA', 'visual_qa', 'RUNNING')
run([REMEDIATION_PYTHON, TOOLS/'qa'/'visual_qa.py',
     FINAL_PDF, QA_DIR,
     '--out', AUDIT_DIR/'visual_qa.json'], 'visual_qa')
vqa_data   = load_json(AUDIT_DIR/'visual_qa.json')
vqa_result = get_result(vqa_data)
gate_results['visual_qa'] = vqa_result
emit('QA', 'visual_qa', vqa_result)

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 8 — Outcome determination and packaging
# ─────────────────────────────────────────────────────────────────────────────

# Residual strategy-gap phase: final validator failures that remain after
# mapped repairs must become Hermes strategy-design artifacts before outcome
# packaging. This is intentionally not a repair; it creates the reusable
# strategy-design packet and proposal for the next deterministic step.
self_extension_failures = targetable_remaining_failures if residual_analysis else remaining_failures
strategy_gap = write_residual_strategy_gap_artifacts(
    FINAL_PDF,
    self_extension_failures,
    post_failures_path,
)

# ── HERMES signal reconciliation against residual analysis (Patch 5) ────────
residual_verdict_summary = summarize_residual_analysis(JOB)
strategy_indexing_summary = summarize_strategy_indexing(JOB)
hermes_reconciliation = reconcile_hermes_signals(
    hermes_signals,
    residual_verdict_summary,
    gate_results,
)
hermes_signals_raw = hermes_reconciliation.get('raw_signals', [])
active_hermes_signals = hermes_reconciliation.get('active_actionable_signals', [])
hermes_signals = (
    hermes_reconciliation.get('active_actionable_signals', [])
    + hermes_reconciliation.get('resolved_incidental_signals', [])
    + hermes_reconciliation.get('non_targetable_residual_signals', [])
    + hermes_reconciliation.get('suppressed_zero_count_signals', [])
)
emit('PACKAGE', 'hermes_signal_reconciliation', 'PASS', data={
    'raw_emissions': hermes_reconciliation.get('raw_emissions', 0),
    'deduped': hermes_reconciliation.get('deduped_count', 0),
    'active_actionable': hermes_reconciliation.get('active_actionable_count', 0),
    'resolved_incidental': hermes_reconciliation.get('resolved_incidental_count', 0),
    'non_targetable_residual': hermes_reconciliation.get('non_targetable_residual_count', 0),
    'suppressed_zero_count': hermes_reconciliation.get('suppressed_zero_count', 0),
})
# M1B: the shared verdict module is the single source of truth for the
# outcome; no inline gate-key lists. Pre-repair gates (*_pre, verapdf_baseline)
# are excluded from the verdict input -- a failing baseline is the EXPECTED
# starting state of every remediation job and must not floor the verdict of
# the repaired document.
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
import dataclasses as _dataclasses
from tools.lib.verdict import VerdictInput, verdict as compute_shared_verdict

verdict_gate_results = {
    k: v for k, v in gate_results.items()
    if not k.endswith('_pre') and k != 'verapdf_baseline'
}
# Contrast carve-out: the contrast audit runs once, pre-repair. Unlike the
# other pre gates it is not expected-to-fail, and when render_compare proves
# the rendering did not change, the pre-repair contrast result remains valid
# for the final document. Surface it under the canonical 'contrast' gate so
# the verdict and the audit report stop showing NOT_RUN for a check that ran.
if ('contrast' not in verdict_gate_results
        and 'contrast_pre' in gate_results
        and is_pass(gate_results.get('render_compare', 'FAIL'))):
    verdict_gate_results['contrast'] = gate_results['contrast_pre']
verdict_input = VerdictInput.from_remediate_state(
    verdict_gate_results,
    active_hermes_signals,
    deviations,
    total_iterations,
    job_hard_cap=JOB_HARD_CAP,
)
if total_iterations >= JOB_HARD_CAP:
    verdict_input = _dataclasses.replace(verdict_input, has_hard_cap_exceeded=True)

# Persist the exact verdict input so status_json_writer (and any reviewer)
# can recompute the same verdict from the same facts (P2 path of the writer).
try:
    (AUDIT_DIR / 'verdict_input.json').write_text(json.dumps({
        'gates': {str(g): {'result': r.value, 'source': r.source}
                  for g, r in verdict_input.gates.items()},
        'hermes_signals_count': verdict_input.hermes_signals_count,
        'deviations_count': verdict_input.deviations_count,
        'total_iterations': verdict_input.total_iterations,
        'job_hard_cap': verdict_input.job_hard_cap,
        'has_hard_cap_exceeded': verdict_input.has_hard_cap_exceeded,
    }, indent=2))
except Exception:
    pass

try:
    _verdict_input_path = AUDIT_DIR / 'verdict_input.json'
    _verdict_payload = load_json(_verdict_input_path) or {}
    _verdict_payload['residual_analysis'] = residual_verdict_summary if 'residual_verdict_summary' in globals() else summarize_residual_analysis(JOB)
    _verdict_payload['strategy_indexing'] = strategy_indexing_summary if 'strategy_indexing_summary' in globals() else summarize_strategy_indexing(JOB)
    _verdict_payload['hermes_reconciliation'] = hermes_reconciliation if 'hermes_reconciliation' in globals() else {}
    _verdict_input_path.write_text(json.dumps(_verdict_payload, indent=2, sort_keys=True))
except Exception:
    pass
verdict_result = compute_shared_verdict(verdict_input)
overall = verdict_result.overall
critical_fails = [str(g) for g in verdict_result.critical_fails]

# Orchestrator-level refinement the shared module deliberately does not model:
# a hard compliance FAIL accompanied by unresolved HERMES_REQUIRED signals is
# an ESCALATION (strategy-design work pending), not a terminal FAIL.
escalation_upgrade = bool(critical_fails and active_hermes_signals)
if escalation_upgrade and overall == 'FAIL':
    overall = 'ESCALATION'

emit('PACKAGE', 'overall_result', overall,
     data={'critical_fails':           critical_fails,
           'blocking_qa':              [str(g) for g in verdict_result.blocking_qa],
           'informational_flags':      [str(g) for g in verdict_result.informational_flags],
           'deviations':               len(deviations),
           'hermes_signals':         len(active_hermes_signals),
           'hermes_signals_resolved_incidental': len(hermes_signals) - len(active_hermes_signals),
           'total_iterations':         total_iterations,
           'iteration_warning_issued': total_iterations >= JOB_WARN_AT,
           'verdict_source':           'shared_verdict' + ('+escalation_upgrade' if escalation_upgrade else '')})

# Write STATUS.json
emit('PACKAGE', 'status_json', 'RUNNING')

# Persist HERMES_REQUIRED signals to a sidecar that status_json_writer can read
try:
    (AUDIT_DIR / 'hermes_signals.json').write_text(
        json.dumps(hermes_signals, indent=2)
    )
except Exception:
    pass

# Persist the orchestrator's authoritative overall result so status_json_writer
# uses it directly instead of re-deriving from gate values.
try:
    (AUDIT_DIR / 'orchestrator_outcome.json').write_text(
        json.dumps({
            'overall_result':   overall,
            'critical_fails':   critical_fails,
            'total_iterations': total_iterations,
            'has_hermes':     len(active_hermes_signals) > 0,
            'escalation_upgrade': escalation_upgrade,
            'verdict': verdict_result.as_dict(), 'residual_analysis': residual_verdict_summary if 'residual_verdict_summary' in globals() else summarize_residual_analysis(JOB), 'strategy_indexing': strategy_indexing_summary if 'strategy_indexing_summary' in globals() else summarize_strategy_indexing(JOB), 'hermes_reconciliation': hermes_reconciliation if 'hermes_reconciliation' in globals() else {},
        }, indent=2)
    )
except Exception:
    pass

rc_status, out_status, err_status = run(
    [REMEDIATION_PYTHON, TOOLS/'packaging'/'status_json_writer.py', JOB,
     '--pdf', str(SOURCE_PDF)],
    'status_json',
    env={'PYTHONPATH': str(APP)},
)
if rc_status != 0:
    if overall in ('FAIL', 'ESCALATION') and rc_status == 1:
        emit(
            'PACKAGE',
            'status_json',
            'PASS',
            note='status_json_writer returned 1 for terminal FAIL/ESCALATION as expected',
        )
    else:
        emit_deviation(
            'status_json',
            'exit_code=0',
            f'exit_code={rc_status}',
            (out_status + err_status)[:2000],
            layer=1,
        )
        sys.exit(1)
else:
    emit('PACKAGE', 'status_json', 'PASS')

# Write strategy attempts log
write_strategy_log(JOB)

# ── Outcome-aware packaging ───────────────────────────────────────────────────

if overall == 'PASS':
    # Full package — remediated PDF + audit report
    emit('PACKAGE', 'package_deliverables', 'RUNNING')
    rc, out, _ = run(
        [REMEDIATION_PYTHON, TOOLS/'packaging'/'package_deliverables.py',
         JOB, FINAL_PDF,
         '--output-dir', OUT,
         '--source-pdf', str(SOURCE_PDF)],
        'package_deliverables',
        env={'PYTHONPATH': str(APP)},
    )
    pkg_data = {}
    try:
        pkg_data = json.loads(out)
    except Exception:
        pass
    emit('PACKAGE', 'package_deliverables',
         get_result(pkg_data) if pkg_data else ('PASS' if rc == 0 else 'FAIL'))

elif overall == 'REVIEW_REQUIRED':
    # Package to review/ subdirectory
    review_dir = OUT / 'review'
    review_dir.mkdir(parents=True, exist_ok=True)
    emit('PACKAGE', 'package_deliverables', 'RUNNING')
    rc, out, _ = run(
        [REMEDIATION_PYTHON, TOOLS/'packaging'/'package_deliverables.py',
         JOB, FINAL_PDF,
         '--output-dir', str(review_dir),
         '--source-pdf', str(SOURCE_PDF)],
        'package_deliverables_review',
        env={'PYTHONPATH': str(APP)},
    )
    emit('PACKAGE', 'package_deliverables', 'PASS' if rc == 0 else 'FAIL',
         note=f'Review package at {review_dir}')

elif overall in ('FAIL', 'ESCALATION'):
    # No remediated PDF — audit report and escalation report only
    failed_dir = OUT / 'failed'
    failed_dir.mkdir(parents=True, exist_ok=True)

    # Generate audit report into failed/ — no remediated PDF
    emit('PACKAGE', 'package_deliverables', 'RUNNING')
    rc, out, _ = run(
        [REMEDIATION_PYTHON, TOOLS/'packaging'/'package_deliverables.py',
         JOB, FINAL_PDF,
         '--output-dir', str(failed_dir),
         '--source-pdf', str(SOURCE_PDF),
         '--skip-pdf'],
        'package_deliverables_fail',
        env={'PYTHONPATH': str(APP)},
    )
    pkg_fail_data = {}
    try:
        pkg_fail_data = json.loads(out)
    except Exception:
        pass
    emit('PACKAGE', 'package_deliverables',
         get_result(pkg_fail_data) if pkg_fail_data else ('PASS' if rc == 0 else 'FAIL'),
         note=f'Audit report at {failed_dir}')

    # Write escalation report
    escalation_report = failed_dir / 'ESCALATION_REPORT.md'
    with open(escalation_report, 'w') as f:
        f.write(f'# Escalation Report — {TICKET}\n\n')
        f.write(f'**Job:** {JOB_NAME}  \n')
        f.write(f'**Overall result:** {overall}  \n')
        f.write(f'**Date:** {datetime.now(timezone.utc).isoformat()}  \n')
        f.write(f'**Total iterations:** {total_iterations}  \n\n')
        f.write('## Critical gate failures\n\n')
        for k in critical_fails:
            f.write(f'- `{k}`: {gate_results.get(k, "UNKNOWN")}\n')
        f.write('\n## Rules requiring agent intervention\n\n')
        for sig in hermes_signals:
            f.write(f'### {sig["rule_id"]}\n')
            f.write(f'**Reason:** {sig["reason"]}  \n')
            f.write(f'**Description:** {sig.get("description", "")}  \n')
            f.write(f'**Failures:** {sig.get("failures", 0)}  \n')
            attempts = sig.get('strategies_attempted', [])
            if attempts:
                f.write('**Strategies attempted:**\n')
                for a in attempts:
                    f.write(f'  - `{a.get("strategy", "unknown")}` '
                            f'({a.get("script", "")}) → {a.get("result", "?")} '
                            f'[iter {a.get("iteration", "?")}]\n')
            f.write('\n')
        f.write('## Next steps\n\n')
        f.write('Flag for operator and engineering review. ')
        f.write('Do not upload remediated PDF — document is not compliant.\n')

    emit('PACKAGE', 'escalation_report', 'PASS',
         note=f'Escalation report at {escalation_report}')

# Post-job knowledge update -- QUARANTINED to dry-run on PASS jobs only.
# Rationale (see ORCHESTRATOR_REVIEW.md S1 indexer finding and
# RESIDUAL_AND_CAPTURE_CONTRACT.md): the indexer's capture logic reads a
# deviation_log that nothing writes, keys off baseline failures rather than
# the residual, and writes new entries in the v1 flat schema (repair_script
# key) into the v2 map (strategies array) -- entries lookup_repair_plan.py
# cannot use. Live writes therefore mutate rule_repair_map.json with
# unusable or wrong knowledge and make reruns of the same document
# non-reproducible. Until the learned_strategies/residual_analysis capture
# contract is implemented, the indexer proposes only; its dry-run output is
# preserved per job as design evidence for that future work.
if overall == 'PASS':
    emit('PACKAGE', 'post_job_indexer', 'RUNNING',
         note='dry-run only -- capture contract not yet implemented')
    rc_idx, out_idx, err_idx = run(
        [REMEDIATION_PYTHON, TOOLS/'audit'/'post_job_indexer.py', JOB,
         '--map', RULE_MAP, '--dry-run'],
        'post_job_indexer',
    )
    try:
        (AUDIT_DIR / 'indexer_proposals.json').write_text(
            out_idx if out_idx else json.dumps(
                {'result': 'ERROR', 'exit_code': rc_idx, 'stderr': err_idx[:2000]}
            )
        )
    except Exception:
        pass
    emit('PACKAGE', 'post_job_indexer',
         'PASS' if rc_idx == 0 else 'WARN',
         data={'mode': 'dry_run',
               'proposals': str(AUDIT_DIR / 'indexer_proposals.json')})
else:
    emit('PACKAGE', 'post_job_indexer', 'SKIPPED',
         note=f'overall={overall} -- indexer dry-runs on PASS jobs only')

# ─────────────────────────────────────────────────────────────────────────────
# Final summary
# ─────────────────────────────────────────────────────────────────────────────

duration = (datetime.now(timezone.utc) - start_time).total_seconds()

summary = {
    'result':                overall,
    'job_dir':               str(JOB),
    'output_dir':            str(OUT),
    'source_pdf':            str(SOURCE_PDF),
    'final_pdf':             str(FINAL_PDF),
    'gates':                 gate_results,
    'deviations':            deviations,
    'hermes_signals':      hermes_signals,
    'resolved_rules':        sorted(resolved_rules),
    'total_iterations':      total_iterations,
    'iteration_warning':     total_iterations >= JOB_WARN_AT,
    'duration_secs':         round(duration, 1),
    'repair_steps_executed': len(repair_steps),
    'unknown_rules':         unknown_rules,
    'doc_tags':              doc_tags,
    'proposed_taxonomy_additions': proposed_taxonomy_additions,
}

print(json.dumps({'phase': 'COMPLETE', 'summary': summary}, indent=2), flush=True)
sys.exit(0 if overall in ('PASS', 'REVIEW_REQUIRED') else 1)
