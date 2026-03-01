"""
DocOps — FastAPI Backend

REST API that wraps the Gemini agent pipeline for the Next.js frontend.
"""

import collections
import io
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
from src.high_level_planner import (
    extract_keypoints,
    annotate_image_pil,
    annotated_image_to_base64,
    load_and_prep_image,
)
from src.constants import CAMERA_WIDTH, CAMERA_HEIGHT
from src.motor_control import get_motor_controller, find_robot_port

# Try placo-based solver; fall back to pure-Python kinematics on Windows
_HAS_PLACO = True
try:
    from src.ik_solver import SO101IKSolver
except Exception:
    _HAS_PLACO = False

from src.kinematics import SOArmKinematics

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

# Rolling FPS tracker (last 60 frame timestamps)
_frame_times: collections.deque = collections.deque(maxlen=60)

CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "1"))


def _get_camera():
    global _camera
    if _camera is None:
        with _camera_lock:
            if _camera is None:
                cfg = CameraConfig(
                    index=CAMERA_INDEX, width=CAMERA_WIDTH, height=CAMERA_HEIGHT
                )
                _camera = CameraCapture(cfg)
                _camera.open()
    return _camera


def _capture_frame() -> bytes:
    """Thread-safe frame capture. Updates the cached latest frame and FPS counter."""
    global _latest_frame
    cam = _get_camera()
    with _camera_lock:
        jpeg = cam.capture_jpeg()
    _latest_frame = jpeg
    _frame_times.append(time.monotonic())
    return jpeg


def _resize_jpeg(jpeg: bytes, width: int, height: int) -> bytes:
    """Decode a JPEG, resize, and re-encode at lower quality for thumbnails."""
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    img = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


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
    # Disconnect robot if connected
    try:
        ctrl = get_motor_controller()
        if ctrl.is_connected:
            ctrl.disconnect()
    except Exception:
        pass


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
        docs.append(
            {
                "name": name,
                "filename": md.name,
                "size_kb": round(size_kb, 1),
                "image_count": img_count,
            }
        )
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
        return {
            "status": "exists",
            "message": f"{file.filename} already in knowledge base",
        }

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
        yield send(
            "stage",
            {
                "stage": "init",
                "message": f"Found {len(docs)} document(s) in knowledge base",
                "documents": doc_names,
            },
        )
        await asyncio.sleep(0)

        # --- Search phase ---
        searcher = DocumentSearcher()
        results = []
        errors = []

        for i, md_file in enumerate(docs):
            doc_name = md_file.stem.replace("_parsed", "")
            yield send(
                "stage",
                {
                    "stage": "searching",
                    "message": f"Searching: {doc_name}",
                    "document": doc_name,
                    "progress": i / len(docs),
                },
            )
            await asyncio.sleep(0)

            content = md_file.read_text(encoding="utf-8")
            try:
                result = await asyncio.to_thread(
                    searcher.search, req.task, content, doc_name
                )
                relevant = result.get("relevant", False)
                yield send(
                    "search_result",
                    {
                        "document": doc_name,
                        "relevant": relevant,
                        "task_understanding": result.get("task_understanding", ""),
                    },
                )
                if relevant:
                    results.append(result)
            except Exception as e:
                errors.append({"document": doc_name, "error": str(e)})
                yield send(
                    "search_error",
                    {
                        "document": doc_name,
                        "error": str(e),
                    },
                )
            await asyncio.sleep(0)

        yield send(
            "stage",
            {
                "stage": "search_complete",
                "message": f"Search complete — {len(results)} relevant document(s) found",
                "relevant_count": len(results),
                "total": len(docs),
            },
        )
        await asyncio.sleep(0)

        if not results:
            yield send(
                "done",
                {
                    "search_results": [],
                    "task_plan": None,
                    "errors": errors,
                    "message": "No relevant information found in any document.",
                },
            )
            return

        # --- Planning phase ---
        yield send(
            "stage",
            {
                "stage": "planning",
                "message": "Generating task execution plan…",
            },
        )
        await asyncio.sleep(0)

        planner = TaskPlanner()
        try:
            task_plan = await asyncio.to_thread(planner.plan, req.task, results)
        except Exception as e:
            yield send(
                "done",
                {
                    "search_results": results,
                    "task_plan": None,
                    "errors": [{"stage": "planning", "error": str(e)}],
                },
            )
            return

        yield send(
            "stage",
            {
                "stage": "complete",
                "message": "Task plan generated successfully",
            },
        )
        await asyncio.sleep(0)

        yield send(
            "done",
            {
                "search_results": results,
                "task_plan": task_plan,
                "errors": errors,
            },
        )

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
        return {
            "reply": "No documents in the knowledge base yet. Upload some PDFs first!"
        }

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
    conversation = (
        f"KNOWLEDGE BASE DOCUMENTS:\n\n{doc_context}\n\n---\n\nCONVERSATION:\n"
    )
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
        reply = (
            response.text.strip()
            if response.text
            else "I couldn't generate a response."
        )
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
    plan_path.write_text(
        json.dumps(
            {
                "plan": plan,
                "feedback": req.feedback,
                "status": "queued",
            },
            indent=2,
        )
    )

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
# Routes — Kinematics (FK / IK)
# ---------------------------------------------------------------------------

