from tree_sitter import Query, Language, Parser
import tree_sitter_python as tspython
from typing import List, Dict, Any, Optional
from src.models.nodes import DatasetNode, TransformationNode

class PythonDataFlowAnalyzer:
    def __init__(self):
        self.py_lang = Language(tspython.language())
        self.parser = Parser(self.py_lang)

    def extract_lineage(self, file_path: str) -> List[TransformationNode]:
        """Extracts lineage information from a Python file."""
        with open(file_path, "rb") as f:
            content = f.read()
            tree = self.parser.parse(content)

        transformations = []
        
        # Detect pandas read_* and to_*
        transformations.extend(self.detect_pandas_io(tree, content, file_path))
        
        # Detect Spark read/write
        transformations.extend(self.detect_spark_io(tree, content, file_path))
        
        # Detect SQLAlchemy execute
        transformations.extend(self.detect_sqlalchemy_io(tree, content, file_path))

        return transformations

    def detect_pandas_io(self, tree, content, file_path) -> List[TransformationNode]:
        # Query for pandas read_csv, read_sql, etc.
        # Pattern: call(attribute(identifier(pandas), identifier(read_...)), ...)
        io_query = """
        (call
          function: (attribute
            object: (identifier) @obj
            attribute: (identifier) @attr)
          arguments: (argument_list (string) @path))
        """
        query = Query(self.py_lang, io_query)
        captures = query.captures(tree.root_node)

        transformations = []
        for node, tag in captures:
            if tag == "attr":
                attr_name = content[node.start_byte:node.end_byte].decode("utf-8")
                if attr_name.startswith("read_"):
                    # This is a source
                    path_node = None
                    # Find path in capturing nodes
                    for n, t in captures:
                        if t == "path" and n.parent == node.parent.parent: # Simple check
                             path_node = n
                    
                    if path_node:
                        path_val = content[path_node.start_byte:path_node.end_byte].decode("utf-8").strip("'\"")
                        transformations.append(TransformationNode(
                            name=f"pandas_{attr_name}",
                            source_datasets=[path_val],
                            target_datasets=["df_variable"], # Placeholder, would need variable tracking for full depth
                            transformation_type="pandas_read",
                            source_file=file_path,
                            line_range=(node.start_point[0] + 1, node.end_point[0] + 1)
                        ))
                elif attr_name.startswith("to_"):
                    # This is a sink
                    pass # Similar logic for sinks

        return transformations

    def detect_spark_io(self, tree, content, file_path) -> List[TransformationNode]:
        # Spark patterns are often chainable: spark.read.format(...).load(...)
        # For now, let's look for .load() and .save() calls with string arguments
        return [] # TODO: Implement more complex pattern matching

    def detect_sqlalchemy_io(self, tree, content, file_path) -> List[TransformationNode]:
        # Look for session.execute(sql) or engine.execute(sql)
        return []
