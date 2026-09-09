"""Export library works + files to CSV for analysis."""

from __future__ import annotations

import csv
import io
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)


def build_books_csv(db: Session) -> str:
    """Build a BOM-prefixed CSV string of all visible works and their files.

    One row per (work, file). A work without any file still produces a single
    row with an empty path so no book is lost from the export.
    """
    rows = db.execute(
        select(
            LibraryWork.title.label("title"),
            LibraryWork.author.label("author"),
            LibraryWork.series_name.label("series_name"),
            LibraryWork.series_index.label("series_index"),
            LibraryWork.tags.label("tags"),
            LibraryWork.publication_status.label("publication_status"),
            LibraryWork.organize_status.label("organize_status"),
            LibraryWork.metadata_quality.label("metadata_quality"),
            LibraryWork.created_at.label("created_at"),
            LibraryFile.path.label("path"),
            LibraryFile.kind.label("kind"),
        )
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.work_id == LibraryWork.id,
            isouter=True,
        )
        .join(
            LibraryVolume,
            LibraryVolume.media_version_id == LibraryMediaVersion.id,
            isouter=True,
        )
        .join(LibraryFile, LibraryFile.volume_id == LibraryVolume.id, isouter=True)
        .where(LibraryWork.hidden.is_(False))
        .order_by(
            LibraryWork.created_at.asc(),
            LibraryWork.id.asc(),
            LibraryVolume.volume_index.asc(),
            LibraryFile.sort_order.asc(),
        )
    ).all()

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "标题",
            "作者",
            "系列",
            "系列序号",
            "标签",
            "出版状态",
            "整理状态",
            "元数据质量",
            "文件路径",
            "文件类型",
            "加入时间",
        ]
    )
    for row in rows:
        author = row.author if row.author else ""
        series_name = row.series_name if row.series_name else ""
        publication_status = row.publication_status or ""
        organize_status = row.organize_status or ""
        file_path = row.path if row.path else ""
        file_kind = row.kind if row.kind else ""
        writer.writerow(
            [
                row.title,
                author,
                series_name,
                row.series_index,
                "；".join(_parse_tags(row.tags)),
                publication_status,
                organize_status,
                row.metadata_quality,
                file_path,
                file_kind,
                row.created_at.isoformat() if row.created_at else "",
            ]
        )
    return "\ufeff" + buffer.getvalue()


def _parse_tags(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]