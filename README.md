# Golden Grippers — Document-to-Execution Pipeline

## Setup

```bash
# Install uv if not already installed
irm https://astral.sh/uv/install.ps1 | iex   # Windows
# curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux/Mac

# Install dependencies
uv sync

# Test Docling parsing
uv run python test_docling.py
```

## Project Structure

```
zurich_physical_hack/
├── src/
│   └── golden_grippers/
│       ├── __init__.py
│       ├── parser.py          # Docling document parser
│       ├── agents/            # DeepMind agent layer
│       ├── task_plan.py       # Task plan schema & compiler
│       └── arm_control.py     # SO-ARM100 interface
├── data/
│   ├── sample_docs/           # Input factory documents
│   └── parsed/                # Docling parsed output
├── models/                    # Local HuggingFace models (gitignored)
├── test_docling.py            # Quick parsing test
├── pyproject.toml
└── PROPOSAL.md
```
