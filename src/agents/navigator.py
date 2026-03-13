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
            # Iterate through module purpose statements to find semantic matches
            # A real vector DB would do cosine similarity, here we do a basic keyword/fuzzy search
            # or rely on the LLM to interpret the output of a broad sweep.
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
                            f"Match: Module [{node}]\nEvidence: {data.get('purpose_statement')}\nMethod: Semantic Inference"
                        )
                elif data.get("type") == "transformation":
                    if concept_lower in data.get("name", "").lower():
                        results.append(
                            f"Match: Transformation [{data.get('name')}]\nEvidence: {data.get('source_file')}:{data.get('line_range')}\nMethod: Static Parsing"
                        )

            if self.archivist:
                # Update details with match count if possible later, or just log start
                pass

            if not results:
                return f"No modules or transformations found directly matching the concept '{concept}'.\nMethod: Semantic Inference (Purpose Statements)"
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

            if dataset not in kg.graph:
                # Try to fuzzy match
                found = None
                for n, d in kg.graph.nodes(data=True):
                    if d.get("type") == "dataset" and dataset.lower() in n.lower():
                        found = n
                        break
                if not found:
                    return f"Dataset '{dataset}' not found in the Knowledge Graph. (Method: Graph Traversal)"
                dataset = found

            graph = nx.DiGraph(kg.graph)
            if direction == "upstream":
                # Reverse graph for upstream tracing
                edges = nx.bfs_edges(graph.reverse(), source=dataset)
            else:
                edges = nx.bfs_edges(graph, source=dataset)

            trace = []
            for u, v in edges:
                # 'v' is the node we transitioned to
                v_data = kg.graph.nodes[v]
                v_type = v_data.get("type")
                if v_type == "transformation":
                    trace.append(
                        f"<- Transformed by [{v_data.get('name')}] at {v_data.get('source_file')}:{v_data.get('line_range')}"
                    )
                elif v_type == "dataset":
                    trace.append(f"<- Supported by Dataset [{v}]")

            if not trace:
                return f"No {direction} dependencies found for {dataset}.\nEvidence: MultiDiGraph lookup\nMethod: Lineage Graph Traversal"

            out = f"Lineage Trace for [{dataset}] ({direction}):\n"
            out += "\n".join(trace)
            out += "\nMethod: Graph Traversal (nx.bfs_edges)"
            return out

        @tool
        def blast_radius(module_path: str) -> str:
            """Graph search: Finds everything that breaks if the specified module is changed.
            Includes downstream imports and data lineage dependencies.
            """
            if self.archivist:
                self.archivist.log_trace(
                    "Navigator_Tool: blast_radius", details={"module": module_path}
                )

            # Standardize path
            target = None
            for n in kg.graph.nodes:
                if module_path in n:
                    target = n
                    break

            if not target:
                return f"Module '{module_path}' not found. (Method: Graph Traversal)"

            graph = nx.DiGraph(kg.graph)
            try:
                descendants = nx.descendants(graph, target)
                if self.archivist:
                    self.archivist.log_trace(
                        "Navigator_Tool: blast_radius",
                        details={"module": module_path, "impact_count": len(descendants)},
                    )

                results = [f"Downstream Blast Radius for {target}:"]
                for d in list(descendants)[:20]:
                    d_data = kg.graph.nodes[d]
                    d_type = d_data.get("type", "unknown")
                    if d_type == "module":
                        results.append(f"- Impacts Module: {d}")
                    else:
                        results.append(f"- Impacts {d_type}: {d}")

                results.append(
                    f"Evidence: Graph descendants lookup ({len(descendants)} total impactors)"
                )
                results.append("Method: Graph Traversal (nx.descendants)")
                return "\n".join(results)
            except Exception as e:
                if self.archivist:
                    self.archivist.log_trace(
                        "Navigator_Tool_Error: blast_radius",
                        details={"module": module_path, "error": str(e)},
                    )
                return f"Error executing Graph Traversal: {e}"

        @tool
        def explain_module(path: str) -> str:
            """Generative: Explains what a specific module or file does based on extracted context."""
            target = None
            for n in kg.graph.nodes:
                if path in n:
                    target = n
                    break

            if not target:
                return f"Module '{path}' not found."

            if self.archivist:
                self.archivist.log_trace("Navigator_Tool: explain_module", details={"path": path})

            data = kg.graph.nodes[target]
            purpose = data.get("purpose_statement", "No LLM purpose extracted.")
            complexity = data.get("complexity_score", 0)
            velocity = data.get("change_velocity_30d", 0)

            return (
                f"Module: {target}\n"
                f"Evidence: Purpose Header + Git Statistics\n"
                f"Purpose: {purpose}\n"
                f"Complexity Score (PageRank): {complexity:.3f}\n"
                f"Change Velocity (30d): {velocity} commits\n"
                "Method: LLM Inference + Git Log Analysis"
            )

        return [find_implementation, trace_lineage, blast_radius, explain_module]

    def interactive_shell(self):
        """Starts a REPL session for querying the cartographer."""
        if not self.model:
            print("LLM Offline. Navigator cannot start.")
            return

        tools = self._build_tools()
        agent = create_react_agent(
            self.model,
            tools,
            state_modifier="You are The Brownfield Cartographer's Navigator interface. You use tools to answer questions about architecture, graphs, and data lineage. Always cite the exact evidence (file path, line range) and the method (Graph Traversal, Semantic Inference, Static Parsing) when answering. Be direct and concise like a senior engineer.",
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
