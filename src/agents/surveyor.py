import os
import subprocess
import networkx as nx
import json
import logging
import re
from typing import Dict, Optional
from collections import Counter
from src.models.nodes import ModuleNode, FunctionNode, ClassNode
from src.models.edges import RelationshipType, EdgeMetadata
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger("SurveyorAgent")


class SurveyorAgent:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.analyzer = TreeSitterAnalyzer()
        self.kg = KnowledgeGraph()
        self.modules: Dict[str, ModuleNode] = {}
        self.symbol_usage: Counter = Counter()

    def analyze_codebase(self, changed_files=None):
        """Orchestrates structural analysis."""
        for root, _, files in os.walk(self.repo_path):
            if ".git" in root or ".venv" in root:
                continue
            for file in files:
                if file.endswith((".py", ".sql", ".yml", ".yaml")):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.repo_path)

                    if changed_files is not None and rel_path.replace("\\", "/") not in [
                        f.replace("\\", "/") for f in changed_files
                    ]:
                        # File unchanged. Try to load it from existing knowledge graph if present
                        if rel_path in self.kg.graph:
                            existing_data = self.kg.graph.nodes[rel_path]
                            if existing_data.get("type") == "module":
                                self.modules[rel_path] = ModuleNode(**existing_data)
                        continue

                    module_node = self.analyze_module(file_path, rel_path)
                    if module_node:
                        self.modules[rel_path] = module_node
                        self.kg.add_node(rel_path, module_node, "module")

        self._track_symbol_usage()
        self.build_import_graph()
        self.calculate_pagerank()
        self.detect_circular_dependencies()
        self.detect_dead_code()

    def analyze_module(self, file_path: str, rel_path: str) -> Optional[ModuleNode]:
        struct = self.analyzer.extract_structure(file_path)
        if not struct:
            struct = {}

        ext = os.path.splitext(file_path)[1].lower()
        language = "python" if ext == ".py" else ("sql" if ext == ".sql" else "yaml")

        functions = [
            FunctionNode(
                qualified_name=f"{rel_path}.{f['name']}",
                parent_module=rel_path,
                signature=f["name"],
                is_public_api=f["is_public"],
            )
            for f in struct.get("functions", [])
        ]

        classes = [ClassNode(name=c, parent_module=rel_path) for c in struct.get("classes", [])]

        try:
            with open(file_path, "rb") as f:
                content = f.read().decode("utf-8", errors="ignore")
            lines = content.splitlines()
            loc = len(lines)
            complexity = float(loc)  # Simple proxy

            return ModuleNode(
                path=rel_path,
                language=language,
                imports=struct.get("imports", []) or struct.get("refs", []),
                functions=functions,
                classes=classes,
                complexity_score=complexity,
                change_velocity_30d=0,
                is_dead_code_candidate=False,
            )
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return None

    def _track_symbol_usage(self):
        """Scans codebase for symbol mentions to detect cross-module usage."""
        for root, _, files in os.walk(self.repo_path):
            if ".git" in root or ".venv" in root:
                continue
            for file in files:
                if file.endswith(".py"):
                    try:
                        with open(
                            os.path.join(root, file), "r", encoding="utf-8", errors="ignore"
                        ) as f:
                            tokens = re.findall(r"\b\w+\b", f.read())
                            self.symbol_usage.update(tokens)
                    except Exception:
                        pass

    def build_import_graph(self):
        """Builds edges with detailed metadata and typed models."""
        for path, node in self.modules.items():
            for imp in node.imports:
                for target_path in self.modules.keys():
                    # Resolve import to target file
                    if imp in target_path.replace("\\", ".").replace("/", "."):
                        metadata = EdgeMetadata(
                            rel_type=RelationshipType.IMPORTS,
                            properties={"import_name": imp},
                            confidence=0.9,
                        )
                        self.kg.add_edge(path, target_path, metadata)

    def calculate_pagerank(self):
        """Derives structural importance hubs."""
        if len(self.kg.graph) > 0:
            try:
                # PageRank works on standard graphs, but MultiDiGraph needs flattening or specific handling
                simple_graph = nx.DiGraph(self.kg.graph)
                scores = nx.pagerank(simple_graph)
                for path, score in scores.items():
                    if path in self.modules:
                        self.modules[path].complexity_score = score
            except Exception as e:
                logger.warning(f"PageRank failed: {e}")

    def detect_circular_dependencies(self):
        """Finds circular dependency clusters using SCC."""
        simple_graph = nx.DiGraph(self.kg.graph)
        sccs = [c for c in nx.strongly_connected_components(simple_graph) if len(c) > 1]
        for scc in sccs:
            logger.warning(f"Circular dependency cluster found: {scc}")
            for node_id in scc:
                if node_id in self.modules:
                    # Mark nodes in cycles as structurally risky
                    self.modules[node_id].domain_cluster = "circular_cluster"

    def detect_dead_code(self):
        """Symbol-level dead code detection."""
        for path, module in self.modules.items():
            # 1. In-degree check
            if self.kg.graph.in_degree(path) == 0:
                if "cli.py" not in path and "seeds" not in path:
                    module.is_dead_code_candidate = True
                    continue

            # 2. Symbol-level check for public functions
            dead_funcs = []
            for func in module.functions:
                if (
                    func.is_public_api and self.symbol_usage[func.signature] <= 1
                ):  # 1 is the definition itself
                    dead_funcs.append(func.signature)

            if dead_funcs and len(dead_funcs) == len(module.functions):
                module.is_dead_code_candidate = True

    def extract_git_velocity(self, days: int = 30):
        """Extracts change hotspots from git history."""
        try:
            cmd = ["git", "log", f"--since='{days} days ago'", "--name-only", "--format=format:"]
            result = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning(
                    "Git log failed. Repository might not be a git repo or git is missing."
                )
                return

            files = [f for f in result.stdout.splitlines() if f.strip()]
            counts = Counter(files)
            for path, count in counts.items():
                if path in self.modules:
                    self.modules[path].change_velocity_30d = count
        except Exception as e:
            logger.error(f"Git velocity extraction failed: {e}")

    def generate_summary(self, output_dir: str):
        """Exposes a consolidated summary of architectural hotspots."""
        hubs = sorted(self.modules.items(), key=lambda x: x[1].complexity_score, reverse=True)[:5]
        hotspots = sorted(
            self.modules.items(), key=lambda x: x[1].change_velocity_30d, reverse=True
        )[:5]

        summary = {
            "top_hubs": [{"path": p, "score": m.complexity_score} for p, m in hubs],
            "hotspots": [{"path": p, "velocity": m.change_velocity_30d} for p, m in hotspots],
            "circular_clusters": [
                list(c)
                for c in nx.strongly_connected_components(nx.DiGraph(self.kg.graph))
                if len(c) > 1
            ],
        }

        summary_path = os.path.join(output_dir, "analysis_summary.json")
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Summary generated at {summary_path}")

    def save_graph(self, output_path: str):
        for path, node in self.modules.items():
            self.kg.add_node(path, node, "module")
        self.kg.serialize(output_path)
        self.generate_summary(os.path.dirname(output_path))
