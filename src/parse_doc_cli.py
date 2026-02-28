"""
CLI wrapper for DocumentParser — outputs parsed document as JSON to stdout.
Used by the pi coding agent parse_document tool.

Usage:
    uv run python src/parse_doc_cli.py <file_path> [--format json|markdown]
"""

import json
import sys
from pathlib import Path

from src.parser import DocumentParser


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: parse_doc_cli.py <file_path> [--format json|markdown]"}))
        sys.exit(1)

    file_path = Path(sys.argv[1])
    fmt = "json"
    if "--format" in sys.argv:
        idx = sys.argv.index("--format")
        if idx + 1 < len(sys.argv):
            fmt = sys.argv[idx + 1]

    if not file_path.exists():
        print(json.dumps({"error": f"File not found: {file_path}"}))
        sys.exit(1)

    try:
        parser = DocumentParser()
        doc = parser.parse(file_path)

        if fmt == "markdown":
            print(doc.markdown)
        else:
            output = {
                "source": str(file_path),
                "tables_count": len(doc.tables),
                "markdown_chars": len(doc.markdown),
                "document": doc.to_dict,
            }
            print(json.dumps(output, indent=2, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