_ik_solver: "SO101IKSolver | None" = None
_ik_solver_lock = threading.Lock()
_pure_kin: SOArmKinematics | None = None


def get_ik_solver():
    """Return placo-based solver or None if unavailable."""
    global _ik_solver
    if not _HAS_PLACO:
        return None
    with _ik_solver_lock:
        if _ik_solver is None:
            _ik_solver = SO101IKSolver()
        return _ik_solver


def get_pure_kin() -> SOArmKinematics:
    """Return the pure-Python FK/IK engine (always available)."""
    global _pure_kin
    if _pure_kin is None:
        _pure_kin = SOArmKinematics()
    return _pure_kin


def get_kinematics() -> SOArmKinematics:
    """Alias used by FK/IK endpoints — always available."""
    return get_pure_kin()


_JOINT_LIMITS_DEG = {
    "shoulder_pan":  (-91.7,  91.7),
    "shoulder_lift": (-90.0,  90.0),
    "elbow_flex":    (-91.7,  80.2),
    "wrist_flex":    (-95.7,  95.7),
    "wrist_roll":    (-180.0, 180.0),
    "gripper":       (-12.0,  85.9),
}


_MOTOR_NAMES_ORDER = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]


class FKRequest(BaseModel):
    joints_deg: list[
        float
    ]  # 6 values: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper


class IKRequest(BaseModel):
    x: float
    y: float
    z: float
    roll: Optional[float] = None  # degrees, optional
    pitch: Optional[float] = None
    yaw: Optional[float] = None
    init_joints_deg: Optional[list[float]] = None  # 6 values, optional initial guess
    gripper_deg: float = 0.0


@app.post("/api/kinematics/fk")
async def forward_kinematics(req: FKRequest):
    """Compute end-effector pose from joint angles (degrees)."""
    import numpy as np

    kin = get_kinematics()
    q_mech_rad = np.deg2rad(req.joints_deg)
    ee = kin.get_ee_position(q_mech_rad)

    q_deg = {name: float(deg) for name, deg in zip(_MOTOR_NAMES_ORDER, req.joints_deg)}
    violations = [
        name
        for name, deg in q_deg.items()
        if deg < _JOINT_LIMITS_DEG[name][0] or deg > _JOINT_LIMITS_DEG[name][1]
    ]
    print(
        f"[FK] EE pos = ({ee['x'] * 1000:.1f}, {ee['y'] * 1000:.1f}, {ee['z'] * 1000:.1f}) mm  "
        f"RPY = ({ee['roll']:.1f}°, {ee['pitch']:.1f}°, {ee['yaw']:.1f}°)"
        + (f"  violations={violations}" if violations else "")
    )
    return {
        "ee_position": {
            "x": ee["x"],
            "y": ee["y"],
            "z": ee["z"],
            "roll_deg": ee["roll"],
            "pitch_deg": ee["pitch"],
            "yaw_deg": ee["yaw"],
        },
        "joint_violations": violations,
    }


