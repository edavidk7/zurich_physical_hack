"""
Golden Grippers — Docling Document Parser

Handles parsing of factory documents (PDF, DOCX, PPTX, XLSX, images, markdown)
using IBM's Docling toolkit. Includes WINDOWS symlink workaround for HuggingFace
model downloads.
"""
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import ImageRefMode, PictureItem


def _patch_symlinks_windows() -> None:
    """
    On WINDOWS without Developer Mode, os.symlink fails with WinError 1314.
    This patches os.symlink to fall back to copying when symlinks aren't available.
    """
    if platform.system() != "Windows":
        return

    _orig_symlink = os.symlink

    def _copy_instead_of_symlink(src: str | Path, dst: str | Path, *args: Any, **kwargs: Any) -> None:
        try:
            _orig_symlink(src, dst, *args, **kwargs)
        except OSError:
            abs_src = (
                os.path.join(os.path.dirname(str(dst)), str(src))
                if not os.path.isabs(str(src))
                else str(src)
            )
            if os.path.isdir(abs_src):
                shutil.copytree(abs_src, str(dst))
            else:
                shutil.copy2(abs_src, str(dst))

    os.symlink = _copy_instead_of_symlink  # type: ignore


# Apply the patch on import
_patch_symlinks_windows()


class ParsedDocument:
    """Structured representation of a parsed document."""

    def __init__(self, doc: Any, source_path: Path) -> None:
        self._doc = doc
        self.source_path = source_path
        self.source_name = source_path.name

    @property
    def to_dict(self) -> Dict[str, Any]:
        """Export document as a structured dictionary (JSON-serializable)."""
        return self._doc.export_to_dict()

    @property
    def markdown(self) -> str:
        """Export document as markdown string."""
        return self._doc.export_to_markdown()

    @property
    def tables(self) -> List[Any]:
        """Get all tables found in the document."""
        return self._doc.tables
        
    @property
    def images(self) -> List[Any]:
        """Extract all images from the document as PIL Image objects."""
        extracted_images = []
        for element, _ in self._doc.iterate_items():
            if isinstance(element, PictureItem):
                img = element.get_image(self._doc)
                if img is not None:
                    extracted_images.append(img)
        return extracted_images

    @property
    def table_dataframes(self) -> List[Any]:
        """Export all tables as pandas DataFrames."""
        dfs = []
        for table in self.tables:
            try:
                dfs.append(table.export_to_dataframe())
            except Exception:
                pass
        return dfs

    def _link_and_save_images(self, out_dir: Path) -> None:
        """Saves images to disk and mutates the document tree to reference them."""
        images_dir = out_dir / f"{self.source_path.stem}_images"
        images_dir.mkdir(parents=True, exist_ok=True)
        
        pic_counter = 1
        for element, _ in self._doc.iterate_items():
            if isinstance(element, PictureItem):
                img = element.get_image(self._doc)
                if img is not None:
                    img_name = f"image_{pic_counter}.png"
                    img_path = images_dir / img_name
                    img.save(img_path, "PNG")
                    
                    # Inject the relative path back into the Docling AST
                    if hasattr(element, "image") and element.image is not None:
                        element.image.uri = f"{images_dir.name}/{img_name}"
                        
                pic_counter += 1

    def save_json(self, output_dir: str | Path, include_images: bool = True) -> Path:
        """Save the parsed document as structured JSON with valid image refs."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        
        if include_images:
            self._link_and_save_images(out_dir)

        output_path = out_dir / f"{self.source_path.stem}_parsed.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict, f, indent=2, default=str)
        return output_path

    def save_markdown(self, output_dir: str | Path, include_images: bool = True) -> Path:
        """Save the parsed markdown to a file, referencing locally extracted images."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        
        if include_images:
            self._link_and_save_images(out_dir)
            # Use REFERENCED mode so Docling outputs ![Image](path/to/image.png)
            md_text = self._doc.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
        else:
            md_text = self.markdown

        output_path = out_dir / f"{self.source_path.stem}_parsed.md"
        output_path.write_text(md_text, encoding="utf-8")
        return output_path
        
    def save_images(self, output_dir: str | Path) -> List[Path]:
        """Explicitly save all extracted images and update their references."""
        out_dir = Path(output_dir)
        self._link_and_save_images(out_dir)
        
        images_dir = out_dir / f"{self.source_path.stem}_images"
        return list(images_dir.glob("*.png"))

    def __repr__(self) -> str:
        return (
            f"ParsedDocument('{self.source_name}', "
            f"tables={len(self.tables)}, "
            f"chars={len(self.markdown)})"
        )


class DocumentParser:
    """Parse factory documents into structured content using Docling."""

    def __init__(self, artifacts_path: Optional[Path] = None) -> None:
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
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = 2.0

        if artifacts_path:
            pipeline_options.artifacts_path = artifacts_path

        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options
                )
            }
        )

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """
        Parse a single document.

        Args:
            file_path: Path to the document file.

        Returns:
            ParsedDocument with structured content.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        result = self.converter.convert(str(path))
        return ParsedDocument(result.document, path)

    def parse_directory(
        self, dir_path: str | Path, extensions: Optional[List[str]] = None
    ) -> List[ParsedDocument]:
        """
        Parse all documents in a directory.

        Args:
            dir_path: Path to the directory.
            extensions: File extensions to include (default: common doc formats).

        Returns:
            List of ParsedDocument objects.
        """
        path = Path(dir_path)
        if extensions is None:
            extensions = [
                "*.pdf", "*.docx", "*.pptx", "*.xlsx",
                "*.md", "*.png", "*.jpg", "*.jpeg",
            ]

        files: List[Path] = []
        for ext in extensions:
            files.extend(path.glob(ext))

        results: List[ParsedDocument] = []
        for f in sorted(files):
            try:
                results.append(self.parse(f))
            except Exception as e:
                print(f"[WARNING] Failed to parse {f.name}: {e}")

        return results