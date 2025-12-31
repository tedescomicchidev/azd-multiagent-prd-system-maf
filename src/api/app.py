from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException

from .prd_workflow import (
    MissingEnvironmentError,
    PrdWorkflow,
    WorkflowExecutionError,
    WorkflowNotReadyError,
    WorkflowResultError,
)


app = FastAPI()
workflow = PrdWorkflow()


@app.on_event("startup")
async def _startup() -> None:
    try:
        await workflow.startup()
    except MissingEnvironmentError as exc:
        raise RuntimeError(str(exc)) from exc


@app.on_event("shutdown")
async def _shutdown() -> None:
    await workflow.shutdown()


@app.get("/")
async def health() -> dict[str, Any]:
    return {"status": "ok", **workflow.environment_snapshot()}


@app.post("/prd")
async def prd(feature_idea: str = Body(..., embed=True)) -> dict[str, Any]:
    text = feature_idea.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Feature idea cannot be empty.")

    try:
        result, trace = await workflow.build_prd_with_trace(text)
        return {"result": result, "trace": trace.messages}
    except WorkflowNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (WorkflowExecutionError, WorkflowResultError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Workflow execution failed: {exc}") from exc
