# Golden Grippers — Hackathon Proposal

## Document-to-Execution Pipeline: Turning Factory Knowledge into Machine-Runnable Instructions

**Live Demo: SO-ARM100 robot arm physically draws shapes extracted from documents.**

---

## 1. Problem Statement

Factories are full of documented knowledge — Standard Operating Procedures, inspection specs, maintenance manuals, assembly instructions — that only humans can read. These documents contain operational logic, sequences, tolerances, constraints, and decision trees buried in PDFs, scanned images, and spreadsheets.

Today, bridging from document to physical execution requires a human to manually interpret every step, every threshold, every decision branch. This is slow, error-prone, and doesn't scale.

**What if a document didn't just get read — it got run?**

---

## 2. Our Solution

**Golden Grippers** is a document-to-execution compiler pipeline. It takes real factory documents (SOPs, inspection sheets, maintenance manuals) and compiles them into structured, machine-executable task plans that drive robot controllers, sensor configurations, and operator HMI workflows.

This is **not a chatbot**. It is a compiler. Documents go in. Executable instructions come out.

### Core Flow

```
Factory Document (PDF / DOCX / Scanned Image / XLSX)
        │
        ▼
┌──────────────────────┐
│      Docling          │  IBM's open-source parser
│  Layout analysis      │  Table extraction
│  Formula recognition  │  Structured JSON/Markdown output
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   Docling MCP Server  │  Agentic interface
│  Convert, query, RAG  │  Structured document access
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│          DeepMind Agent Layer                  │
│                                               │
│  ┌─────────────┐  ┌──────────────┐           │
│  │ Logic        │  │ Task Plan    │           │
│  │ Extractor    │──▶│ Compiler     │           │
│  │              │  │              │           │
│  │ Sequences    │  │ JSON/YAML    │           │
│  │ Conditionals │  │ executable   │           │
│  │ Tolerances   │  │ plan         │           │
│  └─────────────┘  └──────┬───────┘           │
│                           │                   │
│  ┌─────────────┐          │                   │
│  │ Validator    │◀─────────┘                   │
│  │ Cross-check  │                              │
│  │ Flag gaps    │                              │
│  └─────────────┘                              │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
        ┌──────────────────────────┐
        │   Executable Outputs      │
        │                           │
        │  • Robot task plans       │
        │  • Sensor configurations  │
        │  • Inspection thresholds  │
        │  • Operator HMI workflow  │
        └──────────────────────────┘
```

---

## 3. Architecture

### 3.1 System Components

| Component | Technology | Role |
|-----------|-----------|------|
| **Document Ingestion** | Docling (local) | Parses PDFs, DOCX, PPTX, XLSX, scanned docs. AI-powered layout analysis, table extraction, formula recognition. Outputs structured JSON/Markdown. |
| **Agentic Document Interface** | Docling MCP Server | Exposes parsed documents as MCP tools. Enables conversion, querying, and RAG over document content. |
| **Reasoning Layer** | Google DeepMind (Gemini) | Multi-agent system that extracts logic and compiles executable plans. |
| **Orchestration** | Python (LangChain / CrewAI) | Coordinates multi-agent workflow from parse to compile to validate. |
| **Operator Interface** | Web-based HMI (Streamlit / React) | Displays executable workflow with step-by-step guidance, tolerance monitoring, decision branch navigation. |
| **Robot Hardware** | SO-ARM100 (6-DOF servo arm) | Physically executes compiled task plans. Demo: draws shapes/diagrams extracted from documents. Controlled via Python + serial (lerobot / STS3215 servos). |

### 3.2 Agent Definitions

| Agent | Input | Output | Responsibility |
|-------|-------|--------|----------------|
| **DocParser** | Raw factory document | Structured document content (via Docling MCP) | Calls Docling MCP to convert documents, extract tables, identify sections, handle messy scanned inputs. |
| **LogicExtractor** | Structured document content | Extracted operational logic | Identifies ordered sequences, conditional branches (if/then decision trees), tolerances and acceptable ranges, constraints and dependencies, safety precautions. |
| **TaskCompiler** | Extracted operational logic | Executable task plan (JSON/YAML) | Converts extracted logic into a standardized, machine-readable task plan schema. Maps steps to executable actions, thresholds to sensor checks, decisions to branching logic. |
| **Validator** | Task plan + original document | Validated task plan + confidence report | Cross-references compiled plan against source document. Flags missing information, ambiguous instructions, unresolvable tolerances. Outputs a confidence score per step. |
| **MotionPlanner** | Task plan with waypoints/paths | Joint-space trajectory for SO-ARM100 | Converts Cartesian waypoints (drawing paths, pick/place targets) into joint-angle sequences using inverse kinematics. Handles workspace limits, collision avoidance, and pen-up/pen-down transitions. |

