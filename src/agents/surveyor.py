import os
import subprocess
import networkx as nx
from typing import List, Dict, Any, Optional
from src.models.nodes import ModuleNode, FunctionNode, ClassNode
from src.analyzers.tree_sitter_analyzer import LanguageRouter
from tree_sitter import Query
import json

class SurveyorAgent:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.router = LanguageRouter()
        self.graph = nx.DiGraph()
        self.modules: Dict[str, ModuleNode] = {}
        self.pagerank_scores: Dict[str, float] = {}

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
                        self.graph.add_node(rel_path, **module_node.dict())

        self.build_import_graph()
        self.calculate_pagerank()

    def analyze_module(self, file_path: str, rel_path: str) -> Optional[ModuleNode]:
        parser = self.router.get_parser(file_path)
        if not parser:
            return None

        ext = os.path.splitext(file_path)[1]
        language = "python" if ext == ".py" else ("sql" if ext == ".sql" else "yaml")
        
        with open(file_path, "rb") as f:
            content = f.read()
            tree = parser.parse(content)

        imports = []
        functions = []
        classes = []

        if language == "python":
            imports = self.extract_python_imports(tree, content)
            functions = self.extract_python_functions(tree, content, rel_path)
            classes = self.extract_python_classes(tree, content, rel_path)
        elif language == "sql":
            imports = self.extract_sql_refs(tree, content)

        # Basic complexity: line count for now
        lines = content.decode("utf-8", errors="ignore").splitlines()
        loc = len(lines)
        
        comment_count = sum(1 for line in lines if line.strip().startswith(("#", "--", "{#")))
        comment_ratio = comment_count / loc if loc > 0 else 0
        
        complexity = float(loc)
        if language == "python":
            complexity = self.calculate_python_complexity(tree)

        return ModuleNode(
            path=rel_path,
            language=language,
            imports=imports,
            functions=functions,
            classes=classes,
            complexity_score=complexity,
            change_velocity_30d=0, # placeholders
            is_dead_code_candidate=False
        )

    def calculate_python_complexity(self, tree) -> float:
        # Simple cyclomatic complexity based on branching nodes
        query_str = """
        (if_statement) @if
        (for_statement) @for
        (while_statement) @while
        (except_clause) @except
        (boolean_operator) @bool
        """
        query = Query(self.router.py_lang, query_str)
        captures = query.captures(tree.root_node)
        return float(1 + len(captures))

    def extract_python_imports(self, tree, content) -> List[str]:
        query_str = """
        (import_statement (dotted_name) @name)
        (import_from_statement (dotted_name) @name)
        """
        query = Query(self.router.py_lang, query_str)
        captures = query.captures(tree.root_node)
        
        imports = []
        for node, tag in captures:
            imports.append(content[node.start_byte:node.end_byte].decode("utf-8"))
        return list(set(imports))

    def extract_python_functions(self, tree, content, parent_mod) -> List[FunctionNode]:
        query_str = """
        (function_definition
            name: (identifier) @name
            parameters: (parameters) @params)
        """
        query = Query(self.router.py_lang, query_str)
        captures = query.captures(tree.root_node)
        
        funcs = []
        for node, tag in captures:
            if tag == "name":
                name = content[node.start_byte:node.end_byte].decode("utf-8")
                # Look ahead for params if needed, but signature is enough for now
                funcs.append(FunctionNode(
                    qualified_name=f"{parent_mod}.{name}",
                    parent_module=parent_mod,
                    signature=name, # simplified
                    is_public_api=not name.startswith("_")
                ))
        return funcs

    def extract_python_classes(self, tree, content, parent_mod) -> List[ClassNode]:
        query_str = "(class_definition name: (identifier) @name)"
        query = Query(self.router.py_lang, query_str)
        captures = query.captures(tree.root_node)
        
        classes = []
        for node, tag in captures:
            name = content[node.start_byte:node.end_byte].decode("utf-8")
            classes.append(ClassNode(
                name=name,
                parent_module=parent_mod
            ))
        return classes

    def extract_sql_refs(self, tree, content) -> List[str]:
        # dbt uses {{ ref('...') }}
        # We search for template text for now
        text = content.decode("utf-8", errors="ignore")
        import re
        refs = re.findall(r"\{\{\s*ref\(['\"](.+?)['\"]\)\s*\}\}", text)
        return list(set(refs))

    def build_import_graph(self):
        for path, node in self.modules.items():
            for imp in node.imports:
                # Basic resolution: match import name against file paths
                for target_path in self.modules.keys():
                    if imp in target_path.replace("\\", ".").replace("/", "."):
                        self.graph.add_edge(path, target_path)

    def calculate_pagerank(self):
        if len(self.graph) > 0:
            self.pagerank_scores = nx.pagerank(self.graph)
            
    def detect_circular_dependencies(self) -> List[List[str]]:
        return list(nx.simple_cycles(self.graph))

    def save_graph(self, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Convert graph to serializable format
        data = {
            "nodes": {path: node.dict() for path, node in self.modules.items()},
            "edges": list(self.graph.edges()),
            "pagerank": self.pagerank_scores,
            "circular_dependencies": self.detect_circular_dependencies()
        }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def extract_git_velocity(self, days=30) -> Dict[str, int]:
        # Using git log as requested
        try:
            cmd = f"git log --since='{days} days ago' --name-only --format=format:"
            result = subprocess.run(cmd, shell=True, cwd=self.repo_path, capture_output=True, text=True)
            files = [f for f in result.stdout.splitlines() if f.strip()]
            from collections import Counter
            counts = Counter(files)
            for path, count in counts.items():
                if path in self.modules:
                    self.modules[path].change_velocity_30d = count
            return counts
        except Exception as e:
            print(f"Error extracting git velocity: {e}")
            return {}
