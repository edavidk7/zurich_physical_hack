# DocOps — Document-to-Execution Pipeline

> Documents don't just get read. They get run.

DocOps is an automated test & verification platform that parses factory documents (datasheets, SOPs, manuals) using **Docling**, finds relevant specifications via **Gemini AI**, and generates executable task plans for an **SO-ARM100** robotic arm.

Built at the Zurich Physical AI Hackathon by **Golden Grippers**.

<p align="center">
  <img src="data/images/logo.png" alt="Golden Grippers Logo" width="200" />
</p>


## Architecture

| Layer | Stack | Description |
|-------|-------|-------------|
| **Frontend** | Next.js · TypeScript · Tailwind CSS | Two-page UI — Task Execution & Knowledge Base |
| **Backend** | FastAPI · Python | REST API wrapping the agent pipeline |
| **Agents** | Gemini 2.5 Flash | DocumentSearcher + TaskPlanner |
| **Parsing** | Docling | PDF → structured markdown + image extraction |
| **Robot** | SO-ARM100 | 6-DOF arm with multimeter probe |

## Quick Start

```bash
# 1. Install uv (Python package manager)
irm https://astral.sh/uv/install.ps1 | iex   # Windows
# curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux/Mac

# 2. Install Python dependencies
uv sync

# 3. Set up environment
cp .env.example .env   # Add your GEMINI_API_KEY

# 4. Start the backend (port 8000)
uv run python server.py

# 5. Start the frontend (port 3000)
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to use the app.

## Project Structure

```
zurich_physical_hack/
├── server.py                  # FastAPI backend
├── src/
│   ├── agents.py              # Gemini agent layer (search + plan)
│   └── parser.py              # Docling document parser
├── frontend/                  # Next.js + TypeScript + Tailwind
│   └── src/
│       ├── app/page.tsx       # Main UI (Task + KB pages)
│       └── lib/
│           ├── api.ts         # API client
│           └── types.ts       # Shared TypeScript types
├── data/
│   ├── parsed/                # Parsed markdown + extracted images
│   ├── plans/                 # Generated task plans
│   └── uploads/               # Uploaded PDFs
├── pyproject.toml
└── PROPOSAL.md
```

## How It Works

1. **Upload** factory documents (PDFs) to the Knowledge Base
2. **Describe** a task in natural language (e.g. "Verify the 3.3V pin outputs correct voltage")
3. **DocOps** searches all documents for relevant specs, pins, and procedures
4. **Gemini** generates a step-by-step executable plan with pass/fail criteria
5. **SO-ARM100** executes the plan with a multimeter probe

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/documents` | List all parsed documents + stats |
| `POST` | `/api/documents/upload` | Upload & parse a PDF |
| `POST` | `/api/execute` | Run the full pipeline (search → plan) |
| `GET` | `/api/documents/{name}/images/{img}` | Serve extracted images |
