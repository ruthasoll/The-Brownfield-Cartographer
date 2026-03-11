import networkx as nx
import json
import os
from typing import Dict, Any, List, Optional, Type, TypeVar, Generic
from pydantic import BaseModel
from src.models.nodes import ModuleNode, FunctionNode, ClassNode, DatasetNode, TransformationNode

# Generic for Pydantic Models
T = TypeVar("T", bound=BaseModel)

class KnowledgeGraph:
    def __init__(self):
        self.graph = nx.DiGraph()

    def add_node(self, node_id: str, data: T, node_type: str):
        """Adds a typed node to the graph using a Pydantic model."""
        self.graph.add_node(node_id, **data.dict(), type=node_type)

    def add_edge(self, source_id: str, target_id: str, relationship: str = "depends_on"):
        """Adds an edge between two nodes."""
        self.graph.add_edge(source_id, target_id, rel=relationship)

    def get_node_data(self, node_id: str) -> Optional[Dict[str, Any]]:
        if node_id in self.graph:
            return self.graph.nodes[node_id]
        return None

    def serialize(self, file_path: str):
        """Serializes the graph to a JSON file."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        data = {
            "nodes": {n: self.graph.nodes[n] for n in self.graph.nodes},
            "edges": list(self.graph.edges(data=True)) # Include edge data
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def deserialize(self, file_path: str):
        """Deserializes the graph from a JSON file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Graph file not found: {file_path}")
            
        with open(file_path, "r") as f:
            data = json.load(f)
            
        self.graph = nx.DiGraph()
        for node_id, attr in data["nodes"].items():
            self.graph.add_node(node_id, **attr)
        
        for edge in data["edges"]:
            u, v, attr = edge
            self.graph.add_edge(u, v, **attr)

    def search_by_type(self, node_type: str) -> List[str]:
        return [n for n, d in self.graph.nodes(data=True) if d.get("type") == node_type]
