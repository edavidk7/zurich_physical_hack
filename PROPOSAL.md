# Golden Grippers — Hackathon Proposal

## Document-to-Execution Pipeline: Turning Factory Knowledge into Machine-Runnable Instructions

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

### 3.2 Agent Definitions

| Agent | Input | Output | Responsibility |
|-------|-------|--------|----------------|
| **DocParser** | Raw factory document | Structured document content (via Docling MCP) | Calls Docling MCP to convert documents, extract tables, identify sections, handle messy scanned inputs. |
| **LogicExtractor** | Structured document content | Extracted operational logic | Identifies ordered sequences, conditional branches (if/then decision trees), tolerances and acceptable ranges, constraints and dependencies, safety precautions. |
| **TaskCompiler** | Extracted operational logic | Executable task plan (JSON/YAML) | Converts extracted logic into a standardized, machine-readable task plan schema. Maps steps to executable actions, thresholds to sensor checks, decisions to branching logic. |
| **Validator** | Task plan + original document | Validated task plan + confidence report | Cross-references compiled plan against source document. Flags missing information, ambiguous instructions, unresolvable tolerances. Outputs a confidence score per step. |

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

### Use Case A: Assembly SOP → Robot Task Plan

A Standard Operating Procedure PDF describes how to assemble a widget: pick parts, inspect surfaces, apply torque, verify alignment. Docling parses the document — extracting ordered steps from prose, torque specs from tables, tolerances from footnotes. The agent layer compiles these into a robot-executable task plan with pick/place coordinates, torque parameters, and inspection checkpoints.

### Use Case B: Inspection Specification → Sensor Config + Pass/Fail Engine

A quality inspection document (PDF with measurement tables, tolerance ranges, sampling rules) is parsed by Docling's table extractor. The agent maps each measurement to a sensor channel, defines thresholds, and generates an automated pass/fail decision engine. Output drives the HMI inspection dashboard.

### Use Case C: Maintenance Manual → Guided Troubleshooting Workflow

A scanned maintenance manual (messy, multi-column, with diagrams) is processed by Docling's AI-powered layout analysis. The agent extracts the troubleshooting decision tree and presents it as an interactive guided workflow on the operator HMI — "Is the motor humming? → Yes → Check capacitor voltage → Reading below 200V? → Replace capacitor."

---

## 5. Why This Stands Out

| Judging Criteria | How We Address It |
|-------------------|-------------------|
| **Working pipeline** | End-to-end: document in → executable plan out → HMI visualization. Fully demo-able. |
| **Real document-to-physical bridging** | Output is a machine-executable task plan (not a summary or a chatbot response). Task plans drive robot actions, sensor configs, and operator workflows on a real HMI. |
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

---

## 7. Demo Plan

**Live demo flow (5 minutes):**

1. **Upload** a real factory SOP document (PDF with text, tables, diagrams) into the system.
2. **Watch** Docling parse it — show the structured output (tables extracted, steps identified, tolerances captured).
3. **Show** the agent chain reasoning — LogicExtractor identifies sequences and decision points, TaskCompiler generates the plan.
4. **Display** the compiled task plan JSON — annotated with step-by-step actions, tolerances, and decision branches.
5. **Launch** the HMI dashboard — walk through the operator workflow: step execution, tolerance checks, pass/fail decisions, branch navigation.
6. **Demonstrate resilience** — feed in a messy scanned document and show the Validator flagging ambiguities with confidence scores.

---

## 8. Team

**Golden Grippers**

---

## 9. Timeline

| Phase | Deliverable | Time |
|-------|------------|------|
| Setup | Docling + MCP Server running locally, DeepMind API connected | Hour 1-2 |
| Core Pipeline | DocParser + LogicExtractor agents working end-to-end | Hour 3-6 |
| Compiler | TaskCompiler producing valid JSON task plans | Hour 6-8 |
| HMI | Operator dashboard rendering and stepping through task plans | Hour 8-10 |
| Validation | Validator agent + messy document handling | Hour 10-12 |
| Polish & Demo | End-to-end demo, edge cases, presentation prep | Hour 12-14 |

---

*Golden Grippers — Documents don't just get read. They get run.*
