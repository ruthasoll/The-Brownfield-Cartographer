import networkx as nx
import json
import os
from typing import Dict, Any, List, Optional, TypeVar
from pydantic import BaseModel
from src.models.edges import EdgeMetadata

# Generic for Pydantic Models
T = TypeVar("T", bound=BaseModel)


class KnowledgeGraph:
    def __init__(self):
        self.graph = nx.MultiDiGraph()  # Support multiple relationships between same nodes

    def add_node(self, node_id: str, data: T, node_type: str):
        """Adds a typed node to the graph using a Pydantic model."""
        self.graph.add_node(node_id, **data.dict(), type=node_type)

    def add_edge(self, source_id: str, target_id: str, metadata: EdgeMetadata):
        """Adds a typed edge between two nodes."""
        self.graph.add_edge(source_id, target_id, key=metadata.rel_type.value, **metadata.dict())

    def get_node_data(self, node_id: str) -> Optional[Dict[str, Any]]:
        if node_id in self.graph:
            return self.graph.nodes[node_id]
        return None

    def serialize(self, file_path: str):
        """Serializes the graph to a JSON file."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # For MultiDiGraph, edges() returns (u, v, key, data)
        data = {
            "nodes": {n: self.graph.nodes[n] for n in self.graph.nodes},
            "edges": [
                {"source": u, "target": v, "key": k, "metadata": d}
                for u, v, k, d in self.graph.edges(keys=True, data=True)
            ],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def deserialize(self, file_path: str):
        """Deserializes the graph from a JSON file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Graph file not found: {file_path}")

        with open(file_path, "r") as f:
            data = json.load(f)

        self.graph = nx.MultiDiGraph()
        for node_id, attr in data["nodes"].items():
            self.graph.add_node(node_id, **attr)

        for edge in data["edges"]:
            self.graph.add_edge(edge["source"], edge["target"], key=edge["key"], **edge["metadata"])

    def search_by_type(self, node_type: str) -> List[str]:
        return [n for n, d in self.graph.nodes(data=True) if d.get("type") == node_type]
