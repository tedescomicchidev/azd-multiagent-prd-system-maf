"""Utility script to verify the PRD workflow responds to a feature idea.

Supports passing the feature idea either as plain text (--feature-idea) or as a Markdown file
(--feature-idea-md). Optionally writes output to a file (--output-file).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional, TextIO

if __package__ in {None, ""}:
    # Ensure repository root is importable when running as a file path.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.api.prd_workflow import (  # noqa: E402
    MissingEnvironmentError,
    PrdWorkflow,
    WorkflowExecutionError,
    WorkflowNotReadyError,
    WorkflowResultError,
)


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    print(f"Loading environment values from {path}")
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = _strip_quotes(value)
            existing = os.environ.get(key)
            if existing and existing != value:
                print(f"Overriding environment variable {key} (was '{existing}', now '{value}')")
            os.environ[key] = value


def _detect_azd_env_name() -> Optional[str]:
    explicit = os.getenv("AZURE_ENV_NAME")
    if explicit:
        return explicit

    config_path = Path(".azure") / "config.json"
    if not config_path.exists():
        return None
    try:
        import json as _json

        with config_path.open("r", encoding="utf-8") as handle:
            data = _json.load(handle)
    except (OSError, ValueError):
        return None
    defaults = data.get("defaults", {})
    candidate = defaults.get("environment") or data.get("defaultEnvironment")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


def _initialize_env(explicit_path: Optional[str]) -> None:
    candidates = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    azure_env = _detect_azd_env_name()
    if azure_env:
        candidates.append(Path(".azure") / azure_env / ".env")
    candidates.append(Path(".env"))

    for candidate in candidates:
        try:
            _load_env_file(candidate)
        except OSError as exc:
            print(f"Warning: failed to read {candidate}: {exc}")

    if "AZURE_AI_PROJECT_ENDPOINT" not in os.environ:
        legacy = os.environ.get("AIFOUNDRY_PROJECT_ENDPOINT") or os.environ.get("projectEndpoint")
        if legacy:
            print("Setting AZURE_AI_PROJECT_ENDPOINT from legacy value")
            os.environ["AZURE_AI_PROJECT_ENDPOINT"] = legacy

    if "AZURE_AI_MODEL_DEPLOYMENT_NAME" not in os.environ:
        legacy_model = os.environ.get("PRD_MODEL_DEPLOYMENT_NAME") or os.environ.get(
            "AIFOUNDRY_AGENT_MODEL"
        )
        if legacy_model:
            print("Setting AZURE_AI_MODEL_DEPLOYMENT_NAME from legacy value")
            os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"] = legacy_model


def _read_markdown_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Markdown file not found: {p}")
    if not p.is_file():
        raise OSError(f"Path is not a file: {p}")

    # utf-8-sig handles UTF-8 BOMs gracefully (common on Windows).
    text = p.read_text(encoding="utf-8-sig")

    # Normalize newlines.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Trim edges only; keep markdown formatting intact.
    return text.strip()


def _write_trace(trace, stream: TextIO) -> None:
    stream.write("\n--- Workflow trace ---\n")
    for executor_id, messages in trace.messages.items():
        stream.write(f"\n[{executor_id}]\n")
        for message in messages:
            stream.write(f"{message}\n")


async def _run_verification(
    feature_idea: str,
    show_trace: bool,
    output_file: Optional[str],
    include_trace_in_output: bool,
) -> int:
    workflow = PrdWorkflow()
    try:
        await workflow.startup()
    except MissingEnvironmentError as exc:
        print(f"Missing environment configuration: {exc}", file=sys.stderr)
        return 1

    try:
        if show_trace:
            result, trace = await workflow.build_prd_with_trace(feature_idea)
        else:
            result = await workflow.build_prd(feature_idea)
            trace = None
    except (WorkflowNotReadyError, WorkflowExecutionError, WorkflowResultError) as exc:
        print(f"Workflow execution failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await workflow.shutdown()

    payload = json.dumps(result, indent=2)

    if output_file:
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            f.write(payload)
            f.write("\n")
            if include_trace_in_output and trace is not None:
                _write_trace(trace, f)
        print(f"Wrote output to {out_path}")
    else:
        print(payload)
        if trace is not None:
            _write_trace(trace, sys.stdout)

    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the PRD workflow against a sample feature idea.")

    idea_group = parser.add_mutually_exclusive_group()
    idea_group.add_argument(
        "--feature-idea",
        default=None,
        help="Feature idea to evaluate (plain text).",
    )
    idea_group.add_argument(
        "--feature-idea-md",
        help="Path to a Markdown file containing the feature idea / context.",
    )

    parser.add_argument(
        "--env-file",
        help="Optional path to an env file to load before verification.",
    )
    parser.add_argument(
        "--show-trace",
        action="store_true",
        help="Print incremental outputs recorded during the workflow run.",
    )
    parser.add_argument(
        "--output-file",
        help="If provided, write output JSON to this file instead of stdout.",
    )
    parser.add_argument(
        "--include-trace-in-output",
        action="store_true",
        help="When --output-file is set and --show-trace is used, also write the trace to the output file.",
    )

    args = parser.parse_args(argv)

    _initialize_env(args.env_file)

    if args.feature_idea_md:
        try:
            feature_idea = _read_markdown_file(args.feature_idea_md)
        except OSError as exc:
            print(f"Error reading markdown file: {exc}", file=sys.stderr)
            return 2
    else:
        feature_idea = (args.feature_idea or "Add dark mode to our mobile app").strip()

    if not feature_idea:
        print(
            "Error: feature idea is empty. Provide --feature-idea with non-empty text "
            "or --feature-idea-md pointing to a non-empty markdown file.",
            file=sys.stderr,
        )
        return 2

    return asyncio.run(
        _run_verification(
            feature_idea=feature_idea,
            show_trace=args.show_trace,
            output_file=args.output_file,
            include_trace_in_output=args.include_trace_in_output,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
