import networkx as nx
import os
import json
from typing import List, Dict, Optional
from src.models.nodes import DatasetNode, TransformationNode, ModuleNode
from src.analyzers.python_lineage import PythonDataFlowAnalyzer
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.dag_config_parser import DAGConfigAnalyzer

class HydrologistAgent:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.graph = nx.DiGraph()
        self.py_analyzer = PythonDataFlowAnalyzer()
        self.sql_analyzer = SQLLineageAnalyzer()
        self.config_analyzer = DAGConfigAnalyzer()
        self.transformations: List[TransformationNode] = []
        self.audit_log: List[Dict[str, Any]] = []

    def _log_event(self, action: str, details: Dict[str, Any]):
        """Logs an analysis event for the cartography trace."""
        self.audit_log.append({
            "agent": "Hydrologist",
            "action": action,
            "details": details,
            "timestamp": str(os.path.getmtime(self.repo_path)) # Placeholder
        })

    def analyze_lineage(self):
        """Orchestrates lineage extraction across the repository."""
        for root, _, files in os.walk(self.repo_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.repo_path)
                
                if file.endswith(".py"):
                    self.transformations.extend(self.py_analyzer.extract_lineage(file_path))
                elif file.endswith(".sql"):
                    with open(file_path, "r", encoding="utf-8") as f:
                        sql = f.read()
                    self.transformations.extend(self.sql_analyzer.extract_lineage(sql, rel_path))
                elif file.endswith((".yml", ".yaml")):
                    self.transformations.extend(self.config_analyzer.parse_dbt_schema(file_path))
        
        self._log_event("analyze_lineage", {"file_count": len(self.transformations)})
        self.build_graph()

    def build_graph(self):
        for trans in self.transformations:
            trans_node_id = f"trans_{trans.name}"
            self.graph.add_node(trans_node_id, **trans.dict(), type="transformation")
            
            for source in trans.source_datasets:
                self.graph.add_node(source, type="dataset")
                self.graph.add_edge(source, trans_node_id)
            
            for target in trans.target_datasets:
                self.graph.add_node(target, type="dataset")
                self.graph.add_edge(trans_node_id, target)

    def blast_radius(self, node_id: str) -> List[str]:
        if node_id not in self.graph:
            return []
        # Get all nodes reachable from node_id
        return list(nx.descendants(self.graph, node_id))

    def find_sources(self) -> List[str]:
        return [n for n, d in self.graph.in_degree() if d == 0]

    def find_sinks(self) -> List[str]:
        return [n for n, d in self.graph.out_degree() if d == 0]

    def save_lineage(self, output_path: str):
        """Serializes the lineage graph and audit log to disk."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        data = {
            "nodes": {n: self.graph.nodes[n] for n in self.graph.nodes},
            "edges": list(self.graph.edges()),
            "audit_log": self.audit_log
        }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
