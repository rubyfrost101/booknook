"""Pure import filename eligibility rules shared by delivery adapters."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.audio_types import SUPPORTED_AUDIO_EXTS

SUPPORTED_IMPORT_FILE_EXTENSIONS = frozenset(
    {
        ".azw",
        ".azw3",
        ".cbz",
        ".cbr",
        ".epub",
        ".fb2",
        ".mobi",
        ".pdf",
        ".prc",
        ".rar",
        ".txt",
        # `.zip` 被排除：作为图书备份格式，不识别入库，避免与解压后的文件重复。
        *SUPPORTED_AUDIO_EXTS,
    }
)


def is_supported_import_filename(value: str | Path) -> bool:
    return Path(value).suffix.lower() in SUPPORTED_IMPORT_FILE_EXTENSIONS