@app.post("/api/kinematics/ik")
async def inverse_kinematics(req: IKRequest):
    """Compute joint angles to reach a target end-effector position."""
    import numpy as np

    kin = get_kinematics()

    # Build initial guess (mechanical angles in radians)
    mc = get_motor_controller()
    if mc.is_connected:
        live = mc.read_positions().get("positions_deg", {})
        q_init_deg = [float(live.get(n, 0.0)) for n in _MOTOR_NAMES_ORDER]
    elif req.init_joints_deg and len(req.init_joints_deg) == 6:
        q_init_deg = [float(d) for d in req.init_joints_deg]
    else:
        q_init_deg = [0.0] * 6
    q_init_deg[5] = req.gripper_deg
    q_init_rad = np.deg2rad(q_init_deg)

    # Optional orientation target
    target_rpy_deg = None
    use_orientation = False
    if req.roll is not None and req.pitch is not None and req.yaw is not None:
        target_rpy_deg = (req.roll, req.pitch, req.yaw)
        use_orientation = True

    result = kin.inverse_kinematics(
        target_xyz=(req.x, req.y, req.z),
        target_rpy_deg=target_rpy_deg,
        q_init_mech=q_init_rad,
        gripper=np.deg2rad(req.gripper_deg),
        use_orientation=use_orientation,
    )

    joints_deg_list = result["joints_deg"]
    ee = result["ee_position"]
    error_mm = result["error_mm"]

    q_deg_dict = {name: deg for name, deg in zip(_MOTOR_NAMES_ORDER, joints_deg_list)}
    violations = [
        name
        for name, deg in q_deg_dict.items()
        if deg < _JOINT_LIMITS_DEG[name][0] or deg > _JOINT_LIMITS_DEG[name][1]
    ]

    print(
        f"[IK] target=({req.x * 1000:.1f}, {req.y * 1000:.1f}, {req.z * 1000:.1f}) mm  "
        f"achieved=({ee['x'] * 1000:.1f}, {ee['y'] * 1000:.1f}, {ee['z'] * 1000:.1f}) mm  "
        f"error={error_mm:.2f} mm  success={result['success']}"
    )
    print(
        "[IK] joints = " + "  ".join(f"{n[:4]}={v:.1f}°" for n, v in q_deg_dict.items())
    )
    if violations:
        print(f"[IK] LIMIT VIOLATIONS: {violations}")
    return {
        "joints_deg": q_deg_dict,
        "joints_list": joints_deg_list,
        "ee_position": {
            "x": ee["x"],
            "y": ee["y"],
            "z": ee["z"],
            "roll_deg": ee["roll"],
            "pitch_deg": ee["pitch"],
            "yaw_deg": ee["yaw"],
        },
        "error_mm": error_mm,
        "success": result["success"],
        "joint_violations": violations,
    }


@app.get("/api/kinematics/home")
async def kinematics_home():
    """Return the home pose joint angles and corresponding EE position."""
    import numpy as np

    kin = get_kinematics()
    q_home_deg = {n: 0.0 for n in _MOTOR_NAMES_ORDER}
    q_home_rad = np.zeros(6)
    ee = kin.get_ee_position(q_home_rad)
    return {
        "joints_deg": q_home_deg,
        "joint_names": _MOTOR_NAMES_ORDER,
        "ee_position": {
            "x": ee["x"],
            "y": ee["y"],
            "z": ee["z"],
        },
    }


# ---------------------------------------------------------------------------
# Routes — Motor Control (direct servo control)
# ---------------------------------------------------------------------------


class MotorConnectRequest(BaseModel):
    port: Optional[str] = None  # auto-detect if None


class MotorWriteRequest(BaseModel):
    joints_deg: list[float]  # 6 values: shoulder_pan → gripper
    speed: Optional[int] = None  # 0-1000 (0=slowest, 100=moderate, 1000=max)


class MotorSpeedRequest(BaseModel):
    speed: int  # 0-1000


@app.post("/api/motor/connect")
async def motor_connect(req: MotorConnectRequest):
    """Connect to the SO-ARM100 robot on the given serial port."""
    port = req.port
    if not port:
        port = find_robot_port()
        if not port:
            raise HTTPException(
                400, "No robot serial port detected. Specify port manually."
            )
    ctrl = get_motor_controller()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, ctrl.connect, port)
    if result.get("status") == "error":
        raise HTTPException(500, result.get("error", "Connection failed"))
    return result


