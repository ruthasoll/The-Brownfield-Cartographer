import yaml
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
                transformations.append(
                    TransformationNode(
                        name=f"dbt_model_{name}",
                        source_datasets=[],  # To be filled by SQL analyzer
                        target_datasets=[name],
                        transformation_type="dbt_model",
                        source_file=file_path,
                        line_range=(1, 1),
                    )
                )
        return transformations

    def parse_airflow_dag(self, file_path: str) -> List[TransformationNode]:
        """Parses Airflow DAG files (Python) for task dependencies using regex."""
        if not file_path.endswith(".py"):
            return []

        with open(file_path, "r") as f:
            content = f.read()

        import re

        # Look for >> or << operators
        deps = re.findall(r"(\w+)\s*>>\s*(\w+)", content)

        transformations = []
        for source, target in deps:
            transformations.append(
                TransformationNode(
                    name=f"airflow_dep_{source}_{target}",
                    source_datasets=[source],
                    target_datasets=[target],
                    transformation_type="airflow_dag",
                    source_file=file_path,
                    line_range=(1, 1),  # Simplified
                )
            )
        return transformations
