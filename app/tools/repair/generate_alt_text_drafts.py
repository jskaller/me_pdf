#!/usr/bin/env python3
"""
generate_alt_text_drafts.py

Generate draft alt text for Figure elements that received placeholder text
during fix_figure_alt_text.py auto-mode repair.

Default runtime:
  VISION_TOOLS_MODE=hermes

In default mode this script calls the local Hermes OpenAI-compatible gateway,
so the PDF pipeline follows the live Hermes runtime configured by the admin
console.

Debug runtime:
  VISION_TOOLS_MODE=provider

Provider mode preserves the older direct-provider behavior for explicit tests.
"""

import argparse
import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import fitz
except Exception as e:
    print(json.dumps({"result": "ERROR", "error": f"PyMuPDF unavailable: {e}"}))
    sys.exit(2)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def safe_body_snippet(raw: bytes, limit: int = 600) -> str:
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = repr(raw)
    return text[:limit]


def resolve_runtime() -> Dict[str, Any]:
    mode = os.environ.get("VISION_TOOLS_MODE", "hermes").strip().lower() or "hermes"
    timeout = env_int("VISION_PROVIDER_TIMEOUT", 120)
    retries = max(1, env_int("VISION_PROVIDER_RETRIES", 1))

    if mode == "provider":
        base_url = (
            os.environ.get("VISION_PROVIDER_BASE_URL")
            or os.environ.get("PRIMARY_PROVIDER_BASE_URL")
            or ""
        ).rstrip("/")
        api_key = (
            os.environ.get("VISION_PROVIDER_API_KEY")
            or os.environ.get("PRIMARY_PROVIDER_API_KEY")
            or ""
        )
        model = os.environ.get("VISION_MODEL", "")
        if not base_url or not api_key or not model:
            raise RuntimeError(
                "Provider vision model not configured. Set VISION_PROVIDER_BASE_URL "
                "(or PRIMARY_PROVIDER_BASE_URL), VISION_PROVIDER_API_KEY "
                "(or PRIMARY_PROVIDER_API_KEY), and VISION_MODEL; or use "
                "VISION_TOOLS_MODE=hermes."
            )
        return {
            "runtime": "provider",
            "mode": mode,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "timeout": timeout,
            "retries": retries,
        }

    if mode != "hermes":
        raise RuntimeError(
            f"Unsupported VISION_TOOLS_MODE={mode!r}. Use 'hermes' or 'provider'."
        )

    port = os.environ.get("API_SERVER_PORT", "8642")
    base_url = os.environ.get("HERMES_GATEWAY_BASE_URL", f"http://127.0.0.1:{port}/v1").rstrip("/")
    api_key = os.environ.get("API_SERVER_KEY", "")
    model = os.environ.get("API_SERVER_MODEL_NAME", "Hermes Agent")

    if not api_key:
        raise RuntimeError(
            "Hermes gateway is not configured. Set API_SERVER_KEY in root .env."
        )

    return {
        "runtime": "hermes_gateway",
        "mode": mode,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout": timeout,
        "retries": retries,
    }


def post_chat_completion(runtime: Dict[str, Any], messages: list) -> str:
    endpoint = runtime["base_url"].rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": runtime["model"],
            "max_tokens": 300,
            "temperature": 0.0,
            "stream": False,
            "messages": messages,
        }
    ).encode("utf-8")

    last_error: Optional[Exception] = None
    for attempt in range(1, runtime["retries"] + 1):
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {runtime['api_key']}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=runtime["timeout"]) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            message = data["choices"][0]["message"]
            return (message.get("content") or "").strip()
        except urllib.error.HTTPError as e:
            body = safe_body_snippet(e.read())
            raise RuntimeError(
                f"HTTP {e.code} from {endpoint}: {body}"
            ) from e
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            last_error = e
            if attempt < runtime["retries"]:
                time.sleep(min(2 * attempt, 5))
                continue
            raise RuntimeError(
                f"Request to {endpoint} failed after {attempt} attempt(s): "
                f"{type(e).__name__}: {e}"
            ) from e
        except Exception as e:
            last_error = e
            raise RuntimeError(f"Vision request failed: {type(e).__name__}: {e}") from e

    raise RuntimeError(f"Vision request failed: {last_error}")


def render_figure_thumbnail(doc: Any, page_num: int, dpi: int) -> Optional[str]:
    try:
        page = doc[page_num]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return base64.b64encode(pix.tobytes("png")).decode("utf-8")
    except Exception:
        return None


def build_user_text(figure_index: int, instruction: str = "") -> str:
    if instruction:
        return (
            f"This is Figure {figure_index + 1} from a clinical healthcare PDF document. "
            f"Generate alt text following this instruction: {instruction}. "
            "Return only the alt text string, nothing else."
        )

    return (
        f"This is Figure {figure_index + 1} from a clinical healthcare PDF document. "
        "Write a concise, accurate alt text description for this image. "
        "Requirements: describe what the image shows (chart type, subject, key values if "
        "readable); do not describe style or decorative elements; do not identify any "
        "people; keep under 150 characters where possible; if the image is decorative "
        "respond with exactly: DECORATIVE. Return only the alt text string, nothing else."
    )


