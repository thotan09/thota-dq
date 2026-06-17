"""LangGraph state definition for the Aegis agent."""

from __future__ import annotations

from typing import Any, TypedDict

from ..rules.schema import DataQualityRule, RuleFailure, RuleResult  # noqa: F401


class ValidationScope(TypedDict):
    tables: list[str]
    rule_ids: list[str] | None


class AgentDecision(TypedDict):
    step: str
    input_summary: str
    output_summary: str
    model: str | None
    input_tokens: int
    output_tokens: int
    duration_ms: float
    cost_usd: float


class Diagnosis(TypedDict):
    failure_id: str
    explanation: str
    likely_cause: str
    suggested_action: str


class RCAResult(TypedDict):
    failure_id: str
    table: str
    upstream_tables: list[str]
    lineage_depth: int
    root_cause: str
    origin: str
    propagation: str
    fix: str


class RemediationProposal(TypedDict):
    failure_id: str
    table: str
    rule_type: str
    proposed_sql: str       # the actual SQL statement
    confidence: str         # "high" | "medium" | "low"
    caveat: str             # one sentence — what to check before running


class AegisState(TypedDict):
    run_id: str
    triggered_by: str
    scope: ValidationScope
    rules: list[DataQualityRule]
    plan: list[str]  # ordered rule IDs to execute
    rule_results: list[RuleResult]
    failures: list[RuleFailure]
    classified_failures: dict[str, list[RuleFailure]]  # severity -> failures
    reconciliation_summary: dict[str, Any]
    diagnoses: list[Diagnosis]
    rca_results: list[RCAResult]
    remediation_proposals: list[RemediationProposal]
    report: dict[str, Any]
    trajectory: list[AgentDecision]
    cost_total_usd: float
    tokens_total: int
    error: str | None
