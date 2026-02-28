"""
Golden Grippers — Interactive Agent Runner

Ask what you want to do in plain English. The system will:
  1. Search parsed documents for relevant info
  2. Generate a specific executable task plan

Examples:
  "Verify that the 3.3V pin outputs 3.3V"
  "Check if the 5V power rail is within spec"
  "Measure the voltage on analog pin A0"
  "Test continuity between VIN and the barrel jack"
"""

import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.agents import Pipeline


PARSED_DIR = Path(__file__).parent / "data" / "parsed"
OUTPUT_DIR = Path(__file__).parent / "data" / "plans"


def main():
    print("=" * 60)
    print("Golden Grippers — What do you want to test?")
    print("=" * 60)

    # Check for parsed documents
    md_files = sorted(PARSED_DIR.glob("*_parsed.md"))
    if not md_files:
        print(f"\nNo parsed documents found in {PARSED_DIR}")
        print("Run parse_documents.py first to parse PDFs.")
        return

    print(f"\nAvailable documents:")
    for f in md_files:
        print(f"  - {f.stem.replace('_parsed', '')}")

    # Get task from command line or interactive input
    if len(sys.argv) > 1:
        user_task = " ".join(sys.argv[1:])
    else:
        print(f"\nDescribe your task (or 'quit' to exit):")
        user_task = input("> ").strip()

    if not user_task or user_task.lower() in ("quit", "exit", "q"):
        return

    pipeline = Pipeline(docs_dir=PARSED_DIR)

    try:
        result = pipeline.run(user_task, save_dir=OUTPUT_DIR)
        if result["task_plan"]:
            print(f"\n{'='*60}")
            print("Done! Task plan saved to data/plans/task_plan.json")
            print(f"{'='*60}")
        else:
            print("\nCould not generate a plan — no relevant docs found.")
    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    main()
