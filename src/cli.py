import argparse
import os
import sys
import shutil
import subprocess
import logging
import tempfile


def setup_logging(output_dir: str):
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "pipeline.log")),
            logging.StreamHandler(sys.stdout),
        ],
    )


def clone_repo(url: str) -> str:
    """Clones a remote repository to a temporary directory."""
    temp_dir = tempfile.mkdtemp(prefix="cartography_")
    print(f"Cloning {url} to {temp_dir}...")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, temp_dir], check=True, capture_output=True
        )
        return temp_dir
    except subprocess.CalledProcessError as e:
        print(f"Failed to clone repository: {e.stderr.decode()}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="The Brownfield Cartographer - Master Pipeline")
    subparsers = parser.add_subparsers(dest="command")

    # Analyze command
    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze a codebase and build knowledge graph"
    )
    analyze_parser.add_argument("repo", help="Path or GitHub URL to the repository")
    analyze_parser.add_argument(
        "--output-dir", default=".cartography", help="Directory for analysis artifacts"
    )
    analyze_parser.add_argument(
        "--no-llm", action="store_true", help="Force static analysis only, skipping LLM calls"
    )

    # Query command
    query_parser = subparsers.add_parser(
        "query", help="Interactive LangGraph Navigator for architecture/lineage questions"
    )
    query_parser.add_argument(
        "--graph-dir",
        default=".cartography",
        help="Directory containing the serialized knowledge graph",
    )

    args = parser.parse_args()

    if args.command == "analyze":
        output_dir = os.path.abspath(args.output_dir)
        setup_logging(output_dir)
        logger = logging.getLogger("CLI")

        repo_path = args.repo
        is_temp = False
        if repo_path.startswith(("http://", "https://", "git@")):
            repo_path = clone_repo(repo_path)
            is_temp = True
        else:
            repo_path = os.path.abspath(repo_path)

        logger.info(f"Starting orchestration for: {repo_path}")

        try:
            from src.orchestrator import CartographyOrchestrator

            orchestrator = CartographyOrchestrator(repo_path, output_dir, no_llm=args.no_llm)
            orchestrator.run_pipeline()

        except Exception as e:
            import traceback

            with open("error_log.txt", "w") as f:
                f.write(traceback.format_exc())
            logger.error(f"Fatal orchestrator failure: {e}", exc_info=True)
            sys.exit(1)
        finally:
            if is_temp and os.path.exists(repo_path):
                logger.info(f"Cleaning up temporary clone: {repo_path}")
                import stat

                def remove_readonly(func, path, excinfo):
                    os.chmod(path, stat.S_IWRITE)
                    func(path)

                shutil.rmtree(repo_path, onerror=remove_readonly)

    elif args.command == "query":
        from src.graph.knowledge_graph import KnowledgeGraph
        from src.agents.navigator import NavigatorAgent

        kg_path = os.path.join(args.graph_dir, "lineage_graph.json")
        if not os.path.exists(kg_path):
            print(f"Error: Knowledge graph not found at {kg_path}. Run 'analyze' first.")
            sys.exit(1)

        kg = KnowledgeGraph()
        kg.deserialize(kg_path)

        # Instantiate archivist for logging query sessions
        from src.agents.archivist import ArchivistAgent

        archivist = ArchivistAgent(kg, args.graph_dir)

        navigator = NavigatorAgent(kg, archivist=archivist)
        navigator.interactive_shell()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
