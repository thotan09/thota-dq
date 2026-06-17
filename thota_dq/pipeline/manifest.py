"""Pipeline manifest — named, reusable pipeline configurations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str | None = None


class WarehouseConfig(BaseModel):
    type: str = "duckdb"
    connection: dict[str, Any] = Field(default_factory=dict)


class PipelineManifest(BaseModel):
    name: str
    description: str = ""
    rules: str
    warehouse: WarehouseConfig = Field(default_factory=WarehouseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    kb: list[str] = Field(default_factory=list)
    output_json: str | None = None
    goal: str = ""

    @classmethod
    def load(cls, path: Path) -> PipelineManifest:
        """Load a pipeline manifest from a YAML file.

        Automatically walks up from the manifest's directory to find thota-dq.yaml.
        Any field not specified in pipeline.yaml inherits from thota_dq.yaml defaults.
        """
        from ..config.project import AegisProject

        raw = yaml.safe_load(path.read_text())

        # Sugar: top-level `database` key → warehouse.connection.path
        if "database" in raw and "warehouse" not in raw:
            raw["warehouse"] = {"type": "duckdb", "connection": {"path": raw.pop("database")}}
        elif "database" in raw:
            raw["warehouse"].setdefault("connection", {})["path"] = raw.pop("database")

        # Inherit missing fields from the nearest thota-dq.yaml (walk up from manifest dir)
        project = AegisProject.find(path.parent)
        if project is not None:
            if "warehouse" not in raw:
                raw["warehouse"] = project.default_warehouse.model_dump()
            if "llm" not in raw:
                raw["llm"] = project.default_llm.model_dump()

        # Resolve paths relative to the manifest file's directory
        base = path.parent
        raw["rules"] = (
            str(base / raw["rules"]) if not Path(raw["rules"]).is_absolute() else raw["rules"]
        )
        raw["kb"] = [str(base / k) if not Path(k).is_absolute() else k for k in raw.get("kb", [])]
        if raw.get("output_json"):
            raw["output_json"] = (
                str(base / raw["output_json"])
                if not Path(raw["output_json"]).is_absolute()
                else raw["output_json"]
            )

        return cls.model_validate(raw)

    def rules_path(self) -> Path:
        return Path(self.rules)

    def kb_paths(self) -> list[Path]:
        return [Path(k) for k in self.kb]

    def connection_params_json(self) -> str:
        import json

        return json.dumps(self.warehouse.connection)
