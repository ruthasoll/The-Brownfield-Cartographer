import os
import json
import logging
from typing import Optional
from google import genai
from google.genai import types
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

from src.models.nodes import ModuleNode
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger("SemanticistAgent")


class ContextWindowBudget:
    """Tracks token usage and cost for LLM operations."""

    def __init__(self, max_tokens_per_call: int = 2000000):
        self.max_tokens_per_call = max_tokens_per_call
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0  # Estimated USD

        # Rough estimates for Gemini Flash (e.g., $0.075 / 1M input, $0.30 / 1M output)
        self.input_cost_per_m = 0.075
        self.output_cost_per_m = 0.30

    def log_usage(self, prompt_tokens: int, completion_tokens: int):
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost += (prompt_tokens / 1_000_000) * self.input_cost_per_m
        self.total_cost += (completion_tokens / 1_000_000) * self.output_cost_per_m

    def summary(self) -> str:
        return f"Tokens: {self.total_prompt_tokens} in / {self.total_completion_tokens} out. Est Cost: ${self.total_cost:.4f}"


class SemanticistAgent:
    def __init__(self, kg: KnowledgeGraph, repo_path: str):
        self.kg = kg
        self.repo_path = repo_path
        self.budget = ContextWindowBudget()
        self.force_static = False

        self.model_name = "gemini-2.0-flash"
        self.heavy_model_name = "gemini-1.5-pro"

        # Initialize Gemini Client if API key is present
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = None
            logger.warning(
                "GEMINI_API_KEY not found. Semanticist will degrade to static heuristics."
            )

    def _call_llm(
        self, prompt: str, system_instruction: str = None, model: str = None
    ) -> Optional[str]:
        if self.force_static or not self.client:
            return None

        target_model = model or self.model_name
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction, temperature=0.1
            )
            response = self.client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config,
            )

            # Extract usage if available
            try:
                usage = response.usage_metadata
                if usage:
                    self.budget.log_usage(usage.prompt_token_count, usage.candidates_token_count)
            except AttributeError:
                pass  # Usage not provided by this model version

            return response.text
        except Exception as e:
            logger.error(f"LLM Call Failed: {e}")
            return None

    def generate_purpose_statement(self, module_node: ModuleNode):
        """Generates purpose and detects documentation drift."""
        abs_path = os.path.join(self.repo_path, module_node.path)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                code_content = f.read()
        except FileNotFoundError:
            return

        # Simple truncation to avoid blowing context randomly on massive auto-generated files
        if len(code_content) > 100000:
            code_content = code_content[:100000] + "\n...[TRUNCATED]"

        prompt = f"""
        Analyze the following {module_node.language} file from a codebase:
        File Path: {module_node.path}
        
        Code:
        ```
        {code_content}
        ```
        
        Task:
        1. Write a strict 2-3 sentence 'purpose statement' explaining ONLY the business function of this code.
        2. Identify "Documentation Drift" between the implementation and any docstrings/comments.
        
        Output format exactly as JSON:
        {{
            "purpose_statement": "...",
            "drift_report": {{
                "detected": true/false,
                "severity": "none"|"low"|"high",
                "mismatch_details": "description of the discrepancy"
            }}
        }}
        """

        system = "You are an expert FDE. Extraction MUST be sharp and business-focused. You strictly return JSON."

        result = self._call_llm(prompt, system)
        if result:
            try:
                # Clean markdown JSON block if present
                clean_json = result.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(clean_json)
                module_node.purpose_statement = parsed.get(
                    "purpose_statement", "LLM Extraction Failed"
                )
                module_node.drift_report = parsed.get("drift_report")

                if module_node.drift_report and module_node.drift_report.get("detected"):
                    logger.info(f"Documentation Drift detected in {module_node.path}")
                    module_node.purpose_statement += (
                        f" [DRIFT: {module_node.drift_report.get('severity')}]"
                    )

            except json.JSONDecodeError:
                logger.error(f"Failed to parse LLM JSON output for {module_node.path}")
        else:
            module_node.purpose_statement = "LLM Extraction Offline (No API Key or Error)"

    def cluster_into_domains(self):
        """Clusters modules based on Semantic similarities in their Purpose Statements."""
        modules = [m for m in self.kg.graph.nodes.values() if m.get("type") == "module"]

        texts = []
        paths = []
        for m in modules:
            purpose = m.get("purpose_statement", "")
            if purpose and "LLM Extraction Offline" not in purpose:
                texts.append(purpose)
                paths.append(m.get("path"))

        if len(texts) < 3:
            logger.info("Not enough valid purpose statements to cluster into domains.")
            return

        k = min(5, len(texts))  # Between 1 and 5 clusters

        # We use a rapid local TF-IDF vectorization rather than blowing budget on embeddings
        # for a simple K-Means domain cluster. (Rubric allows Gemini embeddings or SKLearn)
        vectorizer = TfidfVectorizer(stop_words="english", max_features=1000)
        X = vectorizer.fit_transform(texts)

        kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto")
        kmeans.fit(X)

        for idx, label in enumerate(kmeans.labels_):
            # We map back the cluster label ID to the node
            node_id = paths[idx]
            # Since we modify the original node in Python object, we must push it back to the graph dict
            # Graph nodes hold the raw dictionary representing the Pydantic model
            if node_id in self.kg.graph:
                # Update the node dict directly
                self.kg.graph.nodes[node_id]["domain_cluster"] = f"Domain_{label}"

        logger.info(f"Clustered {len(texts)} modules into {k} domains.")

    def run_bulk_semantics(self, changed_files=None):
        """Iterates over modules and runs Purpose Extraction."""
        modules = [n for n, d in self.kg.graph.nodes(data=True) if d.get("type") == "module"]
        logger.info(f"Running bulk semantics on {len(modules)} modules...")

        count = 0
        for node_id in modules:
            node_data = self.kg.graph.nodes[node_id]
            node_path = node_data.get("path", "")

            # Skip LLM call if we have an incremental update and this file didn't change
            if changed_files is not None and node_path not in changed_files:
                if "purpose_statement" in node_data:
                    continue  # Keep existing purpose

            # Convert dictionary back to ModuleNode for type safety
            temp_node = ModuleNode(**node_data)
            self.generate_purpose_statement(temp_node)

            # Sync back
            self.kg.graph.nodes[node_id]["purpose_statement"] = temp_node.purpose_statement
            count += 1
            if count % 10 == 0:
                logger.info(f"Processed {count}/{len(modules)} modules...")

        self.cluster_into_domains()
        logger.info(f"Semantic Extraction Complete. Usage: {self.budget.summary()}")

    def answer_day_one_questions(self) -> str:
        """Synthesizes Day-One brief using full architectural context with Pro model and citations."""
        if not self.client:
            return "Cannot generate Day-One brief: LLM Offline."

        # 1. High Complexity hubs with line data
        hubs = sorted(
            [d for n, d in self.kg.graph.nodes(data=True) if d.get("type") == "module"],
            key=lambda x: x.get("complexity_score", 0),
            reverse=True,
        )[:10]

        # 2. Lineage nodes (Datasets & Transformations)
        lineage_nodes = [
            (n, d)
            for n, d in self.kg.graph.nodes(data=True)
            if d.get("type") in ["dataset", "transformation"]
        ]

        hubs_summary = "\n".join(
            [f"- {m['path']} (Purpose: {m.get('purpose_statement', 'N/A')})" for m in hubs]
        )

        # Detailed transformation evidence for citations
        trans_evidence = "\n".join(
            [
                f"- Transformation [{d.get('name')}]: Source {d.get('source_file')}:{d.get('line_range')} "
                f"(Reads: {d.get('source_datasets')}, Writes: {d.get('target_datasets')})"
                for n, d in lineage_nodes
                if d.get("type") == "transformation"
            ][:15]  # Truncate for context window safety
        )

        prompt = f"""
        You are Senior Forward Deployed Engineer analyzing a brownfield repository.
        I have run static analysis and data lineage extraction. Here is the architectural summary:
        
        TOP ARCHITECTURAL HUBS (Critical Path):
        {hubs_summary}
        
        DATA TRANSFORMATIONS & LINEAGE EVIDENCE:
        {trans_evidence}
        
        Using this context, please answer the 5 FDE Day-One Questions:
        1. What is the primary data ingestion path?
        2. What are the 3-5 most critical output datasets/endpoints?
        3. What is the blast radius if the most critical module fails?
        4. Where is the business logic concentrated vs. distributed?
        5. What has changed most frequently in the last 90 days? (Based on provided hubs)
        
        CRITICAL INSTRUCTIONS:
        - For every answer, you MUST include a "Technical Evidence" section.
        - The Technical Evidence MUST embed concrete file paths and line-range citations drawn from the provided summaries.
        - If the data is insufficient to fully answer, state "Insufficient static evidence" but provide your best professional hypothesis with citations.
        - Do not mention implantation details like variable names unless they are part of the dataset/transformation name.
        
        Format as a clean Markdown report using the Pro model's enhanced reasoning.
        """

        result = self._call_llm(
            prompt,
            "You construct authoritative Day-One Briefs with precise technical citations.",
            model=self.heavy_model_name,
        )
        return result or "Error synthesizing Day-One brief."
