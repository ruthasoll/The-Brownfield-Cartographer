import os
import subprocess
from typing import List, Dict, Any, Optional
from src.models.nodes import ModuleNode, FunctionNode, ClassNode
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph

class SurveyorAgent:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.analyzer = TreeSitterAnalyzer()
        self.kg = KnowledgeGraph()
        self.modules: Dict[str, ModuleNode] = {}

    def analyze_codebase(self):
        """Analyzes the entire codebase and builds the structural skeleton."""
        for root, _, files in os.walk(self.repo_path):
            for file in files:
                if file.endswith((".py", ".sql", ".yml", ".yaml")):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.repo_path)
                    
                    module_node = self.analyze_module(file_path, rel_path)
                    if module_node:
                        self.modules[rel_path] = module_node
                        self.kg.add_node(rel_path, module_node, "module")

        self.build_import_graph()
        self.calculate_pagerank()
        self.detect_dead_code()

    def analyze_module(self, file_path: str, rel_path: str) -> Optional[ModuleNode]:
        struct = self.analyzer.extract_structure(file_path)
        if not struct and not file_path.endswith((".yml", ".yaml")):
            return None

        ext = os.path.splitext(file_path)[1]
        language = "python" if ext == ".py" else ("sql" if ext == ".sql" else "yaml")
        
        # Functions/Classes to Node models
        functions = [FunctionNode(
            qualified_name=f"{rel_path}.{f['name']}",
            parent_module=rel_path,
            signature=f['name'],
            is_public_api=f['is_public']
        ) for f in struct.get("functions", [])]
        
        classes = [ClassNode(
            name=c,
            parent_module=rel_path
        ) for c in struct.get("classes", [])]

        # Complexity
        with open(file_path, "rb") as f:
            content = f.read().decode("utf-8", errors="ignore")
        lines = content.splitlines()
        loc = len(lines)
        
        # Simple cyclomatic complexity proxy for now
        complexity = float(loc) 

        return ModuleNode(
            path=rel_path,
            language=language,
            imports=struct.get("imports", []) or struct.get("refs", []),
            functions=functions,
            classes=classes,
            complexity_score=complexity,
            change_velocity_30d=0,
            is_dead_code_candidate=False
        )

    def build_import_graph(self):
        for path, node in self.modules.items():
            for imp in node.imports:
                for target_path in self.modules.keys():
                    if imp in target_path.replace("\\", ".").replace("/", "."):
                        self.kg.add_edge(path, target_path, "imports")

    def calculate_pagerank(self):
        if len(self.kg.graph) > 0:
            scores = nx.pagerank(self.kg.graph)
            for path, score in scores.items():
                if path in self.modules:
                    self.modules[path].complexity_score = score # Using PageRank as a proxy for structural importance

    def detect_dead_code(self):
        """Identifies modules with 0 in-degree as dead code candidates."""
        for node in self.kg.graph.nodes:
            if self.kg.graph.in_degree(node) == 0:
                # Basic filter: ignore known entry points or seeds
                if "cli.py" not in node and "seeds" not in node:
                    if node in self.modules:
                        self.modules[node].is_dead_code_candidate = True

    def save_graph(self, output_path: str):
        # Update nodes in KG with latest metadata (PageRank, Dead Code)
        for path, node in self.modules.items():
            self.kg.add_node(path, node, "module")
        self.kg.serialize(output_path)

    def extract_git_velocity(self, days=30):
        try:
            cmd = f"git log --since='{days} days ago' --name-only --format=format:"
            result = subprocess.run(cmd, shell=True, cwd=self.repo_path, capture_output=True, text=True)
            files = [f for f in result.stdout.splitlines() if f.strip()]
            from collections import Counter
            counts = Counter(files)
            for path, count in counts.items():
                if path in self.modules:
                    self.modules[path].change_velocity_30d = count
                    self.kg.add_node(path, self.modules[path], "module")
        except Exception as e:
            print(f"Error: {e}")

import networkx as nx # Needed
