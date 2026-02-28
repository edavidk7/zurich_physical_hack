"""
Golden Grippers — Docling Document Parser
Test script: parse Arduino datasheets and export structured JSON.
"""

from pathlib import Path
from src.golden_grippers.parser import DocumentParser


DATA_DIR = Path(__file__).parent / "data" / "arduino"
OUTPUT_DIR = Path(__file__).parent / "data" / "parsed"


def main():
    print("=" * 60)
    print("Golden Grippers — Docling Parsing Test")
    print("=" * 60)

    parser = DocumentParser()

    # Find all documents
    files = list(DATA_DIR.glob("*.pdf"))
    if not files:
        print(f"No PDFs found in {DATA_DIR}")
        return

    print(f"\nFound {len(files)} document(s):\n")
    for f in files:
        print(f"  - {f.name}")

    # Parse each document
    for file_path in files:
        print(f"\n{'=' * 60}")
        print(f"PARSING: {file_path.name}")
        print(f"{'=' * 60}")

        try:
            doc = parser.parse(file_path)
            print(doc)

            # Save as JSON (primary output)
            json_path = doc.save_json(OUTPUT_DIR)
            print(f"  JSON saved to: {json_path}")

            # Save as markdown (for human review)
            md_path = doc.save_markdown(OUTPUT_DIR)
            print(f"  Markdown saved to: {md_path}")

            # Show tables summary
            tables = doc.table_dataframes
            if tables:
                print(f"\n  Found {len(tables)} table(s):")
                for i, df in enumerate(tables):
                    print(f"    Table {i}: {len(df)} rows x {len(df.columns)} cols — {list(df.columns)}")
            else:
                print("\n  No tables found")

        except Exception as e:
            print(f"\nERROR parsing {file_path.name}: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
