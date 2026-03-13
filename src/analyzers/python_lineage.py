import re
from typing import List
from src.models.nodes import TransformationNode


class PythonDataFlowAnalyzer:
    def __init__(self):
        pass

    def extract_lineage(self, file_path: str) -> List[TransformationNode]:
        """Extracts lineage information from a Python file."""
        try:
            with open(file_path, "rb") as f:
                content = f.read()
        except (IOError, OSError):
            return []

        transformations = []
        transformations.extend(self.detect_pandas_io(content, file_path))
        transformations.extend(self.detect_spark_io(content, file_path))
        return transformations

    def detect_pandas_io(self, content: bytes, file_path: str) -> List[TransformationNode]:
        """Detect pandas read_*/to_* I/O using regex."""
        text = content.decode("utf-8", errors="ignore")
        transformations = []

        # Match: pd.read_csv("path") or pandas.read_csv("path")
        read_pattern = re.compile(
            r'(?:pd|pandas)\.(read_\w+)\s*\(\s*["\']([^"\']+)["\']', re.MULTILINE
        )
        for m in read_pattern.finditer(text):
            attr_name, path_val = m.group(1), m.group(2)
            lineno = text[: m.start()].count("\n") + 1
            transformations.append(
                TransformationNode(
                    name=f"pandas_{attr_name}",
                    source_datasets=[path_val],
                    target_datasets=["df_variable"],
                    transformation_type="pandas_read",
                    source_file=file_path,
                    line_range=(lineno, lineno),
                )
            )

        # Match: df.to_csv("path") or df.to_parquet("path")
        write_pattern = re.compile(r'\.\s*(to_\w+)\s*\(\s*["\']([^"\']+)["\']', re.MULTILINE)
        for m in write_pattern.finditer(text):
            attr_name, path_val = m.group(1), m.group(2)
            lineno = text[: m.start()].count("\n") + 1
            transformations.append(
                TransformationNode(
                    name=f"pandas_{attr_name}",
                    source_datasets=["df_variable"],
                    target_datasets=[path_val],
                    transformation_type="pandas_write",
                    source_file=file_path,
                    line_range=(lineno, lineno),
                )
            )

        return transformations

    def detect_spark_io(self, content: bytes, file_path: str) -> List[TransformationNode]:
        """Detect Spark read/write I/O using regex."""
        text = content.decode("utf-8", errors="ignore")
        transformations = []

        # Match: spark.read.csv("path") or spark.read.parquet("path")
        read_pattern = re.compile(
            r'spark\s*\.\s*read\s*\.\s*(\w+)\s*\(\s*["\']([^"\']+)["\']', re.MULTILINE
        )
        for m in read_pattern.finditer(text):
            fmt, path_val = m.group(1), m.group(2)
            lineno = text[: m.start()].count("\n") + 1
            transformations.append(
                TransformationNode(
                    name=f"spark_read_{fmt}",
                    source_datasets=[path_val],
                    target_datasets=["spark_df"],
                    transformation_type="spark_read",
                    source_file=file_path,
                    line_range=(lineno, lineno),
                )
            )

        # Match: df.write.parquet("path") or df.write.saveAsTable("table")
        write_pattern = re.compile(
            r'\.\s*write\s*\.\s*(\w+)\s*\(\s*["\']([^"\']+)["\']', re.MULTILINE
        )
        for m in write_pattern.finditer(text):
            fmt, path_val = m.group(1), m.group(2)
            lineno = text[: m.start()].count("\n") + 1
            transformations.append(
                TransformationNode(
                    name=f"spark_write_{fmt}",
                    source_datasets=["spark_df"],
                    target_datasets=[path_val],
                    transformation_type="spark_write",
                    source_file=file_path,
                    line_range=(lineno, lineno),
                )
            )

        return transformations

    def detect_sqlalchemy_io(self, content: bytes, file_path: str) -> List[TransformationNode]:
        # Look for session.execute(sql) or engine.execute(sql) - kept as no-op
        return []
