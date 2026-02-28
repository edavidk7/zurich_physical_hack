"""
SO-ARM100 Robot Sender (MOCK) — accepts drawing commands via stdin (JSON)
and simulates sending them to the arm.

Usage:
    echo '<json>' | uv run python src/robot_sender.py
    uv run python src/robot_sender.py --port /dev/ttyUSB0

Drawing command format (from stdin, one JSON object):
{
  "drawing_commands": [
    { "type": "PEN_UP",   "position": [x, y, z] },
    { "type": "MOVE",     "position": [x, y, z] },
    { "type": "PEN_DOWN", "position": [x, y, z] },
    { "type": "LINE",     "from": [x, y], "to": [x, y] },
    { "type": "ARC",      "center": [x, y], "radius": r, "start_deg": 0, "end_deg": 180 }
  ]
}

All positions are in mm relative to the arm's workspace origin.
"""

import argparse
import json
import sys


def _encode_command(cmd: dict) -> str:
    """Encode a drawing command to a serial string (for display/logging)."""
    cmd_type = cmd["type"]

    if cmd_type in ("PEN_UP", "PEN_DOWN", "MOVE"):
        x, y, z = cmd["position"]
        return f"MOVE {int(x*10)} {int(y*10)} {int(z*10)}"

    elif cmd_type == "LINE":
        x1, y1 = cmd["from"]
        x2, y2 = cmd["to"]
        return f"LINE {int(x1*10)} {int(y1*10)} {int(x2*10)} {int(y2*10)}"

    elif cmd_type == "ARC":
        cx, cy = cmd["center"]
        r = cmd["radius"]
        start = cmd.get("start_deg", 0)
        end = cmd.get("end_deg", 360)
        return f"ARC {int(cx*10)} {int(cy*10)} {int(r*10)} {int(start)} {int(end)}"

    else:
        raise ValueError(f"Unknown command type: {cmd_type}")


def send_commands(commands: list, port: str) -> dict:
    results = []
    for i, cmd in enumerate(commands):
        cmd_type = cmd.get("type", "UNKNOWN")
        try:
            encoded = _encode_command(cmd)
            results.append({
                "index": i,
                "command": cmd_type,
                "encoded": encoded,
                "status": "mock_sent",
            })
        except Exception as e:
            results.append({
                "index": i,
                "command": cmd_type,
                "status": "error",
                "error": str(e),
            })

    errors = [r for r in results if r["status"] == "error"]
    return {
        "port": port,
        "mock": True,
        "sent": len(results),
        "errors": len(errors),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Send drawing commands to SO-ARM100 (mock)")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port (unused in mock)")
    args = parser.parse_args()

    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"error": "No input. Pipe JSON drawing commands to stdin."}))
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    commands = payload.get("drawing_commands", [])
    if not commands:
        print(json.dumps({"error": "No drawing_commands found in input"}))
        sys.exit(1)

    result = send_commands(commands, args.port)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
