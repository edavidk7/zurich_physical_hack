from docling.document_converter import DocumentConverter
import json

source = "sample_docs/bq79600-q1.pdf"
converter = DocumentConverter()
doc = converter.convert(source).document
with open("test.json", "w") as t:
    json.dump(doc.export_to_dict(), t)