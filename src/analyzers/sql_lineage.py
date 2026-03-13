import sqlglot
import os
import re
import logging
from sqlglot import exp
from typing import List, Set
from src.models.nodes import TransformationNode

logger = logging.getLogger("SQLLineageAnalyzer")


class SQLLineageAnalyzer:
    def __init__(self, dialect: str | List[str] = "postgres"):
        self.dialects = [dialect] if isinstance(dialect, str) else dialect
        # Common dialects to try if none specified or if preferred fails
        self.fallback_dialects = ["postgres", "snowflake", "bigquery", "databricks", "duckdb"]

    def extract_lineage(self, sql: str, file_path: str) -> List[TransformationNode]:
        """Extracts lineage with multi-dialect support and CTE resolution."""
        # 1. Basic Jinja/dbt processing (static extraction of ref/source)
        # This ensures we don't lose lineage if sqlglot fails on Jinja syntax.
        dbt_sources = self._extract_dbt_refs(sql)

        # 2. sqlglot parsing with multi-dialect fallback
        # Clean Jinja blocks for sqlglot to help parsing succeed
        clean_sql = re.sub(r"\{\{.*?\}\}", "placeholder_table", sql)
        clean_sql = re.sub(r"\{%.*?%\}", "", clean_sql)

        expressions = []
        parsed_dialect = None

        # Try specified dialects, then fallbacks
        to_try = self.dialects + [d for d in self.fallback_dialects if d not in self.dialects]

        for d in to_try:
            try:
                expressions = sqlglot.parse(clean_sql, read=d)
                if expressions and expressions[0]:  # Check if parsing yielded any expressions
                    parsed_dialect = d
                    logger.info(f"Successfully parsed {file_path} using dialect: {d}")
                    break
            except Exception:
                # Log the specific error if needed, but for now, just try the next dialect
                continue

        if not parsed_dialect:
            logger.warning(
                f"sqlglot failed to parse {file_path} with all attempted dialects. Falling back to dbt static extraction."
            )
            # Fallback to dbt static extraction if sqlglot fails with all dialects
            if dbt_sources:
                return [
                    TransformationNode(
                        name=f"sql_transform_{os.path.basename(file_path)}",
                        source_datasets=list(dbt_sources),
                        target_datasets=[os.path.basename(file_path).split(".")[0]],  # Best guess
                        transformation_type="sql_query_static_fallback",
                        source_file=file_path,
                        line_range=(1, len(sql.splitlines())),
                        sql_query_if_applicable=sql,
                    )
                ]
            return []

        transformations = []
        for expression in expressions:
            if not expression:
                continue

            sources = self._extract_sources(expression)
            targets = self._extract_targets(expression)

            # Merge with dbt static sources
            sources.update(dbt_sources)

            # If dbt model, typically the target is the file name
            if file_path.endswith(".sql") and not targets:
                targets.add(os.path.basename(file_path).split(".")[0])

            if sources or targets:
                transformations.append(
                    TransformationNode(
                        name=f"sql_transform_{os.path.basename(file_path)}",
                        source_datasets=list(sources),
                        target_datasets=list(targets),
                        transformation_type="sql_query",
                        source_file=file_path,
                        line_range=(1, len(sql.splitlines())),
                        sql_query_if_applicable=sql,
                    )
                )

        return transformations

    def _extract_dbt_refs(self, sql: str) -> Set[str]:
        """Static extraction of dbt ref() and source() calls."""
        refs = re.findall(r"\{\{\s*ref\(['\"](.+?)['\"]\)\s*\}\}", sql)
        sources = re.findall(r"\{\{\s*source\(['\"].+?['\"]\s*,\s*['\"](.+?)['\"]\)\s*\}\}", sql)
        return set(refs) | set(sources)

    def _extract_sources(self, expression: exp.Expression) -> Set[str]:
        """Resolves CTEs to find physical table sources."""
        sources = set()
        ctes = set()

        # Find all CTE names
        for cte in expression.find_all(exp.CTE):
            if cte.alias:
                ctes.add(cte.alias.lower())

        # Find all Table identifiers
        for table in expression.find_all(exp.Table):
            if table.name:
                name = table.name.lower()
                # If it's not a placeholder and not a CTE, it's a physical source
                if name != "placeholder_table" and name not in ctes:
                    sources.add(name)

        return sources

    def _extract_targets(self, expression: exp.Expression) -> Set[str]:
        """Identifies target tables (Write operations)."""
        targets = set()
        if isinstance(expression, exp.Create):
            if expression.this and isinstance(expression.this, exp.Table):
                targets.add(expression.this.name.lower())
        elif isinstance(expression, exp.Insert):
            if expression.this and isinstance(expression.this, exp.Table):
                targets.add(expression.this.name.lower())
        elif isinstance(expression, exp.Update):
            if expression.this and isinstance(expression.this, exp.Table):
                targets.add(expression.this.name.lower())
        return targets
