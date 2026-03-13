import os
import logging
import subprocess
from src.agents.surveyor import SurveyorAgent
from src.agents.hydrologist import HydrologistAgent
from src.agents.semanticist import SemanticistAgent
from src.agents.archivist import ArchivistAgent
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger("Orchestrator")


class CartographyOrchestrator:
    """Manages the full multi-agent Cartographer pipeline."""

    def __init__(self, repo_path: str, output_dir: str):
        self.repo_path = repo_path
        self.output_dir = output_dir
        self.kg = KnowledgeGraph()
        self.changed_files = None

        # Incremental state tracking
        os.makedirs(output_dir, exist_ok=True)
        self.state_file = os.path.join(output_dir, "last_commit.txt")
        self.current_commit = self._get_current_commit()

        # Load existing graph if available for incremental updates
        graph_path = os.path.join(output_dir, "lineage_graph.json")
        if os.path.exists(graph_path):
            try:
                self.kg.deserialize(graph_path)
                self.changed_files = self._get_changed_files()
            except Exception as e:
                logger.warning(f"Could not load previous graph, starting fresh: {e}")

        # Initialize core agents
        self.surveyor = SurveyorAgent(repo_path)
        self.surveyor.kg = self.kg  # Link shared KG
        self.hydrologist = HydrologistAgent(self.kg, repo_path)
        self.semanticist = SemanticistAgent(self.kg, repo_path)
        self.archivist = ArchivistAgent(self.kg, output_dir)

    def _get_current_commit(self):
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=self.repo_path, text=True
            ).strip()
        except Exception:
            return None

    def _get_changed_files(self):
        if not os.path.exists(self.state_file) or not self.current_commit:
            return None
        with open(self.state_file, "r") as f:
            last_commit = f.read().strip()

        if last_commit == self.current_commit:
            return []  # No changes

        try:
            out = subprocess.check_output(
                ["git", "diff", "--name-only", last_commit, self.current_commit],
                cwd=self.repo_path,
                text=True,
            )
            files = [f.strip() for f in out.splitlines() if f.strip()]
            logger.info(
                f"Incremental Update: Detected {len(files)} changed files since {last_commit[:7]}"
            )
            return set(files)
        except Exception as e:
            logger.warning(
                f"Failed to get git diff for incremental update, falling back to full: {e}"
            )
            return None

    def run_pipeline(self):
        """Runs the four-agent execution chain."""
        logger.info("Starting The Brownfield Cartographer Pipeline...")
        self.archivist.log_trace("Pipeline_Start", details={"path": self.repo_path})

        # Phase 1: Surveyor
        logger.info("Agent 1: Surveyor -> Analyzing Static Structure & Git Velocity")

        # In Surveyor, we can optimize by only processing changed files
        self.surveyor.analyze_codebase(changed_files=self.changed_files)
        self.surveyor.extract_git_velocity(days=30)
        self.archivist.log_trace("Surveyor_Complete", evidence="Module Graph Constructed")

        # Phase 2: Hydrologist
        logger.info("Agent 2: Hydrologist -> Constructing Data Lineage")
        self.hydrologist.analyze_lineage()
        self.archivist.log_trace("Hydrologist_Complete", evidence="Data Lineage Graph Constructed")

        # Save interim graph for Semanticist bulk node handling
        self.kg.serialize(os.path.join(self.output_dir, "module_graph.json"))

        # Phase 3: Semanticist
        logger.info("Agent 3: Semanticist -> Extracting Purposes and Clustering Domains")
        self.semanticist.run_bulk_semantics(changed_files=self.changed_files)
        self.archivist.log_trace(
            "Semanticist_Complete",
            evidence="Purpose Statements and Domains Assigned",
            details={"cost": f"${self.semanticist.budget.total_cost:.4f}"},
        )

        # Phase 4: Archivist
        logger.info("Agent 4: Archivist -> Generating Living Context Artifacts")
        self.archivist.generate_CODEBASE_md(self.surveyor)
        self.archivist.write_onboarding_brief(self.semanticist)

        # Final Graph Serialization
        self.kg.serialize(os.path.join(self.output_dir, "lineage_graph.json"))

        if self.current_commit:
            with open(self.state_file, "w") as f:
                f.write(self.current_commit)

        self.archivist.log_trace("Pipeline_Complete", evidence="All JSON/MD Artifacts written.")

        logger.info(f"Done! Cartography outputs available in {self.output_dir}")