### 3.3 Task Plan Schema (Output Format)

```json
{
  "task_plan": {
    "id": "sop-widget-assembly-v1",
    "source_document": "Widget_Assembly_SOP_v3.2.pdf",
    "generated_at": "2026-02-28T12:00:00Z",
    "confidence_score": 0.94,
    "steps": [
      {
        "step_id": 1,
        "action": "PICK",
        "target": "housing_component_A",
        "parameters": {
          "grip_force_n": 15,
          "approach_vector": [0, 0, -1]
        },
        "tolerances": {
          "position_mm": 0.5,
          "orientation_deg": 2.0
        },
        "preconditions": [],
        "next": 2
      },
      {
        "step_id": 2,
        "action": "INSPECT",
        "target": "housing_component_A",
        "parameters": {
          "measurement": "surface_roughness",
          "sensor": "vision_camera_1",
          "acceptable_range": { "min": 0.8, "max": 1.6, "unit": "μm Ra" }
        },
        "decision": {
          "pass": { "next": 3 },
          "fail": { "next": "REJECT", "alert": "operator" }
        }
      },
      {
        "step_id": 3,
        "action": "ASSEMBLE",
        "target": "housing_component_A + shaft_B",
        "parameters": {
          "torque_nm": 12.5,
          "torque_tolerance_nm": 0.3,
          "sequence": "insert_then_rotate"
        },
        "preconditions": ["step_2.result == PASS"],
        "next": 4
      }
    ]
  }
}
```

---

## 4. Key Use Cases

### Use Case A (PRIMARY DEMO): Technical Drawing / Diagram → Robot Draws It

A document containing a technical drawing, diagram, flowchart, or shape (e.g., a PDF with an engineering sketch, a floor plan, a company logo) is parsed by Docling. The agent extracts the visual elements — lines, curves, shapes, text labels — and converts them into an ordered sequence of 2D waypoints. The MotionPlanner translates these waypoints into joint-angle trajectories for the SO-ARM100 robot arm, which physically draws the shape on paper with a mounted pen.

**Pipeline:**
```
Document with diagram/drawing (PDF)
    → Docling (layout analysis, image/figure extraction)
    → Agent: Extract shapes, lines, curves as 2D coordinates
    → Agent: Optimize drawing order (minimize pen-up travel)
    → MotionPlanner: IK → joint trajectories for SO-ARM100
    → SO-ARM100 draws it on paper
```

**Why this is the strongest demo:** The audience watches a document go in and a robot physically reproduce what's in it. Zero ambiguity about "document-to-physical bridging."

### Use Case B: Assembly SOP → Robot Task Plan

A Standard Operating Procedure PDF describes how to assemble a widget: pick parts, inspect surfaces, apply torque, verify alignment. Docling parses the document — extracting ordered steps from prose, torque specs from tables, tolerances from footnotes. The agent layer compiles these into a robot-executable task plan with pick/place coordinates, torque parameters, and inspection checkpoints.

### Use Case C: Inspection Specification → Sensor Config + Pass/Fail Engine

A quality inspection document (PDF with measurement tables, tolerance ranges, sampling rules) is parsed by Docling's table extractor. The agent maps each measurement to a sensor channel, defines thresholds, and generates an automated pass/fail decision engine. Output drives the HMI inspection dashboard.

### Use Case D: Maintenance Manual → Guided Troubleshooting Workflow

A scanned maintenance manual (messy, multi-column, with diagrams) is processed by Docling's AI-powered layout analysis. The agent extracts the troubleshooting decision tree and presents it as an interactive guided workflow on the operator HMI — "Is the motor humming? → Yes → Check capacitor voltage → Reading below 200V? → Replace capacitor."

---

## 5. Why This Stands Out

| Judging Criteria | How We Address It |
|-------------------|-------------------|
| **Working pipeline** | End-to-end: document in → executable plan out → robot draws it. Fully demo-able with real hardware. |
| **Real document-to-physical bridging** | SO-ARM100 robot arm physically draws shapes extracted from documents. Not a simulation — real pen on real paper. Also generates sensor configs and operator workflows. |
| **Deployment on real HMI** | Web-based operator dashboard shows step-by-step execution, live tolerance monitoring, decision branch navigation. |
| **Smart use of Docling** | Leverages table extraction (tolerances, specs), layout analysis (multi-column manuals), formula recognition (engineering calculations), MCP Server for agentic RAG querying. |
| **Handling messy real-world documents** | Designed for scanned PDFs, mixed formats, inconsistent layouts. Validator agent flags and resolves ambiguities rather than silently failing. |

