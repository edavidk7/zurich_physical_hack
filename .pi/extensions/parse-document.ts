/**
 * Parse Document Tool
 *
 * Calls docling (via Python) to parse a document (PDF, DOCX, etc.)
 * and returns structured JSON or markdown content.
 *
 * Place in .pi/extensions/ — auto-discovered by pi.
 */

import { Type } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { execFile } from "child_process";
import { promisify } from "util";
import { resolve } from "path";

const execFileAsync = promisify(execFile);

// Root of the Golden Grippers project (two levels up from .pi/extensions/)
const PROJECT_ROOT = resolve(__dirname, "..", "..");

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "parse_document",
		label: "Parse Document",
		description:
			"Parse a factory document (PDF, DOCX, XLSX, image) using Docling. " +
			"Returns structured content including text, tables, and layout. " +
			"Use format='markdown' for human-readable output, 'json' for structured data.",
		parameters: Type.Object({
			file_path: Type.String({
				description: "Absolute or project-relative path to the document to parse",
			}),
			format: Type.Optional(
				Type.Union([Type.Literal("json"), Type.Literal("markdown")], {
					description: "Output format: 'json' (default) or 'markdown'",
				})
			),
		}),

		async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
			const { file_path, format = "json" } = params as {
				file_path: string;
				format?: "json" | "markdown";
			};

			const absPath = resolve(PROJECT_ROOT, file_path);

			try {
				const { stdout, stderr } = await execFileAsync(
					"uv",
					["run", "python", "src/parse_doc_cli.py", absPath, "--format", format],
					{
						cwd: PROJECT_ROOT,
						signal,
						maxBuffer: 50 * 1024 * 1024, // 50MB — parsed docs can be large
					}
				);

				if (stderr) {
					// Docling writes progress to stderr — only fail on actual errors
					const errLines = stderr.split("\n").filter(
						(l) => l.includes("ERROR") || l.includes("Traceback")
					);
					if (errLines.length > 0) {
						return {
							content: [{ type: "text", text: `Parse error:\n${errLines.join("\n")}` }],
							isError: true,
						};
					}
				}

				const text = stdout.trim();

				// Check if the output itself is an error JSON
				if (format === "json") {
					try {
						const parsed = JSON.parse(text);
						if (parsed.error) {
							return {
								content: [{ type: "text", text: `Error: ${parsed.error}` }],
								isError: true,
							};
						}
					} catch {
						// Not JSON — return as-is
					}
				}

				return {
					content: [{ type: "text", text }],
					details: { file: absPath, format },
				};
			} catch (err: any) {
				return {
					content: [{ type: "text", text: `Failed to parse document: ${err.message}` }],
					isError: true,
				};
			}
		},
	});
}
