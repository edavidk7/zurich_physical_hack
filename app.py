"""
DocOps — Automated Test & Verification Platform

Professional manufacturing UI: describe a task, attach documents,
view relevant specs, generated task plan, and robot status.
"""

import sys
from pathlib import Path
from datetime import datetime

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from src.parser import DocumentParser
from src.agents import DocumentSearcher, TaskPlanner

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PARSED_DIR = Path(__file__).parent / "data" / "parsed"
PLANS_DIR = Path(__file__).parent / "data" / "plans"
UPLOAD_DIR = Path(__file__).parent / "data" / "uploads"

PARSED_DIR.mkdir(parents=True, exist_ok=True)
PLANS_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DocOps — Test & Verification",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — teal manufacturing theme
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    :root {
        --teal: #37e0d8;
        --teal-dark: #2bb8b1;
        --teal-darker: #1a8a84;
        --teal-light: #b2f0ec;
        --teal-lighter: #e0faf8;
        --surface: #FAFAFA;
        --surface-alt: #F5F5F5;
        --text-primary: #212121;
        --text-secondary: #616161;
        --danger: #E53935;
        --success: #43A047;
        --warning: #FB8C00;
    }

    .block-container {
        max-width: 100% !important;
        padding: 1rem 2rem !important;
    }

    /* Hide default Streamlit header/footer */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent; }

    /* Top bar */
    .top-bar {
        background: linear-gradient(135deg, var(--teal-darker) 0%, var(--teal-dark) 100%);
        color: white;
        padding: 0.75rem 2rem;
        margin: -1rem -2rem 1.5rem -2rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-family: 'Segoe UI', system-ui, sans-serif;
    }
    .top-bar .logo {
        font-size: 1.4rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .top-bar .logo span { color: var(--teal-light); font-weight: 400; }
    .top-bar .status-bar {
        display: flex;
        gap: 1.5rem;
        font-size: 0.85rem;
        opacity: 0.9;
    }
    .top-bar .status-item {
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .status-dot {
        width: 8px; height: 8px;
        border-radius: 50%;
        display: inline-block;
    }
    .status-dot.online { background: #69F0AE; }
    .status-dot.offline { background: #EF5350; }
    .status-dot.idle { background: #FFD54F; }

    /* Primary button */
    .stButton > button[kind="primary"] {
        background-color: var(--teal) !important;
        border-color: var(--teal) !important;
        color: white !important;
        font-weight: 600;
        border-radius: 6px;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: var(--teal-dark) !important;
        border-color: var(--teal-dark) !important;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 2px solid #E0E0E0;
    }
    .stTabs [data-baseweb="tab-list"] button {
        font-weight: 500;
        padding: 0.75rem 1.5rem;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        color: var(--teal-dark) !important;
        border-bottom-color: var(--teal) !important;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid #E0E0E0;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: var(--teal-darker) !important;
        font-weight: 600;
    }

    /* Headings */
    h1, h2, h3 { color: var(--teal-darker) !important; }

    /* Metric values */
    [data-testid="stMetricValue"] { color: var(--teal-dark) !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] { color: var(--text-secondary) !important; text-transform: uppercase; font-size: 0.7rem !important; letter-spacing: 0.5px; }

    /* Cards */
    .info-card {
        background: white;
        border: 1px solid #E0E0E0;
        border-radius: 8px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.75rem;
    }
    .info-card h4 { margin: 0 0 0.5rem 0; color: var(--teal-darker); font-size: 0.95rem; }

    /* Spec & Pin chips */
    .spec-chip {
        display: inline-block;
        background: var(--teal-lighter);
        color: var(--teal-darker);
        padding: 5px 14px;
        border-radius: 6px;
        margin: 3px;
        font-size: 0.82em;
        font-weight: 500;
        border: 1px solid var(--teal-light);
    }
    .pin-chip {
        display: inline-block;
        background: #FFF8E1;
        color: #E65100;
        padding: 5px 14px;
        border-radius: 6px;
        margin: 3px;
        font-size: 0.82em;
        font-weight: 500;
        border: 1px solid #FFE0B2;
    }

    /* Step rows */
    .step-row {
        display: flex;
        align-items: flex-start;
        gap: 1rem;
        padding: 0.85rem 1rem;
        margin: 4px 0;
        background: white;
        border: 1px solid #EEEEEE;
        border-radius: 8px;
        border-left: 4px solid var(--teal);
    }
    .step-row:hover { border-left-color: var(--teal-dark); background: #FAFFFE; }
    .step-num {
        background: var(--teal);
        color: white;
        width: 28px; height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.8rem;
        font-weight: 700;
        flex-shrink: 0;
    }
    .step-body { flex: 1; }
    .step-action {
        font-weight: 700;
        color: var(--teal-darker);
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .step-desc { color: var(--text-primary); margin-top: 2px; }
    .step-meta { color: var(--text-secondary); font-size: 0.8rem; margin-top: 4px; }

    /* Robot status panel */
    .robot-panel {
        background: linear-gradient(135deg, var(--teal-darker) 0%, #00695C 100%);
        color: white;
        border-radius: 10px;
        padding: 1.25rem;
        margin-bottom: 1rem;
    }
    .robot-panel h4 { color: white !important; margin: 0 0 0.75rem 0; font-size: 0.95rem; }
    .robot-stat {
        display: flex;
        justify-content: space-between;
        padding: 0.3rem 0;
        font-size: 0.85rem;
        border-bottom: 1px solid rgba(255,255,255,0.15);
    }
    .robot-stat:last-child { border-bottom: none; }
    .robot-stat .label { opacity: 0.8; }
    .robot-stat .value { font-weight: 600; }

    /* Camera feed placeholder */
    .camera-feed {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 0;
        overflow: hidden;
        position: relative;
        aspect-ratio: 16/9;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #6C7A89;
        font-size: 0.9rem;
        border: 2px solid #333;
    }
    .camera-overlay {
        position: absolute;
        top: 8px; left: 10px;
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.7rem;
        color: #aaa;
    }
    .camera-overlay .rec {
        width: 8px; height: 8px;
        background: #EF5350;
        border-radius: 50%;
        animation: blink 1.5s infinite;
    }
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

    /* Input area */
    .stTextArea textarea {
        border: 2px solid #E0E0E0 !important;
        border-radius: 8px !important;
    }
    .stTextArea textarea:focus {
        border-color: var(--teal) !important;
        box-shadow: 0 0 0 1px var(--teal) !important;
    }

    /* Example prompt pills */
    .example-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 0.5rem;
    }
    .example-pill-label {
        font-size: 0.78rem;
        color: var(--text-secondary);
        margin-bottom: 4px;
    }

    /* Dividers */
    hr { border-color: #EEEEEE !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

if "search_results" not in st.session_state:
    st.session_state.search_results = None
if "task_plan" not in st.session_state:
    st.session_state.task_plan = None
if "robot_status" not in st.session_state:
    st.session_state.robot_status = "idle"  # idle / running / complete / error
if "selected_example" not in st.session_state:
    st.session_state.selected_example = ""

EXAMPLE_PROMPTS = [
    "Verify the Arduino 3.3V pin outputs correct voltage per datasheet specs",
    "Inspect conveyor belt tension according to maintenance manual",
    "Run pre-shift safety checklist for CNC lathe startup",
    "Check torque on M8 bolts per assembly SOP",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_available_docs() -> list[Path]:
    """Get all parsed markdown docs."""
    return sorted(PARSED_DIR.glob("*_parsed.md"))


def parse_uploaded_file(uploaded_file) -> Path | None:
    """Parse an uploaded PDF and return the parsed markdown path."""
    upload_path = UPLOAD_DIR / uploaded_file.name
    upload_path.write_bytes(uploaded_file.getbuffer())
    parser = DocumentParser()
    doc = parser.parse(upload_path)
    doc.save_json(PARSED_DIR)
    md_path = doc.save_markdown(PARSED_DIR)
    return md_path


# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------

now = datetime.now().strftime("%Y-%m-%d %H:%M")
robot_dot = {"idle": "idle", "running": "online", "complete": "online", "error": "offline"}
robot_label = {"idle": "Idle", "running": "Executing…", "complete": "Ready", "error": "Error"}

st.markdown(f"""
<div class="top-bar">
    <div class="logo">⚙️ DocOps <span>| Test & Verification Platform</span></div>
    <div class="status-bar">
        <div class="status-item">
            <span class="status-dot online"></span> System Online
        </div>
        <div class="status-item">
            <span class="status-dot {robot_dot.get(st.session_state.robot_status, 'idle')}"></span>
            Robot: {robot_label.get(st.session_state.robot_status, 'Idle')}
        </div>
        <div class="status-item">🕐 {now}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Layout: main (left) + robot panel (right)
# ---------------------------------------------------------------------------

main_col, robot_col = st.columns([3, 1], gap="large")

# ======================== RIGHT: Robot & Camera ========================
with robot_col:
    # Robot status
    st.markdown("""
    <div class="robot-panel">
        <h4>🤖 SO-ARM100 Status</h4>
        <div class="robot-stat"><span class="label">State</span><span class="value">Idle</span></div>
        <div class="robot-stat"><span class="label">Position</span><span class="value">Home</span></div>
        <div class="robot-stat"><span class="label">Tool</span><span class="value">Multimeter Probe</span></div>
        <div class="robot-stat"><span class="label">Last Task</span><span class="value">—</span></div>
        <div class="robot-stat"><span class="label">Uptime</span><span class="value">2h 14m</span></div>
    </div>
    """, unsafe_allow_html=True)

    # Camera feed
    st.markdown("""
    <div class="camera-feed">
        <div class="camera-overlay"><div class="rec"></div> LIVE — CAM 1</div>
        <span>📷 Camera feed</span>
    </div>
    """, unsafe_allow_html=True)

    st.caption("")  # spacing

    # Knowledge base summary
    docs = get_available_docs()
    st.markdown(f"""
    <div class="info-card">
        <h4>📚 Knowledge Base</h4>
        <div style="font-size:0.85rem; color:#616161;">
            <b>{len(docs)}</b> document(s) loaded<br>
            Ready for search & verification
        </div>
    </div>
    """, unsafe_allow_html=True)


# ======================== LEFT: Task input & results ========================
with main_col:
    # ---------- Task input section ----------
    st.markdown("### 📝 Task Definition")

    # Example prompt pills
    st.markdown('<div class="example-pill-label">Try an example:</div>', unsafe_allow_html=True)
    ex_cols = st.columns(len(EXAMPLE_PROMPTS))
    for i, example in enumerate(EXAMPLE_PROMPTS):
        with ex_cols[i]:
            if st.button(example, key=f"ex_{i}", use_container_width=True):
                st.session_state.selected_example = example

    # Use selected example as default value if set
    default_value = st.session_state.selected_example

    user_task = st.text_area(
        "Describe your task:",
        value=default_value,
        placeholder="Describe what you want to verify, measure, or test…",
        height=100,
        label_visibility="collapsed",
    )

    # Attach documents inline with the task
    attached_files = st.file_uploader(
        "📎 Attach documents (optional — datasheets, task specs, SOPs)",
        type=["pdf"],
        accept_multiple_files=True,
        key="task_docs",
        help="Attach additional documents for this specific task. They'll be parsed and searched automatically.",
    )

    # Parse attached files on the fly
    if attached_files:
        for uf in attached_files:
            stem = Path(uf.name).stem
            existing = PARSED_DIR / f"{stem}_parsed.md"
            if not existing.exists():
                with st.spinner(f"Parsing {uf.name}..."):
                    try:
                        parse_uploaded_file(uf)
                        st.toast(f"✓ {uf.name} parsed and added to knowledge base")
                    except Exception as e:
                        st.error(f"Failed to parse {uf.name}: {e}")

    bcol1, bcol2, bcol3 = st.columns([1, 1, 6])
    with bcol1:
        run_button = st.button("▶ Execute", type="primary", use_container_width=True)
    with bcol2:
        clear_button = st.button("✕ Clear", use_container_width=True)

    if clear_button:
        st.session_state.search_results = None
        st.session_state.task_plan = None
        st.rerun()

    # ---------- Run pipeline ----------
    if run_button and user_task.strip():
        docs = get_available_docs()
        if not docs:
            st.error("No documents available. Attach PDFs or add them to data/parsed/.")
        else:
            st.session_state.robot_status = "running"

            # Step 1: Search
            with st.status("🔍 Searching documents for relevant specifications...", expanded=True) as status:
                searcher = DocumentSearcher()
                results = []

                for md_file in docs:
                    doc_name = md_file.stem.replace("_parsed", "")
                    st.write(f"Scanning: **{doc_name}**")
                    content = md_file.read_text(encoding="utf-8")
                    result = searcher.search(user_task, content, doc_name)

                    if result.get("relevant", False):
                        results.append(result)
                        specs = result.get("extracted_info", {}).get("specs", [])
                        pins = result.get("extracted_info", {}).get("pins_involved", [])
                        st.write(f"  ✅ Match — {len(specs)} specs, {len(pins)} pins")
                    else:
                        reason = result.get("reason", "no match")
                        st.write(f"  ⬜ No match — {reason}")

                st.session_state.search_results = results

                if results:
                    status.update(label=f"Found relevant info in {len(results)} document(s)", state="complete")
                else:
                    status.update(label="No relevant documents found", state="error")

            # Step 2: Plan
            if results:
                with st.status("⚙️ Generating executable task plan...", expanded=True) as status:
                    planner = TaskPlanner()
                    task_plan = planner.plan(user_task, results)
                    st.session_state.task_plan = task_plan
                    plan = task_plan.get("task_plan", task_plan)
                    steps = plan.get("steps", [])
                    status.update(label=f"Task plan ready — {len(steps)} steps", state="complete")

                st.session_state.robot_status = "complete"
            else:
                st.session_state.robot_status = "error"

    # ---------- Results ----------
    if st.session_state.search_results or st.session_state.task_plan:
        st.markdown("---")

        tab1, tab2, tab3 = st.tabs(["📋 Task Plan", "🔍 Source Documents", "{ } JSON"])

        # ---- Tab 1: Task Plan ----
        with tab1:
            if st.session_state.task_plan:
                plan = st.session_state.task_plan.get("task_plan", st.session_state.task_plan)

                # Metrics row
                mcol1, mcol2, mcol3, mcol4 = st.columns(4)
                with mcol1:
                    confidence = plan.get("confidence_score", "N/A")
                    if isinstance(confidence, (int, float)):
                        st.metric("Confidence", f"{confidence:.0%}")
                    else:
                        st.metric("Confidence", confidence)
                with mcol2:
                    st.metric("Steps", len(plan.get("steps", [])))
                with mcol3:
                    summary = plan.get("summary", {})
                    est = summary.get("estimated_duration_seconds", "N/A")
                    if isinstance(est, (int, float)):
                        st.metric("Est. Duration", f"{est}s")
                    else:
                        st.metric("Est. Duration", est)
                with mcol4:
                    dut = plan.get("equipment", {}).get("dut", "—")
                    st.metric("DUT", dut)

                st.markdown(f"**{plan.get('description', '')}**")

                # Setup
                setup = plan.get("setup", {})
                if setup:
                    with st.expander("⚙️ Setup Requirements"):
                        scol1, scol2, scol3 = st.columns(3)
                        with scol1:
                            st.markdown(f"**Mode:** `{setup.get('multimeter_mode', 'N/A')}`")
                        with scol2:
                            st.markdown(f"**Range:** `{setup.get('multimeter_range', 'auto')}`")
                        with scol3:
                            st.markdown(f"**DUT Power:** `{setup.get('dut_power', 'N/A')}`")
                        if setup.get("notes"):
                            st.info(setup["notes"])

                # Steps — rendered as structured cards
                st.markdown("#### Execution Sequence")
                for step in plan.get("steps", []):
                    action = step.get("action", "?")
                    sid = step.get("step_id", "?")
                    desc = step.get("description", "")
                    params = step.get("parameters", {})
                    expected = params.get("expected_value") or {}
                    pass_crit = step.get("pass_criteria", "")
                    fail_act = step.get("fail_action", "")

                    # Build meta line
                    meta_parts = []
                    if expected:
                        nom = expected.get("nominal", "")
                        unit = expected.get("unit", "")
                        emin = expected.get("min")
                        emax = expected.get("max")
                        if emin is not None and emax is not None:
                            meta_parts.append(f"Expected: {nom} {unit} (range: {emin}–{emax} {unit})")
                        elif nom:
                            meta_parts.append(f"Expected: {nom} {unit}")
                    if params.get("probe_positive"):
                        meta_parts.append(f"Probe+: {params['probe_positive']}")
                    if params.get("probe_negative"):
                        meta_parts.append(f"Probe−: {params['probe_negative']}")

                    meta_html = f'<div class="step-meta">{" · ".join(meta_parts)}</div>' if meta_parts else ""

                    step_html = (
                        f'<div class="step-row">'
                        f'<div class="step-num">{sid}</div>'
                        f'<div class="step-body">'
                        f'<div class="step-action">{action}</div>'
                        f'<div class="step-desc">{desc}</div>'
                        f'{meta_html}'
                        f'</div></div>'
                    )
                    st.markdown(step_html, unsafe_allow_html=True)

                    if pass_crit or fail_act:
                        pc1, pc2 = st.columns(2)
                        if pass_crit:
                            with pc1:
                                st.success(f"Pass: {pass_crit}", icon="✅")
                        if fail_act:
                            with pc2:
                                st.error(f"Fail: {fail_act}", icon="❌")

                # Critical checks
                summary = plan.get("summary", {})
                critical = summary.get("critical_checks", [])
                if critical:
                    st.markdown("#### ⚠️ Critical Checks")
                    for check in critical:
                        st.markdown(f"- {check}")
            else:
                st.info("Execute a task to see the plan here.")

        # ---- Tab 2: Source Documents ----
        with tab2:
            if st.session_state.search_results:
                for i, result in enumerate(st.session_state.search_results):
                    doc_name = result.get("document_name", f"Document {i+1}")
                    task_understanding = result.get("task_understanding", "")

                    with st.expander(f"📄 {doc_name}", expanded=True):
                        st.markdown(f"*{task_understanding}*")

                        info = result.get("extracted_info", {})

                        # Specs
                        specs = info.get("specs", [])
                        if specs:
                            st.markdown("**Specifications:**")
                            for spec in specs:
                                name = spec.get("name", "?")
                                value = spec.get("value", "")
                                unit = spec.get("unit", "")
                                min_v = spec.get("min", "")
                                max_v = spec.get("max", "")
                                range_str = f" ({min_v}–{max_v} {unit})" if min_v and max_v else ""
                                st.markdown(
                                    f'<span class="spec-chip">{name}: <b>{value} {unit}</b>{range_str}</span>',
                                    unsafe_allow_html=True,
                                )

                        # Pins
                        pins = info.get("pins_involved", [])
                        if pins:
                            st.markdown("**Pins:**")
                            for pin in pins:
                                pin_name = pin.get("pin_name", "?")
                                function = pin.get("function", "")
                                vrange = pin.get("voltage_range") or {}
                                vmin = vrange.get("min", "")
                                vmax = vrange.get("max", "")
                                vunit = vrange.get("unit", "V")
                                v_str = f" ({vmin}–{vmax} {vunit})" if vmin != "" and vmax != "" else ""
                                st.markdown(
                                    f'<span class="pin-chip">📌 {pin_name}: {function}{v_str}</span>',
                                    unsafe_allow_html=True,
                                )
                                if pin.get("notes"):
                                    st.caption(f"  ↳ {pin['notes']}")

                        # Safety
                        warnings = info.get("safety_warnings", [])
                        if warnings:
                            for w in warnings:
                                st.warning(w)

                        # Procedures
                        procedures = info.get("procedures", [])
                        if procedures:
                            st.markdown("**Procedures:**")
                            for p in procedures:
                                st.markdown(f"- {p}")

                        ctx = info.get("additional_context", "")
                        if ctx:
                            st.caption(ctx)
            else:
                st.info("Execute a task to see source documents here.")

        # ---- Tab 3: Raw JSON ----
        with tab3:
            if st.session_state.task_plan:
                st.markdown("**Task Plan**")
                st.json(st.session_state.task_plan)
            if st.session_state.search_results:
                st.markdown("**Search Results**")
                st.json(st.session_state.search_results)

# ---------------------------------------------------------------------------
# Sidebar: Knowledge Base management
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 📚 Knowledge Base")

    docs = get_available_docs()
    if docs:
        for d in docs:
            name = d.stem.replace("_parsed", "")
            st.markdown(f"✓ `{name}`")
    else:
        st.caption("No documents loaded yet.")

    st.markdown("---")

    st.markdown("### ➕ Add Documents")
    sidebar_uploads = st.file_uploader(
        "Upload PDFs to knowledge base",
        type=["pdf"],
        accept_multiple_files=True,
        key="sidebar_docs",
        label_visibility="collapsed",
    )

    if sidebar_uploads:
        for uf in sidebar_uploads:
            stem = Path(uf.name).stem
            existing = PARSED_DIR / f"{stem}_parsed.md"
            if existing.exists():
                st.caption(f"✓ {uf.name}")
            else:
                with st.spinner(f"Parsing {uf.name}..."):
                    try:
                        parse_uploaded_file(uf)
                        st.success(f"✓ {uf.name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"✗ {e}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("""
<div style="text-align: center; padding: 1rem 0; color: #9E9E9E; font-size: 0.75rem;">
    DocOps — Automated Test & Verification Platform · Documents don't just get read. They get run.
</div>
""", unsafe_allow_html=True)
