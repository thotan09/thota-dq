"""Pydantic request / response models for the Aegis REST API."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RunRequest(BaseModel):
    rules_yaml: str = Field(..., description="Raw YAML content of a rules file")
    triggered_by: str = Field("api", description="Caller label stored in the audit trail")


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    triggered_by: str
    created_at: str


class RunDetail(RunSummary):
    report: dict | None = None
    error: str | None = None


class SearchResult(BaseModel):
    run_id: str
    step: str
    input_summary: str
    output_summary: str
    model: str | None = None
    cost_usd: float = 0.0


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
