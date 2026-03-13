from tree_sitter import Language, Parser, Query
import tree_sitter_python as tspython
import tree_sitter_yaml as tsyaml
import os
import logging
from typing import List, Dict, Any, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TreeSitterAnalyzer")


class TreeSitterAnalyzer:
    def __init__(self):
        self.parsers: Dict[str, Parser] = {}
        try:
            self.py_lang = Language(tspython.language())
            self.yaml_lang = Language(tsyaml.language())
            try:
                import tree_sitter_sql as tssql

                self.sql_lang = Language(tssql.language())
            except (ImportError, AttributeError):
                self.sql_lang = None
                logger.warning(
                    "SQL grammar (tree-sitter-sql) not found. SQL parsing will be degraded."
                )
        except Exception as e:
            logger.error(f"Critical failure initializing Tree-Sitter grammars: {e}")
            self.py_lang = None
            self.yaml_lang = None
            self.sql_lang = None

    def get_parser(self, file_path: str) -> Optional[Parser]:
        ext = os.path.splitext(file_path)[1].lower()
        lang = None
        if ext == ".py":
            lang = self.py_lang
        elif ext in [".yml", ".yaml"]:
            lang = self.yaml_lang
        elif ext == ".sql":
            lang = self.sql_lang
        else:
            logger.debug(f"Unsupported file extension: {ext} for {file_path}")
            return None

        if not lang:
            logger.error(f"Grammar load failure for extension {ext}")
            return None

        return Parser(lang)

    def extract_structure(self, file_path: str) -> Dict[str, Any]:
        """Exposes a clean, reusable API for structural discovery."""
        parser = self.get_parser(file_path)
        if not parser:
            return {}

        try:
            with open(file_path, "rb") as f:
                content = f.read()
                tree = parser.parse(content)
        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return {}

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".py":
            return {
                "imports": self._extract_python_imports(tree, content),
                "functions": self._extract_python_functions(tree, content),
                "classes": self._extract_python_classes(tree, content),
            }
        elif ext == ".sql":
            return {
                "refs": self._extract_sql_refs(content),
                "tables": self._extract_sql_tables(tree, content),
            }
        elif ext in [".yml", ".yaml"]:
            return {"hierarchy": self._extract_yaml_hierarchy(tree, content)}

        return {}

    def _extract_python_imports(self, tree, content) -> List[str]:
        query_str = (
            "(import_statement (dotted_name) @name) (import_from_statement (dotted_name) @name)"
        )
        query = Query(self.py_lang, query_str)
        return [
            content[node.start_byte : node.end_byte].decode("utf-8")
            for node, _ in query.captures(tree.root_node)
        ]

    def _extract_python_functions(self, tree, content) -> List[Dict[str, Any]]:
        query_str = "(function_definition name: (identifier) @name)"
        query = Query(self.py_lang, query_str)
        return [
            {
                "name": content[node.start_byte : node.end_byte].decode("utf-8"),
                "is_public": not content[node.start_byte : node.end_byte]
                .decode("utf-8")
                .startswith("_"),
            }
            for node, _ in query.captures(tree.root_node)
        ]

    def _extract_python_classes(self, tree, content) -> List[str]:
        query_str = "(class_definition name: (identifier) @name)"
        query = Query(self.py_lang, query_str)
        return [
            content[node.start_byte : node.end_byte].decode("utf-8")
            for node, _ in query.captures(tree.root_node)
        ]

    def _extract_sql_refs(self, content) -> List[str]:
        import re

        text = content.decode("utf-8", errors="ignore")
        return list(set(re.findall(r"\{\{\s*ref\(['\"](.+?)['\"]\)\s*\}\}", text)))

    def _extract_sql_tables(self, tree, content) -> List[str]:
        """Deep SQL parsing for table names in FROM, JOIN, and CTEs."""
        if not self.sql_lang:
            return []

        # This query targets typical relation identifiers in FROM and JOIN clauses
        # and CTE names in WITH clauses.
        query_str = """
        (relation (identifier) @table)
        (common_table_expression name: (identifier) @cte)
        """
        tables = []
        ctes = []
        try:
            query = Query(self.sql_lang, query_str)
            for node, tag in query.captures(tree.root_node):
                name = content[node.start_byte : node.end_byte].decode("utf-8").lower()
                if tag == "table":
                    tables.append(name)
                elif tag == "cte":
                    ctes.append(name)
        except Exception as e:
            logger.warning(f"Tree-sitter SQL query error, parsing degraded: {e}")
            return []

        # Return physical tables that are NOT CTE definitions
        return list(set([t for t in tables if t not in ctes]))

    def _extract_yaml_hierarchy(self, tree, content) -> Dict[str, Any]:
        """Recursive YAML walker to extract key hierarchy."""

        def walk(node):
            if node.type == "block_mapping_pair":
                key_node = node.child_by_field_name("key")
                val_node = node.child_by_field_name("value")
                if key_node and val_node:
                    key = content[key_node.start_byte : key_node.end_byte].decode("utf-8").strip()
                    return {key: walk(val_node)}
            elif node.type == "block_mapping":
                result = {}
                for child in node.children:
                    res = walk(child)
                    if isinstance(res, dict):
                        result.update(res)
                return result
            elif node.type == "block_sequence":
                return [
                    walk(child) for child in node.children if child.type == "block_sequence_item"
                ]
            elif node.type == "block_sequence_item":
                # Item usually has one child which is the value
                for child in node.children:
                    if child.type not in ["-", " "]:
                        return walk(child)
            # Scalar
            return content[node.start_byte : node.end_byte].decode("utf-8").strip()

        return walk(tree.root_node)
