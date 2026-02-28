"""
DocOps — FastAPI Backend

REST API that wraps the Gemini agent pipeline for the Next.js frontend.
"""

import json
import asyncio
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
PARSED_DIR = ROOT / "data" / "parsed"
PLANS_DIR = ROOT / "data" / "plans"
UPLOAD_DIR = ROOT / "data" / "uploads"

for d in (PARSED_DIR, PLANS_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="DocOps API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_docs() -> list[dict]:
    """Return metadata for all parsed markdown docs."""
    docs = []
    for md in sorted(PARSED_DIR.glob("*_parsed.md")):
        name = md.stem.replace("_parsed", "")
        size_kb = md.stat().st_size / 1024
        img_dir = PARSED_DIR / f"{name}_images"
        img_count = len(list(img_dir.glob("*.png"))) if img_dir.exists() else 0
        docs.append({
            "name": name,
            "filename": md.name,
            "size_kb": round(size_kb, 1),
            "image_count": img_count,
        })
    return docs


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    task: str


class ExecuteResult(BaseModel):
    search_results: list[dict]
    task_plan: Optional[dict] = None


# ---------------------------------------------------------------------------
# Routes — Knowledge Base
# ---------------------------------------------------------------------------

@app.get("/api/documents")
async def list_documents():
    """List all parsed documents in the knowledge base."""
    docs = _get_docs()
    total_images = sum(1 for _ in PARSED_DIR.glob("*_images/*.png"))
    total_size = sum(f.stat().st_size for f in PARSED_DIR.glob("*_parsed.md"))
    return {
        "documents": docs,
        "stats": {
            "count": len(docs),
            "total_images": total_images,
            "total_size_kb": round(total_size / 1024, 1),
        },
    }


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and parse a PDF document."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    stem = Path(file.filename).stem
    existing = PARSED_DIR / f"{stem}_parsed.md"
    if existing.exists():
        return {"status": "exists", "message": f"{file.filename} already in knowledge base"}

    upload_path = UPLOAD_DIR / file.filename
    content = await file.read()
    upload_path.write_bytes(content)

    try:
        from src.parser import DocumentParser
        parser = DocumentParser()
        doc = parser.parse(upload_path)
        doc.save_json(PARSED_DIR)
        doc.save_markdown(PARSED_DIR)
    except Exception as e:
        raise HTTPException(500, f"Failed to parse {file.filename}: {e}")

    return {"status": "ok", "message": f"{file.filename} parsed and added"}


@app.get("/api/documents/{doc_name}/images/{image_name}")
async def get_document_image(doc_name: str, image_name: str):
    """Serve an extracted image from a parsed document."""
    img_path = PARSED_DIR / f"{doc_name}_images" / image_name
    if not img_path.exists():
        # Try without _parsed suffix
        clean = doc_name.replace("_parsed", "")
        img_path = PARSED_DIR / f"{clean}_images" / image_name
    if not img_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(img_path, media_type="image/png")


# ---------------------------------------------------------------------------
# Routes — Pipeline Execution
# ---------------------------------------------------------------------------

@app.post("/api/execute")
async def execute_task(req: TaskRequest):
    """Run the full pipeline: search documents → generate task plan."""
    from src.agents import DocumentSearcher, TaskPlanner

    docs = sorted(PARSED_DIR.glob("*_parsed.md"))
    if not docs:
        raise HTTPException(400, "No documents in knowledge base. Upload PDFs first.")

    searcher = DocumentSearcher()
    results = []
    errors = []

    for md_file in docs:
        doc_name = md_file.stem.replace("_parsed", "")
        content = md_file.read_text(encoding="utf-8")
        try:
            result = searcher.search(req.task, content, doc_name)
            if result.get("relevant", False):
                results.append(result)
        except Exception as e:
            errors.append({"document": doc_name, "error": str(e)})

    if not results:
        return {
            "search_results": [],
            "task_plan": None,
            "errors": errors,
            "message": "No relevant information found in any document.",
        }

    planner = TaskPlanner()
    try:
        task_plan = planner.plan(req.task, results)
    except Exception as e:
        return {
            "search_results": results,
            "task_plan": None,
            "errors": [{"stage": "planning", "error": str(e)}],
        }

    return {
        "search_results": results,
        "task_plan": task_plan,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "documents": len(_get_docs())}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
