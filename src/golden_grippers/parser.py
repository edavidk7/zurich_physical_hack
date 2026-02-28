"""
Golden Grippers — Docling Document Parser

Handles parsing of factory documents (PDF, DOCX, PPTX, XLSX, images, markdown)
using IBM's Docling toolkit. Includes Windows symlink workaround for HuggingFace
model downloads.
"""

import json
import os
import platform
import shutil
from pathlib import Path
from typing import Optional

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions


def _patch_symlinks_windows():
    """
    On Windows without Developer Mode, os.symlink fails with WinError 1314.
    This patches os.symlink to fall back to copying when symlinks aren't available.
    """
    if platform.system() != "Windows":
        return

    _orig_symlink = os.symlink

    def _copy_instead_of_symlink(src, dst, *args, **kwargs):
        try:
            _orig_symlink(src, dst, *args, **kwargs)
        except OSError:
            abs_src = (
                os.path.join(os.path.dirname(dst), src)
                if not os.path.isabs(src)
                else src
            )
            if os.path.isdir(abs_src):
                shutil.copytree(abs_src, dst)
            else:
                shutil.copy2(abs_src, dst)

    os.symlink = _copy_instead_of_symlink


# Apply the patch on import
_patch_symlinks_windows()


class DocumentParser:
    """Parse factory documents into structured content using Docling."""

    def __init__(self, artifacts_path: Optional[Path] = None):
        """
        Initialize the parser.

        Args:
            artifacts_path: Optional path to local model artifacts directory.
                           If not set, models are downloaded from HuggingFace.
        """
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_table_structure = True
        pipeline_options.do_ocr = True

        if artifacts_path:
            pipeline_options.artifacts_path = artifacts_path

        self.converter = DocumentConverter(
            format_options={
                "application/pdf": PdfFormatOption(
                    pipeline_options=pipeline_options
                )
            }
        )

    def parse(self, file_path: str | Path) -> "ParsedDocument":
        """
        Parse a single document.

        Args:
            file_path: Path to the document file.

        Returns:
            ParsedDocument with structured content.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        result = self.converter.convert(str(file_path))
        return ParsedDocument(result.document, file_path)

    def parse_directory(
        self, dir_path: str | Path, extensions: list[str] | None = None
    ) -> list["ParsedDocument"]:
        """
        Parse all documents in a directory.

        Args:
            dir_path: Path to the directory.
            extensions: File extensions to include (default: common doc formats).

        Returns:
            List of ParsedDocument objects.
        """
        dir_path = Path(dir_path)
        if extensions is None:
            extensions = [
                "*.pdf", "*.docx", "*.pptx", "*.xlsx",
                "*.md", "*.png", "*.jpg", "*.jpeg",
            ]

        files = []
        for ext in extensions:
            files.extend(dir_path.glob(ext))

        results = []
        for f in sorted(files):
            try:
                results.append(self.parse(f))
            except Exception as e:
                print(f"[WARNING] Failed to parse {f.name}: {e}")

        return results


class ParsedDocument:
    """Structured representation of a parsed document."""

    def __init__(self, doc, source_path: Path):
        self._doc = doc
        self.source_path = source_path
        self.source_name = source_path.name

    @property
    def to_dict(self) -> dict:
        """Export document as a structured dictionary (JSON-serializable)."""
        return self._doc.export_to_dict()

    @property
    def markdown(self) -> str:
        """Export document as markdown string."""
        return self._doc.export_to_markdown()

    @property
    def tables(self) -> list:
        """Get all tables found in the document."""
        return self._doc.tables

    @property
    def table_dataframes(self) -> list:
        """Export all tables as pandas DataFrames."""
        dfs = []
        for table in self.tables:
            try:
                dfs.append(table.export_to_dataframe())
            except Exception:
                pass
        return dfs

    def save_json(self, output_dir: str | Path) -> Path:
        """Save the parsed document as structured JSON."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{self.source_path.stem}_parsed.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict, f, indent=2, default=str)
        return output_path

    def save_markdown(self, output_dir: str | Path) -> Path:
        """Save the parsed markdown to a file."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{self.source_path.stem}_parsed.md"
        output_path.write_text(self.markdown, encoding="utf-8")
        return output_path

    def __repr__(self) -> str:
        return (
            f"ParsedDocument('{self.source_name}', "
            f"tables={len(self.tables)}, "
            f"chars={len(self.markdown)})"
        )
