import os
import json
import logging
from datetime import datetime
from src.graph.knowledge_graph import KnowledgeGraph
from src.agents.semanticist import SemanticistAgent
from src.agents.surveyor import SurveyorAgent

logger = logging.getLogger("ArchivistAgent")


class ArchivistAgent:
    """Produces and maintains the system's outputs as living artifacts."""

    def __init__(self, kg: KnowledgeGraph, output_dir: str):
        self.kg = kg
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.trace_file = os.path.join(output_dir, "cartography_trace.jsonl")

    def log_trace(
        self, action: str, evidence: str = "N/A", confidence: float = 1.0, details: dict = None
    ):
        """Append-only audit log of agent actions."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "evidence": evidence,
            "confidence": confidence,
            "details": details or {},
        }
        with open(self.trace_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def write_onboarding_brief(self, semanticist: SemanticistAgent):
        """Writes the day-one answers to a brief."""
        brief_path = os.path.join(self.output_dir, "onboarding_brief.md")
        logger.info(f"Generating Onboarding Brief -> {brief_path}")

        self.log_trace(
            "Synthesize_Day_One_Brief",
            evidence="Surveyor + Hydrologist Graph",
            details={"model": "gemini-2.5-flash"},
        )
        answers = semanticist.answer_day_one_questions()

        content = f"""# FDE Day-One Onboarding Brief
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## The 5 critical FDE Questions:
{answers}
"""
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(content)

    def generate_CODEBASE_md(self, surveyor: SurveyorAgent):
        """Generates the living context for direct injection into an AI agent."""
        codebase_path = os.path.join(self.output_dir, "CODEBASE.md")
        logger.info(f"Generating Living Context -> {codebase_path}")

        # Extract necessary pieces
        modules = [n for p, n in surveyor.modules.items()]

        # 1. Architecture Hubs
        hubs = sorted(modules, key=lambda x: x.complexity_score or 0, reverse=True)[:5]
        hubs_md = "\n".join(
            [
                f"- `{m.path}` (Score: {m.complexity_score or 0:.2f}) - {getattr(m, 'purpose_statement', 'No Purpose Extracted')}"
                for m in hubs
            ]
        )

        # 2. Known Debt / Circular / Velocity
        velocity_md = "\n".join(
            [
                f"- `{m.path}` ({getattr(m, 'change_velocity_30d', 0) or 0} changes/30d)"
                for m in sorted(
                    modules, key=lambda x: getattr(x, "change_velocity_30d", 0) or 0, reverse=True
                )[:5]
            ]
        )

        dead_md = "\n".join(
            [
                f"- `{m.path}` (Suspected dead code, 0 inbound references)"
                for m in modules
                if getattr(m, "is_dead_code_candidate", False)
            ]
        )

        drift_md = "\n".join(
            [
                f"- `{m.path}` (Doc string differs from implementation)"
                for m in modules
                if "Documentation Drift" in (getattr(m, "purpose_statement", "") or "")
            ]
        )

        # 3. Domains
        # Group by domain
        domain_dict = {}
        for m in modules:
            domain = getattr(m, "domain_cluster", "Unclustered")
            if domain not in domain_dict:
                domain_dict[domain] = []
            domain_dict[domain].append(m.path)

        domain_md = ""
        for d, paths in domain_dict.items():
            domain_md += f"### {d}\n"
            for p in paths[:3]:  # show top 3 per domain to save space
                domain_md += f"- `{p}`\n"
            if len(paths) > 3:
                domain_md += f"- *...and {len(paths) - 3} more files*\n"

        content = f"""# CODEBASE CONTEXT (The Brownfield Cartographer)
*Auto-generated Context Injection File*
*Date:* {datetime.now().strftime("%Y-%m-%d")}

## Architecture Overview (Top Hubs / Critical Path)
These modules form the structural backbone of the system based on PageRank in-degree metrics.
{hubs_md}

## High-Velocity Files (Pain Points)
These files change most frequently in git and represent active development or constant churn:
{velocity_md}

## Known Debt & Risk Vectors
**Dead Code Candidates (0 inbound module references):**
{dead_md or "- None detected."}

**Documentation Drift:**
{drift_md or "- None detected."}

## Domain Boundaries
*Semantically inferred architectural layers:*
{domain_md}

> *Note: This file is designed to be injected into an AI agent's system prompt to build instant working memory of the codebase.*
"""
        with open(codebase_path, "w", encoding="utf-8") as f:
            f.write(content)
        self.log_trace("Generate_CODEBASE_md", evidence="Aggregated Cartography", confidence=1.0)
