from tree_sitter import Language, Parser, Query
import tree_sitter_python as tspython
import tree_sitter_yaml as tsyaml
import os
from typing import List, Dict, Any, Optional

class TreeSitterAnalyzer:
    def __init__(self):
        try:
            self.py_lang = Language(tspython.language())
            self.yaml_lang = Language(tsyaml.language())
            try:
                import tree_sitter_sql as tssql
                self.sql_lang = Language(tssql.language())
            except (ImportError, AttributeError):
                self.sql_lang = None
        except Exception as e:
            print(f"Error initializing TreeSitterAnalyzer: {e}")
            self.py_lang = None
            self.yaml_lang = None
            self.sql_lang = None

    def get_parser(self, file_path: str) -> Optional[Parser]:
        ext = os.path.splitext(file_path)[1].lower()
        lang = self.py_lang if ext == ".py" else (self.yaml_lang if ext in [".yml", ".yaml"] else self.sql_lang)
        return Parser(lang) if lang else None

    def extract_structure(self, file_path: str) -> Dict[str, Any]:
        """Extracts structural elements (imports, functions, classes) from the AST."""
        parser = self.get_parser(file_path)
        if not parser:
            return {}

        with open(file_path, "rb") as f:
            content = f.read()
            tree = parser.parse(content)

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".py":
            return {
                "imports": self._extract_python_imports(tree, content),
                "functions": self._extract_python_functions(tree, content),
                "classes": self._extract_python_classes(tree, content)
            }
        elif ext == ".sql":
            return {"refs": self._extract_sql_refs(content)}
        return {}

    def _extract_python_imports(self, tree, content) -> List[str]:
        query_str = "(import_statement (dotted_name) @name) (import_from_statement (dotted_name) @name)"
        query = Query(self.py_lang, query_str)
        return [content[node.start_byte:node.end_byte].decode("utf-8") for node, _ in query.captures(tree.root_node)]

    def _extract_python_functions(self, tree, content) -> List[Dict[str, Any]]:
        query_str = "(function_definition name: (identifier) @name)"
        query = Query(self.py_lang, query_str)
        return [{"name": content[node.start_byte:node.end_byte].decode("utf-8"), "is_public": not content[node.start_byte:node.end_byte].decode("utf-8").startswith("_")} for node, _ in query.captures(tree.root_node)]

    def _extract_python_classes(self, tree, content) -> List[str]:
        query_str = "(class_definition name: (identifier) @name)"
        query = Query(self.py_lang, query_str)
        return [content[node.start_byte:node.end_byte].decode("utf-8") for node, _ in query.captures(tree.root_node)]

    def _extract_sql_refs(self, content) -> List[str]:
        import re
        text = content.decode("utf-8", errors="ignore")
        return list(set(re.findall(r"\{\{\s*ref\(['\"](.+?)['\"]\)\s*\}\}", text)))
