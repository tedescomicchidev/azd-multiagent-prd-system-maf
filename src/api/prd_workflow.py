from __future__ import annotations

import json
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from agent_framework import SequentialBuilder, WorkflowOutputEvent
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential

from .search_tool import SearchTool


class MissingEnvironmentError(RuntimeError):
    """Raised when required Azure AI environment variables are absent."""


class WorkflowNotReadyError(RuntimeError):
    """Raised when the workflow has not been initialized."""


class WorkflowExecutionError(RuntimeError):
    """Raised when workflow execution fails."""


class WorkflowResultError(RuntimeError):
    """Raised when the workflow finishes without producing a result."""


@dataclass(frozen=True)
class PrdTrace:
    messages: dict[str, list[str]]


class PrdWorkflow:
    """Manages the PRD workflow lifecycle for reuse across processes."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._client: AzureAIAgentClient | None = None
        self._workflow = None
        self._env_info: dict[str, str | None] | None = None

    async def startup(self) -> None:
        if self._workflow is not None:
            return

        project_endpoint = self._resolve_project_endpoint()
        model_deployment = self._resolve_model_deployment()
        self._env_info = {
            "project_endpoint": project_endpoint,
            "model_deployment_name": model_deployment,
            "prd_researcher_agent_id": os.getenv("PRD_RESEARCHER_AGENT_ID"),
            "prd_strategy_agent_id": os.getenv("PRD_STRATEGY_AGENT_ID"),
            "prd_tech_arch_agent_id": os.getenv("PRD_TECH_ARCH_AGENT_ID"),
        }

        self._stack = AsyncExitStack()
        credential = await self._stack.enter_async_context(DefaultAzureCredential(
            exclude_shared_token_cache_credential=True
        ))
        self._client = await self._stack.enter_async_context(
            AzureAIAgentClient(credential=credential)
        )

        search_tool = SearchTool()
        participants = []
        '''
        for spec in _PARTICIPANT_SPECS:
            agent_id = os.getenv(spec["env_var"])
            client = await self._stack.enter_async_context(
                AzureAIAgentClient(
                    async_credential=credential,
                    agent_id=agent_id,
                    agent_name=spec["name"],
                )
            )
            tools = None
            if spec.get("uses_search"):
                tools = [search_tool.as_function()]
            agent = client.create_agent(
                name=spec["name"],
                instructions=spec["instructions"],
                tools=tools,
            )
            participants.append(agent)
        '''
        for spec in _PARTICIPANT_SPECS:
            tools = None
            if spec.get("uses_search"):
                tools = [search_tool.as_function()]
            if tools==None:
                agent = await self._stack.enter_async_context(
                    self._client.create_agent(name=spec["name"], instructions=spec["instructions"])
                )
            else:
                agent = await self._stack.enter_async_context(
                    self._client.create_agent(name=spec["name"], instructions=spec["instructions"], tools=tools)
                )
                
            participants.append(agent)

        self._workflow = SequentialBuilder().participants(participants).build()

    async def shutdown(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._client = None
        self._workflow = None
        self._env_info = None

    async def build_prd(self, feature_idea: str) -> dict[str, Any]:
        result, _ = await self._run(feature_idea, capture_trace=False)
        return result

    async def build_prd_with_trace(self, feature_idea: str) -> tuple[dict[str, Any], PrdTrace]:
        result, trace = await self._run(feature_idea, capture_trace=True)
        return result, PrdTrace(messages=trace)

    def environment_snapshot(self) -> dict[str, str | None]:
        if self._env_info is not None:
            return dict(self._env_info)
        return {
            "project_endpoint": os.getenv("AZURE_AI_PROJECT_ENDPOINT")
            or os.getenv("AIFOUNDRY_PROJECT_ENDPOINT"),
            "model_deployment_name": os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
            or os.getenv("PRD_MODEL_DEPLOYMENT_NAME"),
            "prd_researcher_agent_id": os.getenv("PRD_RESEARCHER_AGENT_ID"),
            "prd_strategy_agent_id": os.getenv("PRD_STRATEGY_AGENT_ID"),
            "prd_tech_arch_agent_id": os.getenv("PRD_TECH_ARCH_AGENT_ID"),
        }

    async def _run(
        self, feature_idea: str, *, capture_trace: bool
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        if self._workflow is None:
            raise WorkflowNotReadyError("Call startup() before build_prd().")

        trace: dict[str, list[str]] = {} if capture_trace else {}
        result: dict[str, Any] | None = None

        try:
            async for event in self._workflow.run_stream(feature_idea):
                executor_id = getattr(event, "executor_id", None)
                if capture_trace and executor_id:
                    text = self._stringify_event_data(event)
                    if text:
                        trace.setdefault(executor_id, []).append(text)
                if isinstance(event, WorkflowOutputEvent):
                    if capture_trace:
                        text = self._stringify_event_data(event)
                        if text:
                            trace.setdefault(executor_id or "workflow", []).append(text)
                    result = self._extract_json(event.data)
        except Exception as exc:  # pragma: no cover - propagated to caller
            raise WorkflowExecutionError(str(exc)) from exc

        if result is None:
            raise WorkflowResultError("Workflow completed without emitting a result.")

        participant_outputs = self._extract_participant_outputs(trace)
        composed = self._compose_prd(feature_idea, participant_outputs)
        composed["workflow_output"] = result
        return composed, trace

    @staticmethod
    def _resolve_project_endpoint() -> str:
        endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        if endpoint:
            return endpoint
        legacy = os.getenv("AIFOUNDRY_PROJECT_ENDPOINT")
        if legacy:
            os.environ.setdefault("AZURE_AI_PROJECT_ENDPOINT", legacy)
            return legacy
        raise MissingEnvironmentError(
            "Set AZURE_AI_PROJECT_ENDPOINT or AIFOUNDRY_PROJECT_ENDPOINT before starting the workflow."
        )

    @staticmethod
    def _resolve_model_deployment() -> str:
        deployment = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        if deployment:
            return deployment
        legacy = os.getenv("PRD_MODEL_DEPLOYMENT_NAME")
        if legacy:
            os.environ.setdefault("AZURE_AI_MODEL_DEPLOYMENT_NAME", legacy)
            return legacy
        raise MissingEnvironmentError(
            "Set AZURE_AI_MODEL_DEPLOYMENT_NAME or PRD_MODEL_DEPLOYMENT_NAME before starting the workflow."
        )

    @staticmethod
    def _extract_json(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            samples: list[str] = []
            for item in payload:
                try:
                    return PrdWorkflow._extract_json(item)
                except ValueError:
                    content = getattr(item, "content", None)
                    text_attr = getattr(item, "text", None)
                    samples.append(
                        f"content_type={type(content)!r} content={repr(content)[:500]} text={repr(text_attr)[:500]} attrs={dir(item)}"
                    )
                    if not content and text_attr is None:
                        continue
                    candidates = []
                    if content:
                        if isinstance(content, str):
                            candidates.append(content)
                        else:
                            for part in content:
                                text = getattr(part, "text", None)
                                if text is None:
                                    continue
                                value = getattr(text, "value", text)
                                if value:
                                    candidates.append(str(value))
                    if text_attr is not None:
                        if isinstance(text_attr, str):
                            candidates.append(text_attr)
                        else:
                            value = getattr(text_attr, "value", text_attr)
                            if value:
                                candidates.append(str(value))
                    for candidate in candidates:
                        samples.append(str(candidate)[:500])
                        try:
                            return PrdWorkflow._extract_json(candidate)
                        except ValueError:
                            continue
            hint = f" candidates={samples!r}" if samples else ""
            raise ValueError(f"No JSON object found in workflow output list: {payload!r}{hint}")
        if not isinstance(payload, str):
            raise ValueError(f"Unexpected payload type: {type(payload)!r}")
        cleaned = payload.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match is None:
                raise ValueError("No JSON object found in workflow output")
            return json.loads(match.group(0))

    @staticmethod
    def _stringify_event_data(event: Any) -> str | None:
        data = getattr(event, "data", None)
        if data is None:
            return None
        if isinstance(data, str):
            normalized = data.replace("\r\n", "\n")
            normalized = normalized.replace('"\n', '"').replace('\n"', '"').replace("\n", " ")
            normalized = re.sub(r"\s+", " ", normalized).strip()
            try:
                parsed = PrdWorkflow._extract_json(normalized)
            except ValueError:
                return normalized
            return json.dumps(parsed)
        if isinstance(data, (dict, list)):
            try:
                return json.dumps(data)
            except TypeError:
                return str(data)
        return str(data)

    def _extract_participant_outputs(self, trace: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
        outputs: dict[str, dict[str, Any]] = {}
        for agent_name in _PARTICIPANT_ORDER:
            messages = trace.get(agent_name)
            if not messages:
                outputs[agent_name] = {}
                continue
            parsed = self._parse_last_json(messages)
            if isinstance(parsed, dict):
                outputs[agent_name] = parsed
            else:
                outputs[agent_name] = {}
            
        return outputs

    def _parse_last_json(self, messages: list[str]) -> dict[str, Any] | None:
        for message in reversed(messages):
            try:
                return self._extract_json(message)
            except ValueError:
                continue
        return None

    @staticmethod
    def _compose_prd(feature_idea: str, outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        research = outputs.get("product-researcher") if isinstance(outputs.get("product-researcher"), dict) else {}
        strategy = outputs.get("product-strategy") if isinstance(outputs.get("product-strategy"), dict) else {}
        architecture = outputs.get("technical-architect") if isinstance(outputs.get("technical-architect"), dict) else {}


        prd = {
            "feature_idea": feature_idea,
            "overview": research.get("research_summary"),
            "personas": research.get("personas"),
            "market_insights": research.get("market_insights"),
            "competitive_analysis": research.get("competitive_analysis"),
            "prd_outline": research.get("prd_outline"),
            "vision": strategy.get("vision"),
            "goals": strategy.get("goals"),
            "non_goals": strategy.get("non_goals"),
            "success_metrics": strategy.get("success_metrics"),
            "strategic_alignment": strategy.get("strategic_alignment"),
            "technical_feasibility": architecture.get("technical_feasibility"),
            "recommended_approach": architecture.get("recommended_approach"),
            "milestones": architecture.get("milestones"),
            "risks_dependencies": architecture.get("risks_dependencies"),
            "effort_estimate": architecture.get("effort_estimate"),
        }

        return {
            "feature_idea": feature_idea,
            "research": research,
            "strategy": strategy,
            "architecture": architecture,
            "prd": prd,
        }


_PARTICIPANT_SPECS = [
    {
        "name": "product-researcher",
        "env_var": "PRD_RESEARCHER_AGENT_ID",
        "uses_search": True,
        "instructions": (
            "You are a Product Researcher. Perform market and user research for the feature idea. "
            "If helpful, call the SearchTool to gather evidence. Respond with JSON only using the keys: "
            "`personas` (list), `market_insights` (string), `competitive_analysis` (string), "
            "`research_summary` (string), `prd_outline` (list), and `sources` (list of objects with `title`, `url`)."
        ),
    },
    {
        "name": "product-strategy",
        "env_var": "PRD_STRATEGY_AGENT_ID",
        "instructions": (
            "You are a Product Strategy Agent. Use the prior research output to craft product vision and strategy. "
            "Respond with JSON only using the keys: `vision` (string), `goals` (list), `non_goals` (list), "
            "`success_metrics` (list), `strategic_alignment` (string), and `assumptions` (list)."
        ),
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
    },
]

_PARTICIPANT_ORDER = [spec["name"] for spec in _PARTICIPANT_SPECS]
