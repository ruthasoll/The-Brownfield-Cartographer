import yaml
import os
from typing import List
from src.models.nodes import TransformationNode

class DAGConfigAnalyzer:
    def __init__(self):
        pass

    def parse_dbt_schema(self, file_path: str) -> List[TransformationNode]:
        """Parses dbt schema.yml for lineage/dependencies."""
        if not file_path.endswith(".yml") and not file_path.endswith(".yaml"):
            return []

        try:
            with open(file_path, "r") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            print(f"Error parsing YAML in {file_path}: {e}")
            return []

        if not config or "models" not in config:
            return []

        models = config.get("models")
        if not isinstance(models, list):
            return []

        transformations = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name")
            # In dbt, dependencies are usually in the .sql files via ref()
            # but tests/descriptions are here. We can mark the model as a target.
            if name:
                transformations.append(TransformationNode(
                    name=f"dbt_model_{name}",
                    source_datasets=[], # To be filled by SQL analyzer
                    target_datasets=[name],
                    transformation_type="dbt_model",
                    source_file=file_path,
                    line_range=(1, 1)
                ))
        return transformations

    def parse_airflow_dag(self, file_path: str) -> List[TransformationNode]:
        """Parses Airflow DAG files (Python) for task dependencies."""
        # This would ideally use tree-sitter or dynamic analysis
        # For Phase 2, we can implement a basic regex or tree-sitter pattern
        return []
