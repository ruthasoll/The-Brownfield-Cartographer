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

    def _static_day_one_brief(self, surveyor: SurveyorAgent) -> str:
        """Generates a fully-static Day-One brief from static analysis data alone.
        Used as a fallback when the LLM is offline, and as Appendix A in any event.
        """
        modules = list(surveyor.modules.values())

        # Top hubs by complexity
        hubs = sorted(modules, key=lambda m: m.complexity_score or 0, reverse=True)[:5]
        hub_lines = "\n".join(
            [f"  - `{m.path}` (PageRank: {m.complexity_score or 0:.3f})" for m in hubs]
        )

        # Highest velocity
        hot = sorted(
            modules,
            key=lambda m: getattr(m, "change_velocity_30d", 0) or 0,
            reverse=True,
        )[:5]
        hot_lines = "\n".join(
            [
                f"  - `{m.path}` ({getattr(m, 'change_velocity_30d', 0) or 0} commits/30d)"
                for m in hot
            ]
        )

        # Data lineage stats from KG
        ds_nodes = [d for n, d in self.kg.graph.nodes(data=True) if d.get("type") == "dataset"]
        tr_nodes = [
            d for n, d in self.kg.graph.nodes(data=True) if d.get("type") == "transformation"
        ]

        # Unique input datasets (no incoming edges in lineage graph)
        try:
            import networkx as nx

            g = nx.DiGraph(self.kg.graph)
            source_datasets = [
                n
                for n, d in self.kg.graph.nodes(data=True)
                if d.get("type") == "dataset" and g.in_degree(n) == 0
            ]
            sink_datasets = [
                n
                for n, d in self.kg.graph.nodes(data=True)
                if d.get("type") == "dataset" and g.out_degree(n) == 0
            ]
        except Exception:
            source_datasets, sink_datasets = [], []

        src_lines = "\n".join([f"  - `{n}`" for n in source_datasets[:5]]) or "  - None detected"
        sink_lines = "\n".join([f"  - `{n}`" for n in sink_datasets[:5]]) or "  - None detected"

        # Dead code candidates (Python only)
        dead = [
            m
            for m in modules
            if getattr(m, "is_dead_code_candidate", False) and m.language == "python"
        ]
        dead_lines = "\n".join([f"  - `{m.path}`" for m in dead[:8]]) or "  - None detected"

        # Circular dependencies / SCCs from surveyor
        cycles = getattr(surveyor, "circular_dependencies", [])
        cycle_lines = (
            "\n".join([f"  - {' -> '.join(c)}" for c in cycles[:5]])
            if cycles
            else "  - None detected"
        )

        return f"""## Q1. What is the primary data ingestion path?
*Evidence: Graph topology, static file analysis*

**Source Datasets (roots with no upstream dependencies):**
{src_lines}

**Transformation count:** {len(tr_nodes)} transformations detected across Python, SQL, and YAML.

---

## Q2. What are the 3-5 most critical output datasets/endpoints?
*Evidence: Lineage graph sink nodes*

**Output / Sink Datasets:**
{sink_lines}

---

## Q3. What is the blast radius if the most critical module fails?
*Evidence: Complexity/PageRank scoring*

**Highest-impact architectural hubs (by PageRank):**
{hub_lines}

Failure in the top hub would cascade to all downstream modules and datasets via the lineage graph.

---

## Q4. Where is the business logic concentrated vs. distributed?
*Evidence: Git velocity + complexity*

**Highest-velocity files (most actively changed = active concern):**
{hot_lines}

**Total modules** analyzed: {len(modules)}
**Data transformations**: {len(tr_nodes)} | **Datasets tracked**: {len(ds_nodes)}

---

## Q5. What has changed most frequently in the last 30 days?
*Evidence: git log --since=30d*

{hot_lines}

**Circular dependency risk:**
{cycle_lines}

**Dead code candidates (Python):**
{dead_lines}

---
*Note: This brief was generated from static analysis only. Run with `GEMINI_API_KEY` set for LLM-enriched answers.*
"""

    def write_onboarding_brief(self, semanticist: SemanticistAgent, surveyor: SurveyorAgent = None):
        """Writes the Day-One FDE brief. Uses LLM when available, static analysis as fallback."""
        brief_path = os.path.join(self.output_dir, "onboarding_brief.md")
        logger.info(f"Generating Onboarding Brief -> {brief_path}")

        self.log_trace(
            "Synthesize_Day_One_Brief",
            evidence="Surveyor + Hydrologist Graph",
            details={"model": "gemini-2.5-flash"},
        )

        # Try LLM first
        llm_answers = semanticist.answer_day_one_questions()

        # Build static analysis section regardless
        static_section = ""
        if surveyor:
            static_section = self._static_day_one_brief(surveyor)

        if "LLM Offline" in (llm_answers or "") or "Cannot generate" in (llm_answers or ""):
            # Fully offline — use static only
            answers_section = static_section
            llm_note = "*⚠ LLM Offline. The following answers are derived entirely from static code analysis.*\n\n"
        else:
            # LLM answered — static is Appendix A
            answers_section = llm_answers
            if static_section:
                answers_section += (
                    f"\n\n---\n\n## Appendix A: Static Analysis Evidence\n\n{static_section}"
                )
            llm_note = ""

        content = f"""# FDE Day-One Onboarding Brief
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

{llm_note}## The 5 FDE Day-One Questions
{answers_section}
"""
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(content)

        self.log_trace("Onboarding_Brief_Written", evidence=brief_path, confidence=1.0)

    def generate_CODEBASE_md(self, surveyor: SurveyorAgent):
        """Generates the living context for direct injection into an AI agent."""
        codebase_path = os.path.join(self.output_dir, "CODEBASE.md")
        logger.info(f"Generating Living Context -> {codebase_path}")

        modules = list(surveyor.modules.values())

        # 1. Architecture Hubs
        hubs = sorted(modules, key=lambda x: x.complexity_score or 0, reverse=True)[:5]
        hubs_md = "\n".join(
            [
                f"- `{m.path}` (PageRank: {m.complexity_score or 0:.3f}) — {(getattr(m, 'purpose_statement', None) or 'Purpose not extracted')}"
                for m in hubs
            ]
        )

        # 2. High-velocity files
        hot = sorted(
            modules, key=lambda x: getattr(x, "change_velocity_30d", 0) or 0, reverse=True
        )[:5]
        velocity_md = "\n".join(
            [f"- `{m.path}` ({getattr(m, 'change_velocity_30d', 0) or 0} changes/30d)" for m in hot]
        )

        # 3. Dead code — PYTHON ONLY
        dead_md = "\n".join(
            [
                f"- `{m.path}` (0 inbound module references)"
                for m in modules
                if getattr(m, "is_dead_code_candidate", False) and m.language == "python"
            ]
        )

        # 4. Documentation drift
        drift_md = "\n".join(
            [
                f"- `{m.path}` (docstring vs implementation mismatch)"
                for m in modules
                if "Documentation Drift" in (getattr(m, "purpose_statement", "") or "")
            ]
        )

        # 5. Domain clusters
        domain_dict: dict = {}
        for m in modules:
            domain = getattr(m, "domain_cluster", "Unclustered")
            domain_dict.setdefault(domain, []).append(m.path)

        domain_md = ""
        for d, paths in sorted(domain_dict.items()):
            domain_md += f"### {d}\n"
            for p in paths[:4]:
                domain_md += f"- `{p}`\n"
            if len(paths) > 4:
                domain_md += f"- *...and {len(paths) - 4} more*\n"

        # 6. Lineage stats from KG
        ds_count = sum(1 for _, d in self.kg.graph.nodes(data=True) if d.get("type") == "dataset")
        tr_count = sum(
            1 for _, d in self.kg.graph.nodes(data=True) if d.get("type") == "transformation"
        )

        content = f"""# CODEBASE CONTEXT (The Brownfield Cartographer)
*Auto-generated Context Injection File — designed for AI agent system prompts*
*Date: {datetime.now().strftime("%Y-%m-%d")} | Modules: {len(modules)} | Datasets: {ds_count} | Transformations: {tr_count}*

## Critical Path (Top Architectural Hubs by PageRank)
{hubs_md}

## High-Velocity Files (Active Development / Churn Risk)
{velocity_md}

## Known Debt & Risk Vectors

**Dead Code Candidates (Python modules with no inbound references):**
{dead_md or "- None detected."}

**Documentation Drift (docstring vs. implementation mismatch):**
{drift_md or "- None detected."}

## Inferred Domain Boundaries
*Semantically clustered by TF-IDF over LLM purpose statements:*
{domain_md or "- No domains computed (run with GEMINI_API_KEY for clustering)."}

> *Inject this file into any AI agent system prompt to provide instant codebase working memory.*
"""
        with open(codebase_path, "w", encoding="utf-8") as f:
            f.write(content)
        self.log_trace("Generate_CODEBASE_md", evidence="Aggregated Cartography", confidence=1.0)

    def generate_interim_report(self, surveyor: SurveyorAgent):
        """Updates the interim_report.md with findings from the full pipeline run."""
        report_path = os.path.join(os.path.dirname(self.output_dir), "interim_report.md")
        logger.info(f"Updating Interim Report -> {report_path}")

        modules = list(surveyor.modules.values())
        hubs = sorted(modules, key=lambda m: m.complexity_score or 0, reverse=True)[:3]
        hub_lines = "\n".join(
            [f"  - `{m.path}` (PageRank={m.complexity_score or 0:.3f})" for m in hubs]
        )

        ds_count = sum(1 for _, d in self.kg.graph.nodes(data=True) if d.get("type") == "dataset")
        tr_count = sum(
            1 for _, d in self.kg.graph.nodes(data=True) if d.get("type") == "transformation"
        )
        mod_count = len(modules)

        cycles = getattr(surveyor, "circular_dependencies", [])
        cycle_lines = (
            "\n".join([f"  - {' -> '.join(c)}" for c in cycles[:3]])
            if cycles
            else "  - None detected"
        )

        report_content = f"""# Brownfield Cartographer — Interim Report

*Auto-generated by The Brownfield Cartographer*
*Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*

## Pipeline Execution Summary

| Agent | Status |
|---|---|
| Surveyor (Static Analysis) | ✅ Complete |
| Hydrologist (Data Lineage) | ✅ Complete |
| Semanticist (LLM Semantics) | ✅ Complete |
| Archivist (Artifact Generation) | ✅ Complete |

## Codebase Metrics

| Metric | Value |
|---|---|
| Total Modules Analyzed | {mod_count} |
| Datasets Tracked (lineage) | {ds_count} |
| Transformations Identified | {tr_count} |
| Circular Dependencies | {len(cycles)} |

## Top Architectural Hubs (Critical Path)
{hub_lines}

## Risk Vectors

**Circular Dependencies:**
{cycle_lines}

## Deliverables

All deliverables are available in `.cartography/`:
- `module_graph.json` — Static module dependency graph
- `lineage_graph.json` — Full data lineage knowledge graph
- `CODEBASE.md` — Living codebase context (AI-injectable)
- `onboarding_brief.md` — 5 FDE Day-One answers
- `cartography_trace.jsonl` — Append-only agent action audit log
- `last_commit.txt` — Baseline commit for incremental re-runs
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        self.log_trace("Interim_Report_Written", evidence=report_path, confidence=1.0)
        logger.info("Interim report updated.")
