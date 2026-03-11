import sqlglot
import os
from sqlglot import exp
from typing import List, Set, Tuple
from src.models.nodes import TransformationNode

class SQLLineageAnalyzer:
    def __init__(self, dialect: str = "postgres"):
        self.dialect = dialect

    def extract_lineage(self, sql: str, file_path: str) -> List[TransformationNode]:
        """Extracts lineage from a SQL string using sqlglot."""
        try:
            expressions = sqlglot.parse(sql, read=self.dialect)
        except Exception as e:
            # Fallback to general parsing or log error
            print(f"Error parsing SQL in {file_path}: {e}")
            return []

        transformations = []
        for expression in expressions:
            if not expression:
                continue
                
            sources = self._extract_sources(expression)
            targets = self._extract_targets(expression)
            
            if sources or targets:
                transformations.append(TransformationNode(
                    name=f"sql_transform_{os.path.basename(file_path)}",
                    source_datasets=list(sources),
                    target_datasets=list(targets),
                    transformation_type="sql_query",
                    source_file=file_path,
                    line_range=(1, len(sql.splitlines())) # Simplified
                ))
        
        return transformations

    def _extract_sources(self, expression: exp.Expression) -> Set[str]:
        sources = set()
        # Find all Table identifiers in the FROM/JOIN clauses
        for table in expression.find_all(exp.Table):
            if table.name:
                sources.add(table.name)
        
        # Remove CTEs from sources (they are intermediate)
        ctes = {cte.alias_column_names[0] if cte.alias_column_names else cte.alias for cte in expression.find_all(exp.CTE)}
        return sources - ctes

    def _extract_targets(self, expression: exp.Expression) -> Set[str]:
        targets = set()
        # INSERT INTO, CREATE TABLE AS, etc.
        if isinstance(expression, exp.Create):
            if expression.this and isinstance(expression.this, exp.Table):
                targets.add(expression.this.name)
        elif isinstance(expression, exp.Insert):
            if expression.this and isinstance(expression.this, exp.Table):
                targets.add(expression.this.name)
        return targets

import os # Needed by the class above