@app.post("/api/motor/disconnect")
async def motor_disconnect():
    """Disconnect from the robot, disabling torque."""
    ctrl = get_motor_controller()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, ctrl.disconnect)
    return result


@app.get("/api/motor/status")
async def motor_status():
    """Get the current motor connection and position status."""
    ctrl = get_motor_controller()
    if not ctrl.is_connected:
        return {"connected": False, "port": None, "positions_deg": None}
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, ctrl.read_positions)
    return {
        "connected": True,
        "port": ctrl._port,
        "positions_deg": result.get("positions_deg"),
        "positions_list": result.get("positions_list"),
        "error": result.get("error"),
    }


@app.get("/api/motor/positions")
async def motor_read_positions():
    """Read current joint positions from the robot."""
    ctrl = get_motor_controller()
    if not ctrl.is_connected:
        raise HTTPException(400, "Robot not connected. Call /api/motor/connect first.")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, ctrl.read_positions)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


@app.post("/api/motor/move")
async def motor_write_positions(req: MotorWriteRequest):
    """Send goal positions to the robot motors.

    Accepts 6 joint angles in degrees: shoulder_pan, shoulder_lift,
    elbow_flex, wrist_flex, wrist_roll, gripper.
    Optionally set speed (0-1000).
    """
    ctrl = get_motor_controller()
    if not ctrl.is_connected:
        raise HTTPException(400, "Robot not connected. Call /api/motor/connect first.")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, ctrl.write_joint_array, req.joints_deg, req.speed
    )
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


@app.post("/api/motor/torque/enable")
async def motor_enable_torque():
    """Enable torque on all motors."""
    ctrl = get_motor_controller()
    if not ctrl.is_connected:
        raise HTTPException(400, "Robot not connected.")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, ctrl.enable_torque)
    return result


@app.post("/api/motor/speed")
async def motor_set_speed(req: MotorSpeedRequest):
    """Set the movement speed (0=slowest, 100=moderate, 1000=max)."""
    ctrl = get_motor_controller()
    if not ctrl.is_connected:
        raise HTTPException(400, "Robot not connected.")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, ctrl.set_speed, req.speed)
    return result


@app.post("/api/motor/torque/disable")
async def motor_disable_torque():
    """Disable torque — arm goes limp."""
    ctrl = get_motor_controller()
    if not ctrl.is_connected:
        raise HTTPException(400, "Robot not connected.")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, ctrl.disable_torque)
    return result


@app.get("/api/motor/detect-port")
async def motor_detect_port():
    """Auto-detect the robot serial port."""
    port = find_robot_port()
    return {"port": port, "detected": port is not None}


# ---------------------------------------------------------------------------
# Routes — Camera
# ---------------------------------------------------------------------------


@app.get("/api/camera/frame")
async def camera_frame():
    """Return a single JPEG snapshot from the robot camera (always fresh)."""
    try:
        loop = asyncio.get_event_loop()
        jpeg = await loop.run_in_executor(None, _capture_frame)
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    except Exception as e:
        raise HTTPException(500, f"Camera error: {e}")


@app.get("/api/camera/stream")
async def camera_stream(w: int = 0, h: int = 0):
    """MJPEG stream from the robot camera for live feed.

    Optional query params:
      w, h – downscale each frame to this resolution before streaming
              (useful for thumbnail previews).  Omit for full resolution.
    """

    async def generate():
        loop = asyncio.get_event_loop()
        while True:
            try:
                jpeg = await loop.run_in_executor(None, _capture_frame)
                if w > 0 and h > 0:
                    jpeg = await loop.run_in_executor(None, _resize_jpeg, jpeg, w, h)
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                # Yield control so the event loop stays responsive;
                # actual frame rate is limited by camera capture time.
                await asyncio.sleep(0)
            except Exception:
                break

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/camera/fps")
async def camera_fps():
    """Return the rolling capture FPS (last 60 frames)."""
    n = len(_frame_times)
    if n < 2:
        return {"fps": 0.0}
    elapsed = _frame_times[-1] - _frame_times[0]
    fps = (n - 1) / elapsed if elapsed > 0 else 0.0
    return {"fps": round(fps, 1)}


