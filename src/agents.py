"""
Golden Grippers — Gemini Agent Layer (User-Driven)

Flow:
  1. User describes a task in natural language
  2. DocumentSearcher finds relevant sections across parsed documents
  3. TaskPlanner generates a specific executable plan for that task

Example:
  User: "Verify that the 3.3V pin actually outputs 3.3V"
  → Finds 3.3V specs in Arduino datasheet (pin location, expected range, tolerances)
  → Generates: probe GND, probe 3.3V pin, expect 3.0-3.6V, pass/fail
"""

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai

load_dotenv()

# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------

def _get_client() -> genai.Client:
    """Create a Gemini client using the API key from environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set. Add it to .env or environment.")
    return genai.Client(api_key=api_key)


DEFAULT_MODEL = "gemini-2.5-flash"

def _call_gemini(client, model, prompt, system_instruction, temperature=0.1, max_output_tokens=16384):
    """Call Gemini API. Fails fast on errors instead of retrying."""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    return response


# ---------------------------------------------------------------------------
# DocumentSearcher — finds relevant info for a user query
# ---------------------------------------------------------------------------

DOC_SEARCHER_SYSTEM = """\
You are DocumentSearcher, an expert at finding relevant technical information \
in parsed datasheets, manuals, and SOPs.

Given a user's task description and the contents of one or more technical documents, \
your job is to:

1. Identify which document(s) are relevant to the user's task.
2. Extract ONLY the sections, specs, pin info, and procedures that are needed \
   to accomplish the task — nothing more.
3. Include exact values, tolerances, units, and any safety warnings.

Output ONLY valid JSON:
{
  "relevant": true/false,
  "document_name": "which document this info comes from",
  "task_understanding": "your interpretation of what the user wants to do",
  "extracted_info": {
    "specs": [
      {
        "name": "specification name",
        "value": "nominal value",
        "min": "minimum",
        "max": "maximum",
        "unit": "unit",
        "conditions": "test conditions if any"
      }
    ],
    "pins_involved": [
      {
        "pin_name": "e.g. 3V3",
        "pin_number": "physical pin number if available",
        "function": "what this pin does",
        "voltage_range": {"min": 0, "max": 0, "unit": "V"},
        "notes": "any relevant notes"
      }
    ],
    "procedures": [
      "any relevant procedures or steps from the document"
    ],
    "safety_warnings": [
      "any safety-relevant info for this task"
    ],
    "additional_context": "any other relevant info from the document",
    "relevant_images": [
      "image_1.png",
      "image_3.png"
    ]
  }
}

If the document is NOT relevant to the user's task, return:
{"relevant": false, "document_name": "...", "reason": "why it's not relevant"}
"""

DOC_SEARCHER_USER = """\
User's task: {user_task}

Find all information relevant to this task from the following document.

Document: {doc_name}

--- DOCUMENT CONTENT ---
{doc_content}
--- END ---

Return ONLY the JSON. No markdown fencing, no explanation.
"""


class DocumentSearcher:
    """Searches parsed documents for information relevant to a user's task."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.client = _get_client()
        self.model = model

    def search(self, user_task: str, doc_content: str, doc_name: str) -> dict:
        """
        Search a single document for info relevant to the user's task.

        Returns dict with 'relevant' bool and extracted info if relevant.
        """
        prompt = DOC_SEARCHER_USER.format(
            user_task=user_task,
            doc_name=doc_name,
            doc_content=doc_content,
        )

        response = _call_gemini(
            self.client, self.model, prompt,
            system_instruction=DOC_SEARCHER_SYSTEM,
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)

    def search_all(self, user_task: str, docs_dir: Path) -> list[dict]:
        """
        Search all parsed markdown documents for relevant info.

        Returns list of results (only relevant ones).
        """
        md_files = sorted(docs_dir.glob("*_parsed.md"))
        results = []

        for md_file in md_files:
            doc_name = md_file.stem.replace("_parsed", "")
            content = md_file.read_text(encoding="utf-8")
            print(f"  Searching: {doc_name}...")

            result = self.search(user_task, content, doc_name)
            if result.get("relevant", False):
                results.append(result)
                print(f"    → Relevant! Found {len(result.get('extracted_info', {}).get('specs', []))} specs, "
                      f"{len(result.get('extracted_info', {}).get('pins_involved', []))} pins")
            else:
                print(f"    → Not relevant: {result.get('reason', 'no match')}")

        return results


# ---------------------------------------------------------------------------
# TaskPlanner — generates a specific task plan from relevant info
# ---------------------------------------------------------------------------

