import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from src.models.edges import EdgeMetadata, RelationshipType
from src.models.nodes import ModuleNode
from src.graph.knowledge_graph import KnowledgeGraph
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.agents.surveyor import SurveyorAgent


def test_schema_validation():
    print("Testing Schema Validation...")
    kg = KnowledgeGraph()
    m_data = ModuleNode(path="test.py", language="python")
    kg.add_node("test.py", m_data, "module")

    # Valid edge
    meta = EdgeMetadata(rel_type=RelationshipType.IMPORTS, confidence=0.9)
    kg.add_edge("test.py", "test.py", meta)

    # Invalid edge should raise error via Pydantic validator before hitting kg
    try:
        EdgeMetadata(rel_type="INVALID_REL", confidence=0.9)  # type: ignore
        print("  ❌ Schema validation failed to catch invalid rel_type.")
    except Exception:
        print("  ✅ Schema validation correctly caught invalid rel_type.")


def test_cte_resolution():
    print("Testing CTE Resolution...")
    sql = """
        with cte1 as (
            select id from source_table_1
        ),
        cte2 as (
            select id from source_table_2
            join cte1 on cte1.id = source_table_2.id
        )
        select * from cte2
    """

    analyzer = SQLLineageAnalyzer()
    lineage = analyzer.extract_lineage(sql, "test.sql")

    if len(lineage) == 1:
        sources = set(lineage[0].source_datasets)
        if sources == {"source_table_1", "source_table_2"}:
            print("  ✅ CTE Resolution correctly resolved base tables and excluded CTE names.")
        else:
            print(
                f"  ❌ CTE Resolution failure. Expected {{'source_table_1', 'source_table_2'}}, got {sources}"
            )
    else:
        print("  ❌ CTE Resolution failure. Expected 1 transformation node.")


def test_circular_detection():
    print("Testing Circular Dependency Detection (SCC)...")
    surveyor = SurveyorAgent(".")
    kg = surveyor.kg

    # Create artificial cycle: A -> B -> C -> A
    m = ModuleNode(path="test", language="python")
    for n in ["A", "B", "C"]:
        kg.add_node(n, m, "module")

    meta = EdgeMetadata(rel_type=RelationshipType.IMPORTS)
    kg.add_edge("A", "B", meta)
    kg.add_edge("B", "C", meta)
    kg.add_edge("C", "A", meta)

    # Mock surveyor modules
    surveyor.modules = {"A": m, "B": m, "C": m}
    surveyor.detect_circular_dependencies()

    if m.domain_cluster == "circular_cluster":
        print("  ✅ Circular Dependency Detection successfully detected cluster A->B->C.")
    else:
        print("  ❌ Circular Dependency Detection failed.")


if __name__ == "__main__":
    print("--- Starting Rubric Refinement Verification Tests ---")
    test_schema_validation()
    test_cte_resolution()
    test_circular_detection()
    print("--- Tests Complete ---")