@app.get("/api/camera/tooltip_projection")
async def tooltip_projection():
    """
    Project the tool tip into the camera image plane.

    Uses the fixed camera-in-EE transform (T_CAM_EE) from robot_cam_calibration
    and the camera intrinsics K from calibration.json to map the tool tip
    (TOOL_OFFSET_EE_M in the Fixed_Jaw frame) to a normalized image coordinate.

    The tip position in the camera frame is constant because both the camera and
    the tool are rigidly attached to the EE — only the workspace view changes,
    not where the tip appears in the image.

    Returns {u_norm, v_norm, visible} where u_norm/v_norm ∈ [0,1].
    """
    import numpy as np
    from src.localize_from_checkerboard import load_calibration, _CALIB_PATH
    from src.constants import CAMERA_WIDTH, CAMERA_HEIGHT, P_TIP_CAM_M

    if not _CALIB_PATH.exists():
        return {
            "visible": False,
            "u_norm": 0.5,
            "v_norm": 0.5,
            "error": "calibration.json not found",
        }

    K, _, _, _ = load_calibration()

    # Tool tip in EE (Fixed_Jaw) frame → camera frame
    x_c, y_c, z_c = list(P_TIP_CAM_M)

    if z_c <= 0:
        return {"visible": False, "u_norm": 0.5, "v_norm": 0.5}

    u = K[0, 0] * x_c / z_c + K[0, 2]
    v = K[1, 1] * y_c / z_c + K[1, 2]
    u_norm = float(u) / CAMERA_WIDTH
    v_norm = float(v) / CAMERA_HEIGHT
    visible = bool(0.0 <= u_norm <= 1.0 and 0.0 <= v_norm <= 1.0)

    print(
        f"[tooltip_projection] tip_cam=({x_c * 1000:.1f}, {y_c * 1000:.1f}, {z_c * 1000:.1f}) mm  "
        f"px=({u:.1f}, {v:.1f})  norm=({u_norm:.3f}, {v_norm:.3f})  visible={visible}"
    )
    return {"visible": visible, "u_norm": u_norm, "v_norm": v_norm}


# ---------------------------------------------------------------------------
# Routes — Keypoint localisation
# ---------------------------------------------------------------------------


class ReferenceImage(BaseModel):
    doc_name: str
    image_name: str


class KeypointRequest(BaseModel):
    prompt: str
    reference_images: list[ReferenceImage] = []
    model: str = "gemini-3-flash-preview"
    thinking_budget: int = 0
    thinking_level: Optional[str] = None  # "minimal", "low", "medium", "high"
    temperature: float = 1.0


class StepKeypointRequest(BaseModel):
    step: dict
    reference_images: list[ReferenceImage] = []
    model: str = "gemini-3-flash-preview"
    thinking_budget: int = 0
    thinking_level: Optional[str] = None  # "minimal", "low", "medium", "high"
    temperature: float = 1.0


def _prompt_from_step(step: dict) -> str:
    """Auto-generate a keypoint localisation prompt from a task plan step.

    The SO-101 robot only manipulates the positive (+) multimeter probe.
    The negative probe is clipped to a fixed point and never moved, so we
    only need to localise the positive probe's target and the current tip.
    """
    params = step.get("parameters") or {}
    probe_pos = params.get("probe_positive", "")
    if probe_pos and isinstance(probe_pos, str):
        return (
            f"Locate {probe_pos} on the board, "
            "and the current tip position of the robot's positive multimeter probe"
        )
    target = step.get("target") or step.get("description") or "the target component"
    return f"Locate {target} on the board and the current tip position of the robot's positive multimeter probe"