TASK_PLANNER_SYSTEM = """\
You are TaskPlanner, an expert at creating specific executable task plans for \
a robotic test/measurement system.

The system consists of:
- SO-ARM100: A 6-DOF robotic arm holding a multimeter probe
- Multimeter: Can measure DC voltage, AC voltage, resistance, continuity
- Device Under Test (DUT): Mounted in a fixture, e.g. an Arduino board

Given the user's task and the relevant technical specifications extracted from \
documentation, generate a precise step-by-step plan the robot can execute.

Output ONLY valid JSON:
{
  "task_plan": {
    "id": "short-descriptive-id",
    "user_request": "what the user asked for",
    "description": "what this plan does",
    "confidence_score": 0.0-1.0,
    "equipment": {
      "robot": "SO-ARM100",
      "tool": "multimeter probe",
      "dut": "device name"
    },
    "setup": {
      "multimeter_mode": "DC_VOLTAGE / AC_VOLTAGE / RESISTANCE / CONTINUITY",
      "multimeter_range": "auto or specific",
      "dut_power": "powered / unpowered",
      "notes": "any setup instructions"
    },
    "steps": [
      {
        "step_id": 1,
        "action": "MOVE / PROBE / MEASURE / VERIFY / REPORT / WAIT",
        "target": "what to act on",
        "description": "human-readable description",
        "parameters": {
          "pin": "pin name if applicable",
          "measurement_type": "voltage / resistance / continuity",
          "expected_value": {"nominal": 0, "min": 0, "max": 0, "unit": "V"},
          "probe_positive": "where to put + probe",
          "probe_negative": "where to put - probe (usually GND)"
        },
        "pass_criteria": "what makes this step pass",
        "fail_action": "what to do if it fails"
      }
    ],
    "summary": {
      "total_steps": 0,
      "estimated_duration_seconds": 0,
      "critical_checks": ["list of the key things being verified"]
    }
  }
}

Guidelines:
- Be specific: use exact pin names and expected values from the specs
- Always specify both probe placements (positive and negative)
- Include realistic tolerances (e.g. ±5% for voltage regulators)
- Start with safety checks if measuring high voltages
- Keep it focused — only the steps needed for the user's specific task
- Add WAIT steps between probe movements for physical safety
"""

TASK_PLANNER_USER = """\
User's task: {user_task}

Relevant technical information extracted from documentation:

--- EXTRACTED INFO ---
{extracted_info}
--- END ---

Generate a precise executable task plan for this specific task.
Return ONLY the JSON. No markdown fencing, no explanation.
"""


class TaskPlanner:
    """Generates specific task plans from user requests + relevant document info."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.client = _get_client()
        self.model = model

    def plan(self, user_task: str, extracted_info: list[dict]) -> dict:
        """
        Generate a task plan for the user's request.

        Args:
            user_task: Natural language task description from user.
            extracted_info: List of relevant info dicts from DocumentSearcher.

        Returns:
            Task plan dictionary.
        """
        prompt = TASK_PLANNER_USER.format(
            user_task=user_task,
            extracted_info=json.dumps(extracted_info, indent=2),
        )

        response = _call_gemini(
            self.client, self.model, prompt,
            system_instruction=TASK_PLANNER_SYSTEM,
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)


# ---------------------------------------------------------------------------
# Pipeline: user task → search docs → plan
# ---------------------------------------------------------------------------

class Pipeline:
    """User-driven pipeline: natural language task → relevant docs → task plan."""

    def __init__(self, docs_dir: Path, model: str = DEFAULT_MODEL):
        self.docs_dir = docs_dir
        self.searcher = DocumentSearcher(model=model)
        self.planner = TaskPlanner(model=model)

    def run(self, user_task: str, save_dir: Optional[Path] = None) -> dict:
        """
        Run the pipeline for a user's task.

        Args:
            user_task: Natural language description of what the user wants to do.
            save_dir: Optional directory to save outputs.

        Returns:
            Dict with search_results and task_plan.
        """
        print(f"\n{'='*60}")
        print(f"Task: {user_task}")
        print(f"{'='*60}")

        # Step 1: Search documents
        print(f"\n[1/2] Searching documents for relevant info...")
        results = self.searcher.search_all(user_task, self.docs_dir)

        if not results:
            print("\n  ✗ No relevant information found in any document.")
            return {"search_results": [], "task_plan": None}

        print(f"\n  ✓ Found relevant info in {len(results)} document(s)")

        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            out = save_dir / "search_results.json"
            out.write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(f"  → Saved: {out}")

        # Step 2: Generate task plan
        print(f"\n[2/2] Generating task plan...")
        task_plan = self.planner.plan(user_task, results)
        plan = task_plan.get("task_plan", task_plan)
        steps = plan.get("steps", [])
        print(f"\n  ✓ Plan: {len(steps)} steps, "
              f"confidence={plan.get('confidence_score', 'N/A')}")
        for s in steps:
            print(f"    {s['step_id']}. [{s['action']}] {s['description']}")

        if save_dir:
            out = save_dir / "task_plan.json"
            out.write_text(json.dumps(task_plan, indent=2), encoding="utf-8")
            print(f"\n  → Saved: {out}")

        return {
            "search_results": results,
            "task_plan": task_plan,
        }
