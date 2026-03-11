import argparse
import os
from src.agents.surveyor import SurveyorAgent
from src.agents.hydrologist import HydrologistAgent

def main():
    parser = argparse.ArgumentParser(description="The Brownfield Cartographer - Codebase Intelligence System")
    subparsers = parser.add_subparsers(dest="command")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a codebase and build knowledge graph")
    analyze_parser.add_argument("repo_path", help="Path to the repository to analyze")
    analyze_parser.add_argument("--output", default=".cartography/module_graph.json", help="Path to save the module graph")

    args = parser.parse_args()

    if args.command == "analyze":
        repo_path = os.path.abspath(args.repo_path)
        print(f"Starting analysis of: {repo_path}")
        
        surveyor = SurveyorAgent(repo_path)
        surveyor.analyze_codebase()
        surveyor.extract_git_velocity(days=90)
        
        surveyor.save_graph(args.output)
        print(f"Module graph saved to {args.output}")

        print("Starting data lineage analysis...")
        hydrologist = HydrologistAgent(repo_path)
        hydrologist.analyze_lineage()
        
        lineage_output = args.output.replace("module_graph.json", "lineage_graph.json")
        hydrologist.save_lineage(lineage_output)
        print(f"Lineage graph saved to {lineage_output}")
        print("Analysis complete.")

if __name__ == "__main__":
    main()