@app.post("/api/execute/step-keypoints")
async def step_keypoints(req: StepKeypointRequest):
    """
    For a single plan step: capture camera, run VLM keypoint localisation,
    return annotated image + keypoints.  Prompt is auto-generated from the step.
    """
    from PIL import Image
    import io

    prompt = _prompt_from_step(req.step)

    ref_pil: list[Image.Image] = []
    for ri in req.reference_images:
        clean = ri.doc_name.replace("_parsed", "")
        img_path = PARSED_DIR / f"{clean}_images" / ri.image_name
        if not img_path.exists():
            img_path = PARSED_DIR / f"{ri.doc_name}_images" / ri.image_name
        if not img_path.exists():
            raise HTTPException(
                404, f"Reference image not found: {ri.doc_name}/{ri.image_name}"
            )
        ref_pil.append(load_and_prep_image(img_path))

    try:
        cam = _get_camera()
        loop = asyncio.get_event_loop()
        jpeg_bytes = await loop.run_in_executor(None, cam.capture_jpeg)
        camera_pil = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(500, f"Camera error: {e}")

    try:
        keypoints = await asyncio.to_thread(
            extract_keypoints,
            ref_pil,
            camera_pil,
            prompt,
            req.model,
            req.thinking_budget,
            req.thinking_level,
            req.temperature,
        )
    except Exception as e:
        raise HTTPException(500, f"VLM error: {e}")

    annotated = annotate_image_pil(camera_pil, keypoints)
    img_b64 = annotated_image_to_base64(annotated)

    return {
        "annotated_image": img_b64,
        "keypoints": keypoints,
        "prompt": prompt,
        "camera_size": list(camera_pil.size),
    }


@app.post("/api/keypoints")
async def locate_keypoints(req: KeypointRequest):
    """
    Capture a live camera frame, run VLM keypoint localisation using the
    provided reference images, and return the annotated camera image + keypoints.
    """
    from PIL import Image
    import io

    ref_pil: list[Image.Image] = []
    for ri in req.reference_images:
        clean = ri.doc_name.replace("_parsed", "")
        img_path = PARSED_DIR / f"{clean}_images" / ri.image_name
        if not img_path.exists():
            img_path = PARSED_DIR / f"{ri.doc_name}_images" / ri.image_name
        if not img_path.exists():
            raise HTTPException(
                404, f"Reference image not found: {ri.doc_name}/{ri.image_name}"
            )
        ref_pil.append(load_and_prep_image(img_path))

    try:
        cam = _get_camera()
        loop = asyncio.get_event_loop()
        jpeg_bytes = await loop.run_in_executor(None, cam.capture_jpeg)
        camera_pil = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(500, f"Camera error: {e}")

    try:
        keypoints = await asyncio.to_thread(
            extract_keypoints,
            ref_pil,
            camera_pil,
            req.prompt,
            req.model,
            req.thinking_budget,
            req.thinking_level,
            req.temperature,
        )
    except Exception as e:
        raise HTTPException(500, f"VLM error: {e}")

    annotated = annotate_image_pil(camera_pil, keypoints)
    img_b64 = annotated_image_to_base64(annotated)

    return {
        "annotated_image": img_b64,
        "keypoints": keypoints,
        "prompt": req.prompt,
        "camera_size": list(camera_pil.size),
    }


# ---------------------------------------------------------------------------
# Routes — Move to keypoint (simple open-loop)
# ---------------------------------------------------------------------------


class MoveToKeypointRequest(BaseModel):
    norm_y: float  # keypoint Y in [0, 1000] normalized coords
    norm_x: float  # keypoint X in [0, 1000] normalized coords
    calib: str = "data/arm_cam_calib/calibration.json"
    dry_run: bool = False


