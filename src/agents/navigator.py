import os
import logging
import networkx as nx
from typing import Literal
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from src.graph.knowledge_graph import KnowledgeGraph
from src.agents.archivist import ArchivistAgent

logger = logging.getLogger("NavigatorAgent")


class NavigatorAgent:
    """Conversational LangGraph agent to query the Knowledge Graph."""

    def __init__(self, kg: KnowledgeGraph, archivist: ArchivistAgent = None):
        self.kg = kg
        self.archivist = archivist
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning(
                "GEMINI_API_KEY not found. Navigator Agent requires an LLM to function interactively."
            )
            self.model = None
        else:
            # We use gemini-2.5-flash for rapid reasoning
            self.model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=api_key)

    def _build_tools(self):
        kg = self.kg  # capture in closure

        @tool
        def find_implementation(concept: str) -> str:
            """Semantic search: Finds where a generic business concept is implemented.
            Returns the path, line range (if applicable), and purpose statement as evidence.
            """
            if self.archivist:
                self.archivist.log_trace(
                    "Navigator_Tool: find_implementation", details={"concept": concept}
                )

            concept_lower = concept.lower()
            results = []
            for node, data in kg.graph.nodes(data=True):
                if data.get("type") == "module":
                    purpose = data.get("purpose_statement", "").lower()
                    if concept_lower in purpose or concept_lower in node.lower():
                        results.append(
                            f"Match: Module [{node}]\nEvidence: {data.get('purpose_statement')}\nFact_Source: LLM-Derived\nMethodology: Semantic Inference"
                        )
                elif data.get("type") == "transformation":
                    if concept_lower in data.get("name", "").lower():
                        results.append(
                            f"Match: Transformation [{data.get('name')}]\nEvidence: {data.get('source_file')}:{data.get('line_range')}\nFact_Source: Static\nMethodology: Static Parsing"
                        )

            if not results:
                return f"No modules or transformations found directly matching the concept '{concept}'.\nFact_Source: N/A\nMethodology: Semantic Sweep"
            return "\n---\n".join(results[:5])

        @tool
        def trace_lineage(
            dataset: str, direction: Literal["upstream", "downstream"] = "upstream"
        ) -> str:
            """Graph search: Traces the data lineage of a dataset/table.
            Returns the sequence of dependencies and transformations.
            """
            if self.archivist:
                self.archivist.log_trace(
                    "Navigator_Tool: trace_lineage",
                    details={"dataset": dataset, "direction": direction},
                )

            found = kg.graph.nodes.get(dataset)
            if not found:
                for n, d in kg.graph.nodes(data=True):
                    if d.get("type") == "dataset" and dataset.lower() in n.lower():
                        dataset = n
                        break
                else:
                    return f"Dataset '{dataset}' not found.\nFact_Source: Static\nMethodology: Node Existence Check"

            graph = nx.DiGraph(kg.graph)
            traversal = list(
                nx.bfs_edges(graph.reverse() if direction == "upstream" else graph, source=dataset)
            )

            trace = []
            for u, v in traversal[:15]:
                v_data = kg.graph.nodes[v]
                v_type = v_data.get("type")
                if v_type == "transformation":
                    trace.append(
                        f"-> Transformed by [{v_data.get('name')}] ({v_data.get('source_file')}:{v_data.get('line_range')})"
                    )
                else:
                    trace.append(f"-> Supported by Dataset [{v}]")

            return (
                f"Lineage Trace for [{dataset}] ({direction}):\n"
                + "\n".join(trace)
                + "\nFact_Source: Static\nMethodology: Lineage Graph Traversal (nx.bfs_edges)"
            )

        @tool
        def blast_radius(module_path: str) -> str:
            """Graph search: Finds everything that breaks if the specified module is changed.
            Includes downstream imports and data lineage dependencies.
            """
            if self.archivist:
                self.archivist.log_trace(
                    "Navigator_Tool: blast_radius", details={"module": module_path}
                )

            target = next((n for n in kg.graph.nodes if module_path in n), None)
            if not target:
                return f"Module '{module_path}' not found.\nFact_Source: Static\nMethodology: Node Lookup"

            graph = nx.DiGraph(kg.graph)
            try:
                descendants = list(nx.descendants(graph, target))
                impact_summary = []
                for d in descendants[:15]:
                    d_type = kg.graph.nodes[d].get("type", "unknown")
                    impact_summary.append(f"- Impacts {d_type}: {d}")

                return (
                    f"Blast Radius for [{target}] ({len(descendants)} total impactors):\n"
                    + "\n".join(impact_summary)
                    + "\nFact_Source: Static\nMethodology: Graph Connectivity Analysis (nx.descendants)"
                )
            except Exception as e:
                return f"Error analyzing blast radius: {e}"

        @tool
        def explain_module(path: str) -> str:
            """Generative: Explains what a specific module or file does based on extracted context."""
            target = next((n for n in kg.graph.nodes if path in n), None)
            if not target:
                return f"Module '{path}' not found.\nFact_Source: Static\nMethodology: Node Lookup"

            if self.archivist:
                self.archivist.log_trace("Navigator_Tool: explain_module", details={"path": path})

            data = kg.graph.nodes[target]
            return (
                f"Module: {target}\n"
                f"Purpose: {data.get('purpose_statement', 'N/A')}\n"
                f"Complexity: {data.get('complexity_score', 0):.3f}\n"
                f"Fact_Source: LLM-Derived (Purpose) | Static (Metrics)\n"
                f"Methodology: Combined Inference and Metrics Extraction"
            )

        return [find_implementation, trace_lineage, blast_radius, explain_module]

    def interactive_shell(self):
        """Starts a REPL session for querying the cartographer."""
        if not self.model:
            print("LLM Offline. Navigator cannot start.")
            return

        system_prompt = (
            "You are The Brownfield Cartographer's Navigator, a top-tier FDE assistant. "
            "Your goal is to provide high-fidelity architectural answers by chaining tools. "
            "\n\nSTRATEGY:\n"
            "1. Multi-Step Reasoning: If a query is complex, do not guess. Chain tools. "
            "Example: 'Find where ingestion is' -> `find_implementation` -> `trace_lineage` -> `blast_radius`. "
            "2. Evidence Labeling: Every fact you state MUST include its Fact_Source and Methodology. "
            "Static facts (Graph/Parsing) are higher confidence than LLM-Derived (Purpose statements). "
            "3. Verification: If you find an implementation via semantic search, verify it by checking its lineage or exports. "
            "\n\nOUTPUT FORMAT:\n"
            "Always include at the end of your response:\n"
            "- **Primary Evidence**: [File paths/Lines]\n"
            "- **Methodology**: [The tools/analysis types you used]\n"
            "- **Fact_Source**: [Static|LLM-Derived|Mixed]\n\n"
            "Be direct, technical, and precise. Avoid conversational fluff."
        )

        tools = self._build_tools()
        agent = create_react_agent(
            self.model,
            tools,
            state_modifier=system_prompt,
        )

        print("\n=============================================")
        print("Cartographer Navigator Agent Online.")
        print("Type 'exit' or 'quit' to terminate.")
        print("=============================================\n")

        while True:
            try:
                user_msg = input("navigator> ")
                if user_msg.lower() in ["exit", "quit", "q"]:
                    break
                if not user_msg.strip():
                    continue

                # Invoke LangGraph agent
                inputs = {"messages": [("user", user_msg)]}
                result = agent.invoke(inputs)

                # Print the final AI response
                print(f"\n{result['messages'][-1].content}\n")

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Agent error: {e}")
                print(f"Error: {e}")
