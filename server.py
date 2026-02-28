"""
DocOps — FastAPI Backend

REST API that wraps the Gemini agent pipeline for the Next.js frontend.
"""

import json
import asyncio
import os
import time
import threading
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response
from pydantic import BaseModel

from src.camera import CameraCapture, CameraConfig

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


# Camera singleton — keeps the camera open for fast frame access
_camera_lock = threading.Lock()
_camera = None
_latest_frame: bytes | None = None  # cached latest JPEG for snapshot

CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "1"))


def _get_camera():
    global _camera
    if _camera is None:
        with _camera_lock:
            if _camera is None:
                cfg = CameraConfig(index=CAMERA_INDEX, width=640, height=480)
                _camera = CameraCapture(cfg)
                _camera.open()
    return _camera


def _capture_frame() -> bytes:
    """Thread-safe frame capture. Updates the cached latest frame."""
    global _latest_frame
    cam = _get_camera()
    with _camera_lock:
        jpeg = cam.capture_jpeg()
    _latest_frame = jpeg
    return jpeg


def _close_camera():
    global _camera
    if _camera is not None:
        with _camera_lock:
            if _camera is not None:
                _camera.close()
                _camera = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _close_camera()


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


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class RobotExecuteRequest(BaseModel):
    task_plan: dict
    feedback: Optional[str] = None


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


@app.get("/api/documents/{doc_name}")
async def get_document_content(doc_name: str):
    """Return the full parsed content and images list for a document."""
    md_path = PARSED_DIR / f"{doc_name}_parsed.md"
    if not md_path.exists():
        raise HTTPException(404, "Document not found")

    content = md_path.read_text(encoding="utf-8")
    img_dir = PARSED_DIR / f"{doc_name}_images"
    images = sorted([f.name for f in img_dir.glob("*.png")]) if img_dir.exists() else []

    return {
        "name": doc_name,
        "content": content,
        "images": images,
        "size_kb": round(md_path.stat().st_size / 1024, 1),
    }


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