@app.post("/api/robot/move-to-keypoint")
async def move_to_keypoint(req: MoveToKeypointRequest):
    """
    Capture a camera frame, estimate pose via checkerboard, compute the
    lateral movement needed to center on the given keypoint, and execute
    the cartesian move on the robot.

    This is a simple open-loop version: one shot, no VLM re-checking.
    """
    import io
    import cv2
    import numpy as np
    from PIL import Image
    from src.pose_estimation import estimate_camera_pose, compute_movement_to_keypoint

    print(f"[move-to-kp] request: norm_y={req.norm_y:.1f}, norm_x={req.norm_x:.1f}, dry_run={req.dry_run}")

    # 1. Capture frame
    try:
        cam = _get_camera()
        loop = asyncio.get_event_loop()
        jpeg_bytes = await loop.run_in_executor(None, cam.capture_jpeg)
        camera_pil = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
        bgr = cv2.cvtColor(np.array(camera_pil), cv2.COLOR_RGB2BGR)
    except Exception as e:
        print(f"[move-to-kp] camera error: {e}")
        raise HTTPException(500, f"Camera error: {e}")

    img_h, img_w = bgr.shape[:2]
    print(f"[move-to-kp] captured frame {img_w}x{img_h}")

    # 2. Estimate camera pose from checkerboard
    try:
        success, rvec, tvec, K, D = await asyncio.to_thread(
            estimate_camera_pose, bgr, req.calib
        )
    except Exception as e:
        print(f"[move-to-kp] pose estimation error: {e}")
        raise HTTPException(500, f"Pose estimation error: {e}")

    if not success:
        print("[move-to-kp] checkerboard NOT detected")
        raise HTTPException(
            422, "Checkerboard not detected in frame — cannot estimate pose."
        )

    cam_height_mm = float(tvec.flatten()[2])
    print(
        f"[move-to-kp] pose OK — rvec={rvec.flatten().round(3).tolist()}, "
        f"tvec={tvec.flatten().round(1).tolist()} mm, cam_height={cam_height_mm:.1f} mm"
    )

    # 3. Compute lateral movement delta (camera frame, mm)
    delta_cam = await asyncio.to_thread(
        compute_movement_to_keypoint,
        req.norm_y, req.norm_x,
        rvec, tvec, K, D,
        img_w, img_h,
    )

    # Camera→robot frame mapping (straight-down mount)
    dx_cam_mm, dy_cam_mm = float(delta_cam[0]), float(delta_cam[1])
    delta_robot = np.array([
        dy_cam_mm / 1000.0,
        -dx_cam_mm / 1000.0,
        0.0,
    ])
    dist_m = float(np.linalg.norm(delta_robot[:2]))

    print(
        f"[move-to-kp] delta_cam=({dx_cam_mm:.1f}, {dy_cam_mm:.1f}) mm  "
        f"delta_robot=({delta_robot[0]*100:.2f}, {delta_robot[1]*100:.2f}, 0) cm  "
        f"dist={dist_m*100:.2f} cm"
    )

    result = {
        "delta_cam_mm": {"dx": dx_cam_mm, "dy": dy_cam_mm},
        "delta_robot_m": {"x": float(delta_robot[0]), "y": float(delta_robot[1]), "z": 0.0},
        "distance_m": dist_m,
        "cam_height_mm": cam_height_mm,
        "dry_run": req.dry_run,
        "moved": False,
    }

    if dist_m < 0.001:
        print("[move-to-kp] already centered, skipping move")
        result["message"] = "Already centered on keypoint."
        return result

    if req.dry_run:
        print(f"[move-to-kp] dry run — would move {dist_m*100:.1f} cm")
        result["message"] = f"Dry run: would move {dist_m * 100:.1f} cm."
        return result

    # 4. Execute cartesian move via lerobot
    import sys
    sys.path.insert(0, str(Path(__file__).parent / "scripts"))
    from move_arm_cartesian import cartesian_move, obs_to_q, ALL_JOINTS, PORT, ROBOT_ID, N_STEPS
    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
    from lerobot.robots.so_follower.so_follower import SOFollower

    try:
        print(f"[move-to-kp] connecting robot on {PORT}…")
        config = SOFollowerRobotConfig(port=PORT, id=ROBOT_ID)
        robot = SOFollower(config)
        robot.connect()

        obs = await asyncio.to_thread(robot.get_observation)
        q = obs_to_q(obs)
        print(f"[move-to-kp] current joints (deg): {np.round(q, 1).tolist()}")

        n_steps = max(N_STEPS, int(dist_m / 0.0025))
        print(f"[move-to-kp] executing cartesian_move with {n_steps} steps…")
        q = await asyncio.to_thread(cartesian_move, robot, q, delta_robot, n_steps)
        print(f"[move-to-kp] move complete, final joints (deg): {np.round(q, 1).tolist()}")

        robot.disconnect()
        print("[move-to-kp] robot disconnected")
    except Exception as e:
        print(f"[move-to-kp] robot move error: {e}")
        raise HTTPException(500, f"Robot move error: {e}")

    result["moved"] = True
    result["message"] = f"Moved {dist_m * 100:.1f} cm toward keypoint."
    print(f"[move-to-kp] done — moved {dist_m*100:.1f} cm")
    return result


