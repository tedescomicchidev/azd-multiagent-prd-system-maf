from __future__ import annotations

import os
from typing import Any

import httpx
from agent_framework import AIFunction
from pydantic import BaseModel, Field


class SearchInput(BaseModel):
    query: str = Field(..., description="Search query to send to Google Custom Search")
    max_results: int = Field(
        5,
        ge=1,
        le=5,
        description="Maximum number of results to return (1-5).",
    )


class SearchTool:
    """Optional Google Custom Search tool for market research."""

    def __init__(self) -> None:
        self._api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        self._engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID")

    def as_function(self) -> AIFunction[SearchInput, dict[str, Any]]:
        return AIFunction(
            name="SearchTool",
            description="Search the web using Google Custom Search for market and product research.",
            func=self.run,
            input_model=SearchInput,
        )

    async def run(self, query: str, max_results: int = 5) -> dict[str, Any]:
        if not self._api_key or not self._engine_id:
            return {
                "status": "search_not_configured",
                "query": query,
                "results": [],
                "message": "GOOGLE_SEARCH_API_KEY or GOOGLE_SEARCH_ENGINE_ID is not configured.",
            }

        params = {
            "key": self._api_key,
            "cx": self._engine_id,
            "q": query,
            "num": max_results,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            return {
                "status": "search_error",
                "query": query,
                "results": [],
                "message": f"Search request failed: {exc}",
            }

        items = payload.get("items", [])
        results = [
            {
                "title": item.get("title"),
                "url": item.get("link"),
                "snippet": item.get("snippet"),
            }
            for item in items
        ]

        return {
            "status": "ok",
            "query": query,
            "results": results,
        }
