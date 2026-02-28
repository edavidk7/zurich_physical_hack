/**
 * Send to Robot Tool
 *
 * Sends drawing commands to the SO-ARM100 robot arm over serial.
 * Commands are forwarded to src/robot_sender.py via stdin.
 *
 * Place in .pi/extensions/ — auto-discovered by pi.
 */

import { Type } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { spawn } from "child_process";
import { resolve } from "path";

const PROJECT_ROOT = resolve(__dirname, "..", "..");
const DEFAULT_PORT = "/dev/ttyUSB0";

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "send_to_robot",
		label: "Send to Robot",
		description:
			"Send drawing commands to the SO-ARM100 robot arm over serial. " +
			"Accepts a list of drawing_commands (PEN_UP, PEN_DOWN, MOVE, LINE, ARC). " +
			"Use dry_run=true to validate commands without moving the arm. " +
			"Positions are in mm relative to the arm's workspace origin.",
		parameters: Type.Object({
			drawing_commands: Type.Array(
				Type.Object({
					type: Type.Union(
						[
							Type.Literal("PEN_UP"),
							Type.Literal("PEN_DOWN"),
							Type.Literal("MOVE"),
							Type.Literal("LINE"),
							Type.Literal("ARC"),
						],
						{ description: "Command type" }
					),
				}, { additionalProperties: true }),
				{ description: "List of drawing commands to execute" }
			),
			port: Type.Optional(
				Type.String({ description: `Serial port (default: ${DEFAULT_PORT})` })
			),
		}),

		async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
			const {
				drawing_commands,
				port = DEFAULT_PORT,
			} = params as {
				drawing_commands: object[];
				port?: string;
			};

			const payload = JSON.stringify({ drawing_commands });

			const args = ["run", "python", "src/robot_sender.py", "--port", port];

			return new Promise((resolve_p) => {
				const proc = spawn("uv", args, {
					cwd: PROJECT_ROOT,
					stdio: ["pipe", "pipe", "pipe"],
				});

				// Abort if signal fires
				signal?.addEventListener("abort", () => proc.kill());

				let stdout = "";
				let stderr = "";

				proc.stdout.on("data", (d: Buffer) => { stdout += d.toString(); });
				proc.stderr.on("data", (d: Buffer) => { stderr += d.toString(); });

				// Write commands to stdin and close
				proc.stdin.write(payload);
				proc.stdin.end();

				proc.on("close", (code) => {
					try {
						const result = JSON.parse(stdout.trim());

						if (result.error) {
							resolve_p({
								content: [{ type: "text", text: `Robot error: ${result.error}` }],
								isError: true,
							});
							return;
						}

						const summary = `Mock sent: ${result.sent} command(s), ${result.errors} error(s)`;

						resolve_p({
							content: [{ type: "text", text: `${summary}\n\n${JSON.stringify(result, null, 2)}` }],
							details: { port, commands: drawing_commands.length },
						});
					} catch {
						resolve_p({
							content: [
								{
									type: "text",
									text: `Robot sender failed (exit ${code}):\nstdout: ${stdout}\nstderr: ${stderr}`,
								},
							],
							isError: true,
						});
					}
				});
			});
		},
	});
}