# ---------------------------------------------------------------------------
# Sequence: Home → Pos1 → Home → Pos2
# ---------------------------------------------------------------------------

_STEP_LABELS = ["Home", "Position 1", "Home", "Position 2", "Home"]
_sequence_status: dict = {
    "running": False, "step": "", "step_num": 0, "total": len(_STEP_LABELS),
    "error": None, "done": False, "aborted": False, "labels": _STEP_LABELS,
}
_sequence_abort = threading.Event()

SEQ_HOME = [3, -26, -7, 92, -65, 39]
SEQ_POS1 = {"x": 0.0466, "y": -0.3202, "z": 0.0099, "roll": 87.5, "pitch": 1.2, "yaw": 34.6}
SEQ_POS2 = {"x": 0.0160, "y": -0.2967, "z": 0.0110, "roll": 90.7, "pitch": -0.3, "yaw": 28.5}
SEQ_SPEED = 10
SEQ_HOLD = 3


def _run_sequence_blocking():
    """Execute the demo sequence in a background thread."""
    import numpy as np
    global _sequence_status
    ctrl = get_motor_controller()
    kin = get_kinematics()
    try:
        def solve(pos):
            target_xyz = (pos["x"], pos["y"], pos["z"])
            target_rpy = (pos["roll"], pos["pitch"], pos["yaw"])
            q_init = np.zeros(6)
            result = kin.inverse_kinematics(target_xyz, target_rpy, q_init, pos.get("gripper", 39.0), True)
            if not result["success"]:
                raise ValueError(f"IK failed: error={result['error_mm']:.1f}mm")
            return result["joints_deg"]

        joints1 = solve(SEQ_POS1)
        joints2 = solve(SEQ_POS2)

        steps = [
            ("Home", SEQ_HOME),
            ("Position 1", joints1),
            ("Home", SEQ_HOME),
            ("Position 2", joints2),
            ("Home", SEQ_HOME),
        ]

        for i, (label, joints) in enumerate(steps, 1):
            if _sequence_abort.is_set():
                _sequence_status = {"running": False, "step": f"Aborted at step {i}", "step_num": i, "total": 5, "error": None, "done": False, "aborted": True, "labels": _STEP_LABELS}
                return
            _sequence_status = {"running": True, "step": f"Moving to {label}", "step_num": i, "total": 5, "error": None, "done": False, "aborted": False, "labels": _STEP_LABELS}
            ctrl.write_joint_array(joints, SEQ_SPEED)
            _sequence_status["step"] = f"Holding at {label}"
            for _ in range(int(SEQ_HOLD / 0.25)):
                if _sequence_abort.is_set():
                    _sequence_status = {"running": False, "step": f"Aborted at {label}", "step_num": i, "total": 5, "error": None, "done": False, "aborted": True, "labels": _STEP_LABELS}
                    return
                time.sleep(0.25)

        _sequence_status = {"running": False, "step": "Complete", "step_num": 5, "total": 5, "error": None, "done": True, "aborted": False, "labels": _STEP_LABELS}
    except Exception as e:
        _sequence_status = {"running": False, "step": "Error", "step_num": 0, "total": 5, "error": str(e), "done": False, "aborted": False, "labels": _STEP_LABELS}


@app.post("/api/sequence/run")
async def run_sequence():
    """Start the Home→Pos1→Home→Pos2→Home demo sequence."""
    global _sequence_status
    if _sequence_status["running"]:
        raise HTTPException(409, "Sequence already running")
    ctrl = get_motor_controller()
    if not ctrl.is_connected:
        raise HTTPException(400, "Robot not connected")
    _sequence_abort.clear()
    _sequence_status = {"running": True, "step": "Starting", "step_num": 0, "total": 5, "error": None, "done": False, "aborted": False, "labels": _STEP_LABELS}
    t = threading.Thread(target=_run_sequence_blocking, daemon=True)
    t.start()
    return {"status": "started", "labels": _STEP_LABELS}


@app.post("/api/sequence/abort")
async def abort_sequence():
    """Abort the running sequence."""
    if not _sequence_status["running"]:
        raise HTTPException(400, "No sequence running")
    _sequence_abort.set()
    return {"status": "aborting"}


@app.get("/api/sequence/status")
async def sequence_status():
    return _sequence_status


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
