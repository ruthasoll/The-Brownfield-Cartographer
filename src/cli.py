import argparse
import os
import sys
import shutil
import subprocess
import logging
import tempfile
from src.agents.surveyor import SurveyorAgent
from src.agents.hydrologist import HydrologistAgent


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
        "--git-window", type=int, default=30, help="Days of git history to analyze"
    )
    analyze_parser.add_argument(
        "--dialect", default="postgres", help="SQL dialect for lineage analysis"
    )

    args = parser.parse_args()

    if args.command == "analyze":
        output_dir = os.path.abspath(args.output_dir)
        setup_logging(output_dir)
        logger = logging.getLogger("Orchestrator")

        repo_path = args.repo
        is_temp = False
        if repo_path.startswith(("http://", "https://", "git@")):
            repo_path = clone_repo(repo_path)
            is_temp = True
        else:
            repo_path = os.path.abspath(repo_path)

        logger.info(f"Starting orchestration for: {repo_path}")

        try:
            # 1. Surveyor Phase
            logger.info("Phase 1: Surveyor (Structure & Git)...")
            surveyor = SurveyorAgent(repo_path)
            surveyor.analyze_codebase()
            surveyor.extract_git_velocity(days=args.git_window)

            module_graph_path = os.path.join(output_dir, "module_graph.json")
            surveyor.save_graph(module_graph_path)
            logger.info(f"Surveyor complete. Found {len(surveyor.modules)} modules.")

            # 2. Hydrologist Phase
            logger.info("Phase 2: Hydrologist (Lineage)...")
            # Pass dialect if analyzer supported it (we updated SQLLineageAnalyzer to take it)
            hydrologist = HydrologistAgent(repo_path)
            hydrologist.sql_analyzer.dialect = args.dialect
            hydrologist.analyze_lineage()

            lineage_graph_path = os.path.join(output_dir, "lineage_graph.json")
            hydrologist.save_lineage(lineage_graph_path)
            logger.info(
                f"Hydrologist complete. Found {len(hydrologist.transformations)} transformations."
            )

            logger.info(f"Full analysis complete. Artifacts in {output_dir}")

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


if __name__ == "__main__":
    main()