@app.post("/api/execute/stream")
async def execute_task_stream(req: TaskRequest):
    """SSE endpoint: stream progress events while running the pipeline."""

    async def event_stream():
        import time
        from src.agents import DocumentSearcher, TaskPlanner

        def send(event: str, data: dict):
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        docs = sorted(PARSED_DIR.glob("*_parsed.md"))
        if not docs:
            yield send("error", {"message": "No documents in knowledge base."})
            return

        doc_names = [md.stem.replace("_parsed", "") for md in docs]
        yield send("stage", {
            "stage": "init",
            "message": f"Found {len(docs)} document(s) in knowledge base",
            "documents": doc_names,
        })
        await asyncio.sleep(0)

        # --- Search phase ---
        searcher = DocumentSearcher()
        results = []
        errors = []

        for i, md_file in enumerate(docs):
            doc_name = md_file.stem.replace("_parsed", "")
            yield send("stage", {
                "stage": "searching",
                "message": f"Searching: {doc_name}",
                "document": doc_name,
                "progress": i / len(docs),
            })
            await asyncio.sleep(0)

            content = md_file.read_text(encoding="utf-8")
            try:
                result = await asyncio.to_thread(
                    searcher.search, req.task, content, doc_name
                )
                relevant = result.get("relevant", False)
                yield send("search_result", {
                    "document": doc_name,
                    "relevant": relevant,
                    "task_understanding": result.get("task_understanding", ""),
                })
                if relevant:
                    results.append(result)
            except Exception as e:
                errors.append({"document": doc_name, "error": str(e)})
                yield send("search_error", {
                    "document": doc_name,
                    "error": str(e),
                })
            await asyncio.sleep(0)

        yield send("stage", {
            "stage": "search_complete",
            "message": f"Search complete — {len(results)} relevant document(s) found",
            "relevant_count": len(results),
            "total": len(docs),
        })
        await asyncio.sleep(0)

        if not results:
            yield send("done", {
                "search_results": [],
                "task_plan": None,
                "errors": errors,
                "message": "No relevant information found in any document.",
            })
            return

        # --- Planning phase ---
        yield send("stage", {
            "stage": "planning",
            "message": "Generating task execution plan…",
        })
        await asyncio.sleep(0)

        planner = TaskPlanner()
        try:
            task_plan = await asyncio.to_thread(planner.plan, req.task, results)
        except Exception as e:
            yield send("done", {
                "search_results": results,
                "task_plan": None,
                "errors": [{"stage": "planning", "error": str(e)}],
            })
            return

        yield send("stage", {
            "stage": "complete",
            "message": "Task plan generated successfully",
        })
        await asyncio.sleep(0)

        yield send("done", {
            "search_results": results,
            "task_plan": task_plan,
            "errors": errors,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------
# Routes — AI Chat Agent
# ---------------------------------------------------------------------------

CHAT_SYSTEM = """\
You are DocOps Assistant, an expert AI agent that answers questions about \
technical documents in the knowledge base. You have access to parsed datasheets, \
manuals, and SOPs.

When answering:
- Reference specific values, pin numbers, specs, and tolerances from the documents.
- If you cite a fact, mention which document it comes from.
- Be concise but thorough. Use bullet points for lists of specs.
- If the documents don't contain relevant information, say so honestly.
- You can explain concepts, compare specs, help with troubleshooting, and suggest \
  verification procedures based on the documentation.
- Format your response in Markdown for readability.
"""


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Answer a question about the knowledge base documents using Gemini."""
    from src.agents import _get_client, _call_gemini, DEFAULT_MODEL

    # Gather all document content
    docs = sorted(PARSED_DIR.glob("*_parsed.md"))
    if not docs:
        return {"reply": "No documents in the knowledge base yet. Upload some PDFs first!"}

    doc_context_parts = []
    for md_file in docs:
        doc_name = md_file.stem.replace("_parsed", "")
        content = md_file.read_text(encoding="utf-8")
        # Truncate very large docs to keep within context window
        if len(content) > 30000:
            content = content[:30000] + "\n\n[... document truncated ...]"
        doc_context_parts.append(f"=== Document: {doc_name} ===\n{content}")

    doc_context = "\n\n".join(doc_context_parts)

    # Build conversation prompt
    conversation = f"KNOWLEDGE BASE DOCUMENTS:\n\n{doc_context}\n\n---\n\nCONVERSATION:\n"
    for msg in req.history:
        role_label = "User" if msg.role == "user" else "Assistant"
        conversation += f"\n{role_label}: {msg.content}\n"
    conversation += f"\nUser: {req.message}\n\nAssistant:"

    client = _get_client()
    try:
        response = _call_gemini(
            client,
            DEFAULT_MODEL,
            conversation,
            CHAT_SYSTEM,
            temperature=0.3,
            max_output_tokens=4096,
        )
        reply = response.text.strip() if response.text else "I couldn't generate a response."
    except Exception as e:
        reply = f"Error: {e}"

    return {"reply": reply}


# ---------------------------------------------------------------------------
# Routes — Robot Execution
# ---------------------------------------------------------------------------

@app.post("/api/robot/execute")
async def robot_execute(req: RobotExecuteRequest):
    """Send a task plan to the SO-ARM100 robot for execution.

    In production this would communicate with the robot controller.
    For now it simulates accepting the plan, optionally applying user feedback,
    and returning a confirmation.
    """
    plan = req.task_plan
    steps = plan.get("task_plan", {}).get("steps", [])
    total = len(steps)

    # Save the plan for the robot controller to pick up
    plan_path = PLANS_DIR / "latest_plan.json"
    plan_path.write_text(json.dumps({
        "plan": plan,
        "feedback": req.feedback,
        "status": "queued",
    }, indent=2))

    return {
        "status": "queued",
        "message": f"Task plan with {total} step(s) queued for robot execution.",
        "steps": total,
        "feedback_applied": bool(req.feedback),
    }


@app.get("/api/robot/status")
async def robot_status():
    """Check the current robot execution status."""
    plan_path = PLANS_DIR / "latest_plan.json"
    if not plan_path.exists():
        return {"status": "idle", "message": "No task queued."}
    data = json.loads(plan_path.read_text())
    return {"status": data.get("status", "unknown"), "message": "Task plan loaded."}


# ---------------------------------------------------------------------------
# Routes — Camera
# ---------------------------------------------------------------------------

@app.get("/api/camera/frame")
async def camera_frame():
    """Return a single JPEG snapshot from the robot camera."""
    try:
        # Return the cached latest frame if available (from the stream),
        # otherwise capture a fresh one
        if _latest_frame is not None:
            return Response(content=_latest_frame, media_type="image/jpeg")
        loop = asyncio.get_event_loop()
        jpeg = await loop.run_in_executor(None, _capture_frame)
        return Response(content=jpeg, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(500, f"Camera error: {e}")


@app.get("/api/camera/stream")
async def camera_stream():
    """MJPEG stream from the robot camera for live feed."""
    async def generate():
        loop = asyncio.get_event_loop()
        while True:
            try:
                jpeg = await loop.run_in_executor(None, _capture_frame)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
                await asyncio.sleep(0.1)  # ~10 fps
            except Exception:
                break

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


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
