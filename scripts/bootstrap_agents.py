"""Bootstrap PRD workflow agents and verify configuration."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import FunctionDefinition, FunctionToolDefinition
from azure.identity.aio import DefaultAzureCredential

from src.api.prd_workflow import (
    MissingEnvironmentError,
    PrdWorkflow,
    WorkflowExecutionError,
    WorkflowNotReadyError,
    WorkflowResultError,
)
from src.api.search_tool import SearchTool

try:
    # Allow execution as a script or via `python -m scripts.bootstrap_agents`.
    from scripts.verify_agent import _initialize_env
except ModuleNotFoundError:  # pragma: no cover - fallback when running directly
    from verify_agent import _initialize_env


AGENT_SPECS = [
    {
        "name": "product-researcher",
        "env_var": "PRD_RESEARCHER_AGENT_ID",
        "instructions": (
            "You are a Product Researcher. Perform market and user research for the feature idea. "
            "If helpful, call the SearchTool to gather evidence. Respond with JSON only using the keys: "
            "`personas` (list), `market_insights` (string), `competitive_analysis` (string), "
            "`research_summary` (string), `prd_outline` (list), and `sources` (list of objects with `title`, `url`)."
        ),
        "uses_search": True,
    },
    {
        "name": "product-strategy",
        "env_var": "PRD_STRATEGY_AGENT_ID",
        "instructions": (
            "You are a Product Strategy Agent. Use the prior research output to craft product vision and strategy. "
            "Respond with JSON only using the keys: `vision` (string), `goals` (list), `non_goals` (list), "
            "`success_metrics` (list), `strategic_alignment` (string), and `assumptions` (list)."
        ),
        "uses_search": False,
    },
    {
        "name": "technical-architect",
        "env_var": "PRD_TECH_ARCH_AGENT_ID",
        "instructions": (
            "You are a Technical Architect. Evaluate feasibility and plan execution based on the prior outputs. "
            "Respond with JSON only using the keys: `technical_feasibility` (string), "
            "`recommended_approach` (string), `milestones` (list), `risks_dependencies` (list), "
            "`effort_estimate` (string), and `architecture_notes` (string)."
        ),
        "uses_search": False,
    },
]


def _sanitize(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, inner in value.items():
            new_key = " ".join(str(key).split()).strip() if isinstance(key, str) else key
            sanitized[new_key] = _sanitize(inner)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        compact = " ".join(value.split())
        return compact.strip()
    return value


def _detect_azd_env_name() -> Optional[str]:
    explicit = os.getenv("AZURE_ENV_NAME")
    if explicit:
        return explicit

    config_path = Path(".azure") / "config.json"
    if not config_path.exists():
        return None
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    defaults = data.get("defaults", {})
    candidate = defaults.get("environment") or data.get("defaultEnvironment")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


def _resolve_env_path() -> Optional[Path]:
    azure_env = _detect_azd_env_name()
    if not azure_env:
        return None
    return Path(".azure") / azure_env / ".env"


def _update_env_file(path: Path, updates: dict[str, str]) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    keys = set(updates.keys())
    updated_lines: list[str] = []
    for line in lines:
        if not line or line.strip().startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            updated_lines.append(f"{key}={updates[key]}")
            keys.discard(key)
        else:
            updated_lines.append(line)

    for key in sorted(keys):
        updated_lines.append(f"{key}={updates[key]}")

    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def _build_search_tool_definition() -> FunctionToolDefinition:
    search_tool = SearchTool().as_function()
    spec = search_tool.to_json_schema_spec()["function"]
    function_def = FunctionDefinition(
        name=spec["name"],
        description=spec.get("description"),
        parameters=spec["parameters"],
    )
    return FunctionToolDefinition(function=function_def)


async def _bootstrap(feature_idea: Optional[str], output: Optional[Path]) -> int:
    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT") or os.getenv("AIFOUNDRY_PROJECT_ENDPOINT")
    if not project_endpoint:
        print(
            "Missing environment configuration: Set AZURE_AI_PROJECT_ENDPOINT or AIFOUNDRY_PROJECT_ENDPOINT.",
            file=sys.stderr,
        )
        return 1

    model_deployment = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.getenv("PRD_MODEL_DEPLOYMENT_NAME")
    if not model_deployment:
        print(
            "Missing environment configuration: Set AZURE_AI_MODEL_DEPLOYMENT_NAME or PRD_MODEL_DEPLOYMENT_NAME.",
            file=sys.stderr,
        )
        return 1

    env_updates: dict[str, str] = {}
    credential = DefaultAzureCredential()
    search_tool = _build_search_tool_definition()

    async with credential:
        async with AgentsClient(endpoint=project_endpoint, credential=credential) as client:
            existing_agents: dict[str, str] = {}
            async for agent in client.list_agents():
                if agent.name:
                    existing_agents[agent.name] = str(agent.id)

            for spec in AGENT_SPECS:
                agent_id = os.getenv(spec["env_var"]) or existing_agents.get(spec["name"])
                tools = [search_tool] if spec["uses_search"] else []
                if agent_id:
                    await client.update_agent(
                        agent_id,
                        model=model_deployment,
                        name=spec["name"],
                        instructions=spec["instructions"],
                        tools=tools or None,
                    )
                else:
                    agent = await client.create_agent(
                        model=model_deployment,
                        name=spec["name"],
                        instructions=spec["instructions"],
                        tools=tools or None,
                    )
                    agent_id = str(agent.id)

                if not agent_id:
                    print(f"Failed to resolve agent id for {spec['name']}", file=sys.stderr)
                    return 1

                env_updates[spec["env_var"]] = agent_id
                os.environ[spec["env_var"]] = agent_id

    env_path = _resolve_env_path()
    if env_path is None:
        print("Warning: unable to determine azd environment path; skipping .env update.")
    else:
        _update_env_file(env_path, env_updates)
        print(f"Updated {env_path} with agent IDs.")

    workflow = PrdWorkflow()
    try:
        await workflow.startup()
    except MissingEnvironmentError as exc:
        print(f"Missing environment configuration: {exc}", file=sys.stderr)
        return 1

    print("Workflow initialized successfully.")
    print(json.dumps(workflow.environment_snapshot(), indent=2))

    if not feature_idea:
        await workflow.shutdown()
        return 0

    try:
        result, trace = await workflow.build_prd_with_trace(feature_idea)
    except (WorkflowNotReadyError, WorkflowExecutionError, WorkflowResultError) as exc:
        print(f"Workflow execution failed: {exc}", file=sys.stderr)
        await workflow.shutdown()
        return 1

    await workflow.shutdown()

    print("\nSample PRD result:")
    print(json.dumps(_sanitize(result), indent=2))

    if output:
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Saved workflow output to {output}")

    if trace.messages:
        print("\nParticipant trace:")
        for executor_id, messages in trace.messages.items():
            print(f"\n[{executor_id}]")
            combined = " ".join(part.strip() for part in messages if part.strip())
            if not combined:
                continue

            try:
                parsed = json.loads(combined)
            except json.JSONDecodeError:
                normalized = combined.replace('" \n', '" ').replace('\n "', ' "').replace('\n', ' ')
                normalized = re.sub(r"\s+", " ", normalized).strip()
                for symbol in [",", ":", "{", "}", "[", "]"]:
                    normalized = normalized.replace(f" {symbol}", symbol).replace(f"{symbol} ", symbol)
                try:
                    parsed = json.loads(normalized)
                except json.JSONDecodeError:
                    print(normalized)
                else:
                    print(json.dumps(_sanitize(parsed), indent=2))
            else:
                print(json.dumps(_sanitize(parsed), indent=2))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize PRD agents and optionally warm up the PRD workflow."
    )
    parser.add_argument(
        "--feature-idea",
        help="Optional feature idea to execute as a warm-up run.",
    )
    parser.add_argument(
        "--env-file",
        help="Optional path to an env file to load before initialization.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional file path to write the warm-up result as JSON.",
    )

    args = parser.parse_args()

    if args.output and args.output.is_dir():
        print("--output must reference a file, not a directory.", file=sys.stderr)
        return 1

    _initialize_env(args.env_file)

    return asyncio.run(
        _bootstrap(args.feature_idea.strip() if args.feature_idea else None, args.output)
    )


if __name__ == "__main__":
    raise SystemExit(main())
