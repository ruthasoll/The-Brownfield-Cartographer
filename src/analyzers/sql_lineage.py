import sqlglot
import os
import re
import logging
from sqlglot import exp
from typing import List, Set
from src.models.nodes import TransformationNode

logger = logging.getLogger("SQLLineageAnalyzer")


class SQLLineageAnalyzer:
    def __init__(self, dialect: str = "postgres"):
        self.dialect = dialect

    def extract_lineage(self, sql: str, file_path: str) -> List[TransformationNode]:
        """Extracts lineage with CTE resolution and Jinja awareness."""
        # 1. Basic Jinja/dbt processing (static extraction of ref/source)
        # This ensures we don't lose lineage if sqlglot fails on Jinja syntax.
        dbt_sources = self._extract_dbt_refs(sql)

        # 2. sqlglot parsing
        try:
            # Clean Jinja blocks for sqlglot to help parsing succeed
            clean_sql = re.sub(r"\{\{.*?\}\}", "placeholder_table", sql)
            clean_sql = re.sub(r"\{%.*?%\}", "", clean_sql)

            expressions = sqlglot.parse(clean_sql, read=self.dialect)
        except Exception as e:
            logger.warning(
                f"sqlglot failed to parse {file_path}: {e}. Falling back to dbt static extraction."
            )
            # Fallback to dbt static extraction if sqlglot fails
            if dbt_sources:
                return [
                    TransformationNode(
                        name=f"sql_transform_{os.path.basename(file_path)}",
                        source_datasets=list(dbt_sources),
                        target_datasets=[os.path.basename(file_path).split(".")[0]],  # Best guess
                        transformation_type="sql_query",
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
