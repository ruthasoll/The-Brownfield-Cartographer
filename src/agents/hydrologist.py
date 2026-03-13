import os
import networkx as nx
import logging
from typing import List, Dict, Any
from src.models.nodes import DatasetNode, TransformationNode
from src.models.edges import RelationshipType, EdgeMetadata
from src.analyzers.python_lineage import PythonDataFlowAnalyzer
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.dag_config_parser import DAGConfigAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger("HydrologistAgent")


class HydrologistAgent:
    def __init__(self, kg: KnowledgeGraph, repo_path: str):
        self.repo_path = repo_path
        self.kg = kg
        self.py_analyzer = PythonDataFlowAnalyzer()
        self.sql_analyzer = SQLLineageAnalyzer()
        self.config_analyzer = DAGConfigAnalyzer()
        self.transformations: List[TransformationNode] = []
        self.audit_log: List[Dict[str, Any]] = []

    def analyze_lineage(self):
        """Orchestrates lineage extraction with multi-analyzer coverage."""
        for root, _, files in os.walk(self.repo_path):
            if ".git" in root or ".venv" in root:
                continue
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.repo_path)

                try:
                    if file.endswith(".py"):
                        self.transformations.extend(self.py_analyzer.extract_lineage(file_path))
                    elif file.endswith(".sql"):
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            sql = f.read()
                        self.transformations.extend(
                            self.sql_analyzer.extract_lineage(sql, rel_path)
                        )
                    elif file.endswith((".yml", ".yaml")):
                        # dbt models and schema configs
                        res = self.config_analyzer.parse_dbt_schema(file_path)
                        if res:
                            self.transformations.extend(res)
                except Exception as e:
                    logger.error(f"Hydrologist failed on {rel_path}: {e}")

        self.build_graph()

    def build_graph(self):
        """Builds a typed lineage graph with standardized ID prefixes."""
        for trans in self.transformations:
            # Prefix: tr: for transformation
            trans_node_id = f"tr:{trans.name}"
            self.kg.add_node(trans_node_id, trans, "transformation")

            for source in trans.source_datasets:
                # Prefix: ds: for dataset
                ds_id = f"ds:{source}"
                ds = DatasetNode(name=source, storage_type="unknown")
                self.kg.add_node(ds_id, ds, "dataset")

                metadata = EdgeMetadata(
                    rel_type=RelationshipType.READS,
                    source_line=trans.line_range[0],
                    properties={"file": trans.source_file},
                    confidence=1.0,
                )
                self.kg.add_edge(ds_id, trans_node_id, metadata)

            for target in trans.target_datasets:
                ds_id = f"ds:{target}"
                ds = DatasetNode(name=target, storage_type="unknown")
                self.kg.add_node(ds_id, ds, "dataset")

                metadata = EdgeMetadata(
                    rel_type=RelationshipType.WRITES,
                    source_line=trans.line_range[0],
                    properties={"file": trans.source_file},
                    confidence=1.0,
                )
                self.kg.add_edge(trans_node_id, ds_id, metadata)

    def blast_radius(self, ds_id: str) -> List[str]:
        """Downstream impact: What breaks if this dataset is corrupted?"""
        if not ds_id.startswith("ds:"):
            ds_id = f"ds:{ds_id}"
        if ds_id not in self.kg.graph:
            return []
        return list(nx.descendants(self.kg.graph, ds_id))

    def reverse_blast_radius(self, ds_id: str) -> List[str]:
        """Upstream impact: What causes this dataset to change?"""
        if not ds_id.startswith("ds:"):
            ds_id = f"ds:{ds_id}"
        if ds_id not in self.kg.graph:
            return []
        return list(nx.ancestors(self.kg.graph, ds_id))

    def find_path_between(self, start_id: str, end_id: str) -> List[List[str]]:
        """Enumerates flow paths between two datasets."""
        if not start_id.startswith("ds:"):
            start_id = f"ds:{start_id}"
        if not end_id.startswith("ds:"):
            end_id = f"ds:{end_id}"

        try:
            return list(nx.all_simple_paths(self.kg.graph, start_id, end_id))
        except (nx.NodeNotFound, nx.NetworkXNoPath):
            return []

    def save_lineage(self, output_path: str):
        self.kg.serialize(output_path)
