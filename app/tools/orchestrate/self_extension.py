#!/usr/bin/env python3
"""
self_extension.py

Support utilities for the PDF/UA self-extension loop.

Patch 0 is intentionally isolated:
- no import from remediate.py, because remediate.py executes the pipeline at
  import time;
- no mutation of PDFs, rule maps, repair plans, or orchestrator state;
- only env/config resolution, throttling/budget primitives, a bounded Hermes
  gateway probe, and canonical generated-script naming helpers.

Later patches can import this module from the residual self-extension executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ENV_PATH = Path("/opt/data/.env")
DEFAULT_THROTTLE_STATE = Path("/tmp/hermes_self_extension_throttle.json")


class SelfExtensionError(RuntimeError):
    """Base exception for self-extension support failures."""


class SelfExtensionConfigError(SelfExtensionError):
    """Raised when required gateway/config values are unavailable."""


class SelfExtensionBudgetExceeded(SelfExtensionError):
    """Raised when a configured self-extension call budget is exhausted."""


def clean_text(value: Any) -> str:
    """Collapse whitespace for compact JSON artifacts and probe matching."""

    return " ".join(str(value or "").split()).strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int, minimum: Optional[int] = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def env_float(name: str, default: float, minimum: Optional[float] = None) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def read_env_file(path: Path, allowed: Iterable[str]) -> Dict[str, str]:
    """Read selected key/value pairs from a simple dotenv file."""

    allowed_set = set(allowed)
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed_set:
            continue

        values[key] = value.strip().strip('"').strip("'")

    return values


def load_gateway_env(env_path: Path = ENV_PATH) -> Dict[str, str]:
    """
    Resolve Hermes gateway-facing values without selecting provider models.

    This mirrors remediate.py's gateway contract while staying import-safe.
    Provider keys and concrete provider model selection remain owned by Hermes.
    """

    allowed = {
        "API_SERVER_KEY",
        "API_SERVER_PORT",
        "HERMES_GATEWAY_BASE_URL",
        "API_SERVER_MODEL_NAME",
    }
    values = {key: os.environ.get(key, "") for key in allowed}

    try:
        file_values = read_env_file(env_path, allowed)
    except OSError:
        file_values = {}

    for key, value in file_values.items():
        if not values.get(key):
            values[key] = value

    return values


@dataclass(frozen=True)
class SelfExtensionConfig:
    """Runtime config for self-extension gateway calls."""

    allow_gateway: bool
    throttle_enabled: bool
    max_calls_per_minute: float
    max_generation_calls_per_job: int
    max_attempts_per_rule: int
    gateway_timeout_seconds: float
    max_tokens: int
    temperature: float
    gateway_base_url: str
    gateway_model: str
    gateway_api_key: str
    throttle_state_path: Path

    @classmethod
    def from_env(cls, env_path: Path = ENV_PATH) -> "SelfExtensionConfig":
        gateway_env = load_gateway_env(env_path)
        port = gateway_env.get("API_SERVER_PORT") or "8642"
        base_url = (
            gateway_env.get("HERMES_GATEWAY_BASE_URL")
            or f"http://127.0.0.1:{port}/v1"
        ).rstrip("/")

        return cls(
            allow_gateway=env_bool("HERMES_SELF_EXTENSION_ALLOW_GATEWAY", False),
            throttle_enabled=env_bool(
                "HERMES_SELF_EXTENSION_THROTTLE_ENABLED",
                False,
            ),
            max_calls_per_minute=env_float(
                "HERMES_SELF_EXTENSION_MAX_CALLS_PER_MINUTE",
                30.0,
                minimum=0.1,
            ),
            max_generation_calls_per_job=env_int(
                "HERMES_SELF_EXTENSION_MAX_GENERATION_CALLS_PER_JOB",
                10,
                minimum=0,
            ),
            max_attempts_per_rule=env_int(
                "HERMES_SELF_EXTENSION_MAX_ATTEMPTS_PER_RULE",
                3,
                minimum=1,
            ),
            gateway_timeout_seconds=env_float(
                "HERMES_SELF_EXTENSION_GATEWAY_TIMEOUT_SECONDS",
                30.0,
                minimum=1.0,
            ),
            max_tokens=env_int(
                "HERMES_SELF_EXTENSION_MAX_TOKENS",
                8000,
                minimum=64,
            ),
            temperature=env_float(
                "HERMES_SELF_EXTENSION_TEMPERATURE",
                0.0,
                minimum=0.0,
            ),
            gateway_base_url=base_url,
            gateway_model=gateway_env.get("API_SERVER_MODEL_NAME") or "Hermes Agent",
            gateway_api_key=gateway_env.get("API_SERVER_KEY") or "",
            throttle_state_path=Path(
                os.environ.get(
                    "HERMES_SELF_EXTENSION_THROTTLE_STATE",
                    str(DEFAULT_THROTTLE_STATE),
                )
            ),
        )

    def safe_dict(self) -> Dict[str, Any]:
        """Return config data safe for JSON artifacts and logs."""

        return {
            "allow_gateway": self.allow_gateway,
            "throttle_enabled": self.throttle_enabled,
            "max_calls_per_minute": self.max_calls_per_minute,
            "max_generation_calls_per_job": self.max_generation_calls_per_job,
            "max_attempts_per_rule": self.max_attempts_per_rule,
            "gateway_timeout_seconds": self.gateway_timeout_seconds,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "gateway_base_url": self.gateway_base_url,
            "gateway_model": self.gateway_model,
            "gateway_api_key_present": bool(self.gateway_api_key),
            "throttle_state_path": str(self.throttle_state_path),
        }


def canonical_rule_slug(rule_id: str) -> str:
    """
    Convert a rule id into a collision-resistant generated-script slug.

    Character replacement alone can collide: "7.1" and "7_1" both become
    "7_1". A short digest of the original rule id keeps candidate and adopted
    script names stable without losing human readability.
    """

    original = str(rule_id or "").strip()
    visible = re.sub(r"[^a-z0-9]+", "_", original.lower())
    visible = re.sub(r"_+", "_", visible).strip("_")
    if not visible:
        visible = "rule"

    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:10]
    return f"{visible}_{digest}"


def generated_candidate_filename(rule_id: str, attempt: int) -> str:
    """Return a quarantined generated-script attempt filename."""

    attempt_number = max(1, int(attempt))
    return (
        f"fix_generated_{canonical_rule_slug(rule_id)}_"
        f"attempt_{attempt_number:02d}.py"
    )


def adopted_generated_filename(rule_id: str) -> str:
    """Return the later adopted generated-script filename for a rule."""

    return f"fix_generated_{canonical_rule_slug(rule_id)}.py"


def generated_repair_script_relpath(rule_id: str, attempt: Optional[int] = None) -> str:
    """
    Return the repo-relative generated repair path used by later patches.

    Attempt paths stay quarantined. Adoption should keep provenance visible by
    registering tools/repair/generated/<adopted filename> in the rule map.
    """

    filename = (
        generated_candidate_filename(rule_id, attempt)
        if attempt is not None
        else adopted_generated_filename(rule_id)
    )
    return f"tools/repair/generated/{filename}"


class SelfExtensionThrottle:
    """
    Throttle and budget primitive for self-extension LLM calls.

    The rate throttle uses a state file and, on Linux, an fcntl lock. The job
    budget is separate so the gateway probe can test connectivity without
    spending a generation-call budget slot.
    """

    def __init__(
        self,
        config: SelfExtensionConfig,
        job_dir: Optional[Path] = None,
    ) -> None:
        self.config = config
        self.job_dir = Path(job_dir) if job_dir else None

    def reserve_generation_budget(self) -> Dict[str, Any]:
        """Reserve one configured generation-call budget slot for a job."""

        max_calls = self.config.max_generation_calls_per_job
        if max_calls <= 0 or self.job_dir is None:
            return {
                "result": "SKIPPED",
                "reason": "job budget disabled or no job_dir",
            }

        path = self.job_dir / "self_extension_call_budget.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = load_json_object(path) or {}
        calls = int(data.get("generation_calls_reserved") or 0)
        if calls >= max_calls:
            raise SelfExtensionBudgetExceeded(
                "Self-extension generation call budget exhausted: "
                f"{calls}/{max_calls}"
            )

        data.update(
            {
                "generation_calls_reserved": calls + 1,
                "max_generation_calls_per_job": max_calls,
                "updated_at": time.time(),
            }
        )
        write_json_atomic(path, data)
        return {
            "result": "RESERVED",
            "generation_calls_reserved": calls + 1,
            "max_generation_calls_per_job": max_calls,
            "path": str(path),
        }

    def wait_for_rate_slot(self) -> Dict[str, Any]:
        """Reserve one throttle slot and sleep if the configured rate requires it."""

        if not self.config.throttle_enabled:
            return {"result": "SKIPPED", "reason": "throttle disabled"}

        rate = self.config.max_calls_per_minute
        interval_seconds = 60.0 / rate
        path = self.config.throttle_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_suffix(path.suffix + ".lock")

        started_at = time.time()
        with lock_path.open("a+") as lock_file:
            lock_file_exclusive(lock_file)
            try:
                data = load_json_object(path) or {}
                last_call_at = float(data.get("last_call_at") or 0.0)
                now = time.time()
                sleep_seconds = max(0.0, (last_call_at + interval_seconds) - now)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

                reserved_at = time.time()
                data.update(
                    {
                        "last_call_at": reserved_at,
                        "max_calls_per_minute": rate,
                        "interval_seconds": interval_seconds,
                        "total_slots_reserved": (
                            int(data.get("total_slots_reserved") or 0) + 1
                        ),
                    }
                )
                write_json_atomic(path, data)
            finally:
                unlock_file(lock_file)

        return {
            "result": "RESERVED",
            "max_calls_per_minute": rate,
            "elapsed_seconds": round(time.time() - started_at, 3),
            "state_path": str(path),
        }


class HermesGatewayClient:
    """Bounded OpenAI-compatible client for the Hermes gateway."""

    def __init__(
        self,
        config: SelfExtensionConfig,
        throttle: Optional[SelfExtensionThrottle] = None,
    ) -> None:
        self.config = config
        self.throttle = throttle

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        throttle: bool = True,
        reserve_budget: bool = True,
    ) -> Dict[str, Any]:
        if not self.config.allow_gateway:
            raise SelfExtensionConfigError(
                "Hermes gateway self-extension calls are disabled. "
                "Set HERMES_SELF_EXTENSION_ALLOW_GATEWAY=1 to enable."
            )
        if not self.config.gateway_api_key:
            raise SelfExtensionConfigError(
                "API_SERVER_KEY is not available from the process environment "
                "or /opt/data/.env."
            )

        throttle_record: Dict[str, Any] = {}
        if throttle and self.throttle is not None:
            throttle_record["rate"] = self.throttle.wait_for_rate_slot()
            if reserve_budget:
                throttle_record["budget"] = self.throttle.reserve_generation_budget()

        body = json.dumps(
            {
                "model": self.config.gateway_model,
                "messages": messages,
                "temperature": self.config.temperature,
                "max_tokens": max_tokens or self.config.max_tokens,
                "stream": False,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self.config.gateway_base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.gateway_api_key}",
                "Content-Type": "application/json",
            },
        )

        timeout = timeout_seconds or self.config.gateway_timeout_seconds
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        response = json.loads(raw)
        message = response["choices"][0]["message"]
        content = message.get("content") or message.get("reasoning_content") or ""
        return {
            "result": "PASS",
            "content": content,
            "response_model": response.get("model", self.config.gateway_model),
            "gateway_base_url": self.config.gateway_base_url,
            "gateway_model": self.config.gateway_model,
            "throttle": throttle_record,
            "usage": response.get("usage", {}),
        }


def run_gateway_probe(
    *,
    job_dir: Optional[Path] = None,
    out_path: Optional[Path] = None,
    config: Optional[SelfExtensionConfig] = None,
) -> Dict[str, Any]:
    """
    Make a tiny bounded Hermes gateway request.

    This is the lowest-cost test for whether the remediation runtime can make a
    non-interactive /v1/chat/completions call through the Hermes gateway.
    """

    cfg = config or SelfExtensionConfig.from_env()
    record: Dict[str, Any] = {
        "probe": "self_extension_gateway",
        "config": cfg.safe_dict(),
        "timestamp": time.time(),
    }

    if not cfg.allow_gateway:
        record.update(
            {
                "result": "SKIPPED",
                "reason": "HERMES_SELF_EXTENSION_ALLOW_GATEWAY is not enabled",
            }
        )
        maybe_write_probe(out_path, record)
        return record

    prompt = (
        "This is a bounded health probe from the PDF/UA self-extension runtime. "
        "Return exactly this token and no other text:\n"
        "SELF_EXTENSION_GATEWAY_PROBE_OK"
    )

    try:
        throttle = SelfExtensionThrottle(cfg, job_dir=job_dir)
        client = HermesGatewayClient(cfg, throttle=throttle)
        response = client.chat_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=64,
            timeout_seconds=cfg.gateway_timeout_seconds,
            throttle=True,
            reserve_budget=False,
        )
        content = clean_text(response.get("content", ""))
        ok = content == "SELF_EXTENSION_GATEWAY_PROBE_OK"
        record.update(
            {
                "result": "PASS" if ok else "FAIL",
                "reason": "probe token matched" if ok else "probe token mismatch",
                "content": content[:500],
                "response_model": response.get("response_model"),
                "gateway_base_url": response.get("gateway_base_url"),
                "gateway_model": response.get("gateway_model"),
                "throttle": response.get("throttle"),
                "usage": response.get("usage", {}),
            }
        )
    except urllib.error.HTTPError as exc:
        body = read_http_error_body(exc)
        record.update(
            {
                "result": "FAIL",
                "reason": f"HTTPError {exc.code}",
                "error": body[:2000],
            }
        )
    except Exception as exc:
        record.update(
            {
                "result": "FAIL",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )

    maybe_write_probe(out_path, record)
    return record


def read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def maybe_write_probe(path: Optional[Path], record: Dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, record)


def load_json_object(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def lock_file_exclusive(handle: Any) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError):
        return


def unlock_file(handle: Any) -> None:
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError):
        return


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PDF/UA self-extension support helpers",
    )
    sub = parser.add_subparsers(dest="command")

    probe = sub.add_parser(
        "probe",
        help="Run a bounded Hermes gateway self-extension probe",
    )
    probe.add_argument(
        "--job-dir",
        default="",
        help="Optional job dir for throttle/budget artifacts",
    )
    probe.add_argument(
        "--out",
        default="",
        help="Optional JSON artifact path for the probe result",
    )

    slug = sub.add_parser(
        "slug",
        help="Print canonical generated-script names for a rule id",
    )
    slug.add_argument("rule_id")
    slug.add_argument(
        "--attempt",
        type=int,
        default=1,
        help="Attempt number for candidate filename output",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    ns = parser.parse_args(argv)

    if ns.command == "slug":
        output = {
            "rule_id": ns.rule_id,
            "slug": canonical_rule_slug(ns.rule_id),
            "candidate_filename": generated_candidate_filename(
                ns.rule_id,
                ns.attempt,
            ),
            "candidate_relpath": generated_repair_script_relpath(
                ns.rule_id,
                ns.attempt,
            ),
            "adopted_filename": adopted_generated_filename(ns.rule_id),
            "adopted_relpath": generated_repair_script_relpath(ns.rule_id),
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0

    if ns.command == "probe":
        job_dir = Path(ns.job_dir) if ns.job_dir else None
        out_path = Path(ns.out) if ns.out else None
        result = run_gateway_probe(job_dir=job_dir, out_path=out_path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("result") in {"PASS", "SKIPPED"} else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
