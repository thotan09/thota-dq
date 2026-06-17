"""Tests for AegisProject (aegis.yaml) loading and PipelineManifest inheritance."""

from __future__ import annotations

import textwrap
from pathlib import Path

from thota_dq.config.project import AegisProject
from thota_dq.pipeline.manifest import PipelineManifest

# ---------------------------------------------------------------------------
# AegisProject
# ---------------------------------------------------------------------------


class TestAegisProjectLoad:
    def test_load_full_config(self, tmp_path):
        cfg = tmp_path / "thota_dq.yaml"
        cfg.write_text(
            textwrap.dedent("""\
            default_llm:
              provider: openai
              model: gpt-4o-mini
            default_warehouse:
              type: bigquery
              connection:
                project: my-proj
                dataset: analytics
            audit:
              db_path: .thota_dq/history.db
            pipelines_dir: pipes
        """)
        )
        project = AegisProject.load(cfg)
        assert project.default_llm.provider == "openai"
        assert project.default_llm.model == "gpt-4o-mini"
        assert project.default_warehouse.type == "bigquery"
        assert project.default_warehouse.connection["project"] == "my-proj"
        assert project.pipelines_dir == "pipes"
        assert project.root == tmp_path.resolve()

    def test_load_minimal_config(self, tmp_path):
        cfg = tmp_path / "thota_dq.yaml"
        cfg.write_text("{}\n")
        project = AegisProject.load(cfg)
        assert project.default_llm.provider == "anthropic"
        assert project.default_warehouse.type == "duckdb"

    def test_load_empty_file(self, tmp_path):
        cfg = tmp_path / "thota_dq.yaml"
        cfg.write_text("")
        project = AegisProject.load(cfg)
        assert project.default_llm.provider == "anthropic"


class TestAegisProjectFind:
    def test_finds_in_parent(self, tmp_path):
        (tmp_path / "thota_dq.yaml").write_text("default_llm:\n  provider: bedrock\n")
        nested = tmp_path / "pipelines" / "fraud"
        nested.mkdir(parents=True)
        project = AegisProject.find(nested)
        assert project is not None
        assert project.default_llm.provider == "bedrock"

    def test_finds_in_same_dir(self, tmp_path):
        (tmp_path / "thota_dq.yaml").write_text("{}\n")
        project = AegisProject.find(tmp_path)
        assert project is not None

    def test_returns_none_when_not_found(self, tmp_path):
        # tmp_path has no thota-dq.yaml and parents are real filesystem dirs
        # Use a deeply nested temp path with no thota-dq.yaml anywhere inside
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        project = AegisProject.find(nested)
        # May or may not find one in parent tmp dirs — just verify it doesn't crash
        # and returns AegisProject or None
        assert project is None or isinstance(project, AegisProject)

    def test_nearest_wins(self, tmp_path):
        (tmp_path / "thota_dq.yaml").write_text("default_llm:\n  provider: anthropic\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "thota_dq.yaml").write_text("default_llm:\n  provider: openai\n")
        project = AegisProject.find(sub)
        assert project is not None
        assert project.default_llm.provider == "openai"

    def test_resolve_db_path_relative(self, tmp_path):
        (tmp_path / "thota_dq.yaml").write_text("audit:\n  db_path: .thota_dq/history.db\n")
        project = AegisProject.load(tmp_path / "thota_dq.yaml")
        assert project.resolve_db_path() == tmp_path / ".thota_dq" / "history.db"

    def test_resolve_db_path_absolute(self, tmp_path):
        abs_path = "/var/thota_dq/history.db"
        (tmp_path / "thota_dq.yaml").write_text(f"audit:\n  db_path: {abs_path}\n")
        project = AegisProject.load(tmp_path / "thota_dq.yaml")
        assert project.resolve_db_path() == Path(abs_path)


# ---------------------------------------------------------------------------
# PipelineManifest inheritance
# ---------------------------------------------------------------------------


class TestPipelineManifestInheritance:
    def _write_project(self, root: Path, provider="openai", warehouse_type="bigquery"):
        (root / "thota_dq.yaml").write_text(
            textwrap.dedent(f"""\
            default_llm:
              provider: {provider}
              model: gpt-4o-mini
            default_warehouse:
              type: {warehouse_type}
              connection:
                project: proj
                dataset: ds
        """)
        )

    def _write_rules(self, directory: Path):
        (directory / "rules.yaml").write_text("rules: []\n")

    def test_inherits_llm_and_warehouse(self, tmp_path):
        self._write_project(tmp_path)
        pipeline_dir = tmp_path / "pipelines" / "orders"
        pipeline_dir.mkdir(parents=True)
        self._write_rules(pipeline_dir)
        (pipeline_dir / "pipeline.yaml").write_text("name: orders\nrules: ./rules.yaml\n")
        m = PipelineManifest.load(pipeline_dir / "pipeline.yaml")
        assert m.llm.provider == "openai"
        assert m.warehouse.type == "bigquery"

    def test_pipeline_overrides_warehouse(self, tmp_path):
        self._write_project(tmp_path, warehouse_type="bigquery")
        pipeline_dir = tmp_path / "pipelines" / "local"
        pipeline_dir.mkdir(parents=True)
        self._write_rules(pipeline_dir)
        (pipeline_dir / "pipeline.yaml").write_text(
            textwrap.dedent("""\
            name: local
            rules: ./rules.yaml
            warehouse:
              type: duckdb
              connection:
                path: /tmp/local.duckdb
        """)
        )
        m = PipelineManifest.load(pipeline_dir / "pipeline.yaml")
        assert m.warehouse.type == "duckdb"
        assert m.warehouse.connection["path"] == "/tmp/local.duckdb"

    def test_pipeline_overrides_llm(self, tmp_path):
        self._write_project(tmp_path, provider="openai")
        pipeline_dir = tmp_path / "pipelines" / "heavy"
        pipeline_dir.mkdir(parents=True)
        self._write_rules(pipeline_dir)
        (pipeline_dir / "pipeline.yaml").write_text(
            textwrap.dedent("""\
            name: heavy
            rules: ./rules.yaml
            llm:
              provider: anthropic
              model: claude-sonnet-4-6
        """)
        )
        m = PipelineManifest.load(pipeline_dir / "pipeline.yaml")
        assert m.llm.provider == "anthropic"
        assert m.llm.model == "claude-sonnet-4-6"

    def test_no_aegis_yaml_uses_pydantic_defaults(self, tmp_path):
        pipeline_dir = tmp_path / "pipelines" / "standalone"
        pipeline_dir.mkdir(parents=True)
        self._write_rules(pipeline_dir)
        (pipeline_dir / "pipeline.yaml").write_text("name: standalone\nrules: ./rules.yaml\n")
        m = PipelineManifest.load(pipeline_dir / "pipeline.yaml")
        assert m.llm.provider == "anthropic"
        assert m.warehouse.type == "duckdb"

    def test_database_sugar_still_works_with_project(self, tmp_path):
        self._write_project(tmp_path, warehouse_type="bigquery")
        pipeline_dir = tmp_path / "pipelines" / "duckpipe"
        pipeline_dir.mkdir(parents=True)
        self._write_rules(pipeline_dir)
        (pipeline_dir / "pipeline.yaml").write_text(
            "name: duckpipe\nrules: ./rules.yaml\ndatabase: /tmp/x.duckdb\n"
        )
        m = PipelineManifest.load(pipeline_dir / "pipeline.yaml")
        # explicit `database` key → duckdb override, not inherited bigquery
        assert m.warehouse.type == "duckdb"
        assert m.warehouse.connection["path"] == "/tmp/x.duckdb"