def call_vision_model(runtime: Dict[str, Any], image_b64: str, figure_index: int, instruction: str = "") -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                },
                {"type": "text", "text": build_user_text(figure_index, instruction)},
            ],
        }
    ]
    return post_chat_completion(runtime, messages)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--fix-output", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--instructions", default=None)
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    try:
        runtime = resolve_runtime()
    except Exception as e:
        output = {
            "result": "ERROR",
            "error": str(e),
            "runtime": os.environ.get("VISION_TOOLS_MODE", "hermes"),
        }
        print(json.dumps(output, indent=2))
        Path(args.out).write_text(json.dumps(output, indent=2))
        return 2

    runtime_public = {
        "runtime": runtime["runtime"],
        "base_url": runtime["base_url"],
        "model": runtime["model"],
        "timeout": runtime["timeout"],
        "retries": runtime["retries"],
    }

    try:
        fix_output = json.loads(Path(args.fix_output).read_text())
    except Exception as e:
        output = {"result": "ERROR", "error": f"Could not read fix output: {e}", **runtime_public}
        print(json.dumps(output, indent=2))
        Path(args.out).write_text(json.dumps(output, indent=2))
        return 2

    needs_review = fix_output.get("needs_review", [])
    if not needs_review:
        output = {
            "result": "SKIPPED",
            "note": "No figures in needs_review list — nothing to generate drafts for.",
            "figures": {},
            **runtime_public,
        }
        print(json.dumps(output, indent=2))
        Path(args.out).write_text(json.dumps(output, indent=2))
        return 0

    instructions: Dict[str, str] = {}
    if args.instructions:
        try:
            inst_data = json.loads(Path(args.instructions).read_text())
            instructions = {
                str(k): v.get("instruction", "")
                for k, v in inst_data.get("figures", {}).items()
                if isinstance(v, dict) and v.get("instruction")
            }
        except Exception as e:
            output = {"result": "ERROR", "error": f"Could not read instructions: {e}", **runtime_public}
            print(json.dumps(output, indent=2))
            Path(args.out).write_text(json.dumps(output, indent=2))
            return 2

    try:
        doc = fitz.open(args.pdf)
    except Exception as e:
        output = {"result": "ERROR", "error": f"Could not open PDF: {e}", **runtime_public}
        print(json.dumps(output, indent=2))
        Path(args.out).write_text(json.dumps(output, indent=2))
        return 2

    results: Dict[str, Any] = {}
    warnings = []
    errors = []
    generated = 0
    skipped = 0

    for item in needs_review:
        fig_idx = item.get("figure_index", 0)
        inst = instructions.get(str(fig_idx), "")

        if "page_num" in item:
            page_num = item["page_num"]
            page_resolution = item.get("page_resolution", "stored")
        else:
            legacy_xref = item.get("xref", 0)
            xref_to_page = {}
            for pn in range(len(doc)):
                for img_info in doc[pn].get_images(full=True):
                    ix = img_info[0]
                    if ix not in xref_to_page:
                        xref_to_page[ix] = pn
            page_num = xref_to_page.get(legacy_xref, 0)
            page_resolution = "legacy_xref_fallback"
            warnings.append(
                {
                    "figure_index": fig_idx,
                    "warning": (
                        f"needs_review entry for figure {fig_idx} has no page_num — "
                        f"falling back to legacy xref lookup (struct xref {legacy_xref}). "
                        "Re-run fix_figure_alt_text.py to regenerate with correct page numbers."
                    ),
                }
            )

        thumb_b64 = render_figure_thumbnail(doc, page_num, args.dpi)
        if thumb_b64 is None:
            errors.append(
                {
                    "figure_index": fig_idx,
                    "page_num": page_num,
                    "error": f"Could not render page {page_num} — figure skipped",
                }
            )
            skipped += 1
            continue

        try:
            draft = call_vision_model(runtime, thumb_b64, fig_idx, inst)
            if not draft:
                raise RuntimeError("Vision model returned empty content")
            results[str(fig_idx)] = {
                "figure_index": fig_idx,
                "page": page_num + 1,
                "page_resolution": page_resolution,
                "alt_text_draft": draft,
                "source": runtime["runtime"],
                "model": runtime["model"],
                "base_url": runtime["base_url"],
                "instruction": inst or None,
                "decorative": draft.strip().upper() == "DECORATIVE",
            }
            generated += 1
        except Exception as e:
            errors.append(
                {
                    "figure_index": fig_idx,
                    "page": page_num + 1,
                    "runtime": runtime["runtime"],
                    "model": runtime["model"],
                    "base_url": runtime["base_url"],
                    "timeout": runtime["timeout"],
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            skipped += 1

    doc.close()

    overall = "PASS" if not errors else ("PARTIAL" if generated > 0 else "FAIL")
    output = {
        "result": overall,
        "pdf": args.pdf,
        **runtime_public,
        "figures_total": len(needs_review),
        "figures_drafted": generated,
        "figures_skipped": skipped,
        "draft_note": (
            "All alt text in this file is DRAFT output from a vision model. "
            "Human review and approval is required via generate_alt_text_review_report.py "
            "before these descriptions are applied to the document."
        ),
        "figures": results,
        "warnings": warnings,
        "errors": errors,
    }

    print(json.dumps(output, indent=2))
    Path(args.out).write_text(json.dumps(output, indent=2))
    return 0 if overall == "PASS" else (1 if overall == "PARTIAL" else 2)


if __name__ == "__main__":
    sys.exit(main())