---

## 6. Technology Stack

| Layer | Technology |
|-------|-----------|
| Document Parsing | **Docling** (local, open-source) |
| Agentic Document Access | **Docling MCP Server** (RAG, query, convert) |
| Agent Reasoning | **Google DeepMind / Gemini** models |
| Agent Orchestration | **Python** with **LangChain** or **CrewAI** |
| Task Plan Format | **JSON** (standardized schema) |
| Operator HMI | **Streamlit** or **React** web dashboard |
| Validation | Custom Validator agent + schema validation |
| Robot Hardware | **SO-ARM100** (6-DOF, STS3215 servos, serial control) |
| Robot Control | **Python** (lerobot / custom IK + trajectory planning) |
| Drawing Pipeline | SVG path extraction → waypoint generation → IK → joint commands |

---

## 7. Demo Plan

**Live demo flow (5 minutes):**

1. **Upload** a document containing a technical drawing or diagram (PDF) into the system.
2. **Watch** Docling parse it — show extracted figures, shapes, and structured content on screen.
3. **Show** the agent chain — shape extraction, waypoint generation, drawing order optimization.
4. **Display** the compiled task plan — 2D waypoints, pen-up/pen-down commands, joint trajectories.
5. **SO-ARM100 draws it** — the robot arm physically reproduces the drawing on paper with a pen. The audience watches the document come to life.
6. **HMI overlay** — the operator dashboard shows real-time arm position, progress through the task plan, and step-by-step execution.
7. **Bonus round** — feed in a second document (e.g., a messy scanned SOP) and show the full pipeline: parsing, logic extraction, task plan compilation, and Validator flagging ambiguities.

---

## 8. Team

**Golden Grippers**

---

## 9. Timeline

| Phase | Deliverable | Time |
|-------|------------|------|
| Setup | Docling + MCP Server running locally, DeepMind API connected, SO-ARM100 serial link verified | Hour 1-2 |
| Core Pipeline | DocParser + LogicExtractor agents working end-to-end | Hour 3-5 |
| Drawing Pipeline | Document → shape extraction → 2D waypoints → IK → SO-ARM100 draws basic shapes | Hour 5-8 |
| Task Compiler | TaskCompiler producing valid JSON task plans for general SOPs | Hour 8-9 |
| HMI | Operator dashboard with real-time arm visualization + task plan stepping | Hour 9-11 |
| Integration | Full pipeline: document → parse → compile → draw + validate | Hour 11-12 |
| Polish & Demo | End-to-end demo rehearsal, edge cases, presentation prep | Hour 12-14 |

---

## 10. Hardware Setup

### SO-ARM100 Configuration
- **Arm:** SO-ARM100 (6-DOF, STS3215 bus servos)
- **End effector:** Pen holder attachment (pen mounted to gripper)
- **Drawing surface:** A4 paper on flat surface within arm workspace
- **Control:** Python serial interface (USB-to-TTL → servo bus)
- **Workspace:** ~20cm x 20cm drawing area at table height

### Drawing Pipeline Detail
```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  Docling      │     │  DeepMind     │     │  SO-ARM100   │
│  extracts     │────▶│  Agent        │────▶│  draws it    │
│  figures/     │     │  converts to  │     │  on paper    │
│  diagrams     │     │  2D waypoints │     │              │
└──────────────┘     └───────────────┘     └──────────────┘
                           │
                     ┌─────▼─────┐
                     │   IK      │
                     │  Solver   │
                     │  (joint   │
                     │  angles)  │
                     └───────────┘
```

**Waypoint format:**
```json
{
  "drawing_commands": [
    { "type": "PEN_UP",   "position": [0, 0, 50] },
    { "type": "MOVE",     "position": [10, 20, 50] },
    { "type": "PEN_DOWN", "position": [10, 20, 5] },
    { "type": "LINE",     "from": [10, 20], "to": [50, 80] },
    { "type": "ARC",      "center": [30, 50], "radius": 15, "start_deg": 0, "end_deg": 180 },
    { "type": "PEN_UP",   "position": [50, 80, 50] }
  ]
}
```

---

*Golden Grippers — Documents don't just get read. They get run.*
