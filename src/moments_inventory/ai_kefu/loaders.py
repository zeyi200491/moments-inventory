from __future__ import annotations

from pathlib import Path


def load_text_document(path: str | Path) -> str:
    document_path = Path(path)
    return document_path.read_text(encoding="utf-8").strip()
