"""Pure multi-source identity arbitration for imported publications."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from pathlib import Path

from app.contracts.local_metadata import LocalMetadataSource
from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.publication_titles import titles_from_local_source
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    IdentityEvidenceDTO,
    IdentitySource,
)
from app.modules.imports.application.local_metadata import (
    LocalMetadataCandidate,
    ResolvedLocalMetadata,
    resolve_local_metadata,
)

UNKNOWN_AUTHOR = "未知作者"
_UNKNOWN_VALUES = {
    "",
    "unknown",
    "unknownauthor",
    "n/a",
    "na",
    "none",
    "未知",
    "未知作者",
    "佚名",
}
_JUNK_EMBEDDED_TITLES = {
    "无标题",
    "封面页",
    "书名",
    "未命名",
    "新建文档",
    "文档",
    "untitled",
    "unknown",
    "unknown document",
}
_JUNK_EMBEDDED_AUTHORS = {
    "administrator",
    "weiyayun",
    "dtpmac17",
    "no129231",
    "tsi",
    "pdfroom",
    "prereader",
    "studentedition",
    "ad",
    "history",
    "hbcimp1",
    "佚名",
    "unknown",
    "unknownauthor",
    "未知",
    "未知作者",
    "na",
    "none",
}
_DOWNLOAD_SOURCE_TITLE_RE = re.compile(
    r"(?:z[- ]?lib(?:rary)?|libgen|oceanofpdf|b-ok|bookzz|anna['’]?s? archive)",
    re.IGNORECASE,
)
_HEX_DUMP_RE = re.compile(r"<[0-9a-fA-F]{6,}>")


def resolve_import_metadata(
    path_identity: BookIdentityDTO,
    *,
    embedded: PublicationMetadata | None,
    sidecar: PublicationMetadata | None,
    source_order: tuple[LocalMetadataSource, ...],
    path_metadata: PublicationMetadata | None = None,
    path_publication_title: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
) -> tuple[BookIdentityDTO, ResolvedLocalMetadata]:
    """Resolve one complete local snapshot before database identity decisions."""

    resolved_path_metadata = path_metadata or _legacy_path_metadata(
        path_identity,
        path_publication_title=path_publication_title,
    )
    candidates = [
        LocalMetadataCandidate(
            source="PATH",
            metadata=resolved_path_metadata,
        )
    ]
    if embedded is not None:
        candidates.append(
            LocalMetadataCandidate(
                source="EMBEDDED",
                metadata=_normalize_source_metadata(
                    _sanitize_embedded_metadata(embedded)
                ),
            )
        )
    if sidecar is not None:
        candidates.append(
            LocalMetadataCandidate(
                source="SIDECAR_OPF", metadata=_normalize_source_metadata(sidecar)
            )
        )
    resolved = resolve_local_metadata(
        tuple(candidates),
        source_order,
        requested_title=requested_title,
        requested_author=requested_author,
    )
    publication = resolved.metadata
    title = publication.title or publication.series_name or path_identity.title
    author = publication.author or UNKNOWN_AUTHOR
    selected_source = (
        resolved.source_for("title") or resolved.source_for("author") or "PATH"
    )
    source_mapping: dict[str, IdentitySource] = {
        "SIDECAR_OPF": "sidecar_opf",
        "EMBEDDED": "epub_opf",
        "PATH": path_identity.source,
        "REQUESTED": "requested",
    }
    identity_source = source_mapping[selected_source]
    path_owned_identity = selected_source == "PATH"
    identity = replace(
        path_identity,
        title=title,
        author=author,
        volume_index=publication.volume_index,
        source=identity_source,
        confidence=1.0
        if selected_source in {"SIDECAR_OPF", "REQUESTED"}
        else path_identity.confidence,
        selection_reason="resolved_local_metadata",
        grouping_key=path_identity.grouping_key if path_owned_identity else None,
        grouping_kind=(
            path_identity.grouping_kind if path_owned_identity else "standalone"
        ),
    )
    return identity, resolved


def _legacy_path_metadata(
    path_identity: BookIdentityDTO,
    *,
    path_publication_title: str | None,
) -> PublicationMetadata:
    """Keep the unchanged audio/direct-call PATH behavior outside this refactor."""

    uses_ai_fallback = (
        path_identity.source == "ai"
        and path_identity.volume_index is None
        and path_identity.grouping_kind != "folder"
    )
    resolved_path_title = (
        path_identity.title
        if uses_ai_fallback
        else path_publication_title
        if path_publication_title is not None
        else path_identity.title
    )
    path_series_name: str | None = None
    if path_identity.grouping_kind == "folder":
        if path_publication_title is not None:
            resolved_path_title = path_publication_title
        else:
            logical_name = Path(path_identity.logical_path.replace("\\", "/")).name
            resolved_path_title = Path(logical_name).stem or path_identity.title
        path_series_name = _valid_title(path_identity.title)
    path_author = (
        _valid_author(path_identity.author)
        if path_identity.source != "ai"
        or path_identity.grouping_kind == "folder"
        or uses_ai_fallback
        else None
    )
    if (
        path_identity.grouping_kind != "folder"
        and path_identity.volume_index is not None
        and _looks_like_volume_label(path_author)
    ):
        path_author = None
    path_titles = titles_from_local_source(
        resolved_path_title,
        series_name=path_series_name,
        volume_index=path_identity.volume_index,
    )
    return PublicationMetadata(
        title=path_titles.work_title,
        volume_title=path_titles.volume_title,
        authors=(path_author,) if path_author else (),
        series_name=path_series_name,
        volume_index=path_titles.volume_index,
    )


def _sanitize_embedded_metadata(
    metadata: PublicationMetadata,
) -> PublicationMetadata:
    """Drop confidence-lowering junk from file-embedded metadata.

    Files often ship internal metadata with placeholder/source values
    (``无标题``, ``Administrator``, an ``E.B.White``-style author mis-parsed as a
    download domain, or a ``Z-Library`` residue).  These should never overwrite
    a cleaner path-derived title/author, so the offending fields are dropped
    and the PATH candidate falls back naturally.

    ``title`` and ``volume_title`` are judged independently: EPUB parsers put
    volume-label titles (``第二卷``) into ``volume_title`` while leaving
    ``title`` unset, so a missing ``title`` must not discard a valid
    ``volume_title``.
    """
    title = _clean_value(metadata.title)
    title_junk = bool(title) and _embedded_title_is_junk(title)
    volume_title = _clean_value(metadata.volume_title)
    volume_title_junk = bool(volume_title) and _embedded_title_is_junk(
        volume_title
    )
    authors = tuple(_clean_value(author) for author in metadata.authors)
    authors = tuple(author for author in authors if author)
    author_junk = any(_embedded_author_is_junk(author) for author in authors)
    if title_junk:
        title = None
    if volume_title_junk:
        volume_title = None
    if author_junk:
        authors = ()
    if not title_junk and not volume_title_junk and not author_junk:
        return metadata
    return replace(
        metadata,
        title=title,
        volume_title=volume_title,
        authors=authors,
    )


def _embedded_title_is_junk(value: str | None) -> bool:
    if not value:
        return True
    key = _identity_key(value)
    if key in _JUNK_EMBEDDED_TITLE_KEYS:
        return True
    if _HEX_DUMP_RE.search(value):
        return True
    if _DOWNLOAD_SOURCE_TITLE_RE.search(value):
        return True
    # Filename-shaped titles such as ``Elements_Pics-chinese-final`` are not
    # real publication titles; a path-derived title is preferred.
    if "_" in value:
        return True
    return False


def _embedded_author_is_junk(value: str | None) -> bool:
    if not value:
        return True
    key = _identity_key(value)
    if key in _JUNK_EMBEDDED_AUTHOR_KEYS:
        return True
    if _HEX_DUMP_RE.search(value):
        return True
    # Pure ASCII, dot-abbreviated tokens such as ``E.B.White`` were being
    # mistaken for download-source domains; treat multi-token dotted names as
    # credible authors rather than junk.
    if re.search(r"[a-z]", value, re.IGNORECASE) and re.search(r"\.", value):
        return False
    # Single-token pinyin/system usernames and identifiers.
    if re.fullmatch(r"[a-z0-9]{2,}", value):
        return True
    # Symbols only (``~ ~``). CJK names are real characters, not junk.
    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", value):
        return True
    return False


def _normalize_source_metadata(
    metadata: PublicationMetadata,
) -> PublicationMetadata:

    if metadata.volume_title is not None or metadata.title is None:
        return metadata
    titles = titles_from_local_source(
        metadata.title,
        series_name=metadata.series_name,
        volume_index=metadata.volume_index,
    )
    return replace(
        metadata,
        title=titles.work_title,
        volume_title=titles.volume_title,
        volume_index=titles.volume_index,
    )


def _looks_like_volume_label(value: str | None) -> bool:
    if value is None:
        return False
    return bool(
        re.fullmatch(
            r"(?:vol[._\s-]*\d+(?:\.\d+)?|"
            r"\u7b2c?\s*\d+(?:\.\d+)?"
            r"(?:\s*[-~\uff5e\u2014]\s*\d+(?:\.\d+)?)?"
            r"\s*[\u8bdd\u7ae0\u5377\u518c\u96c6]?)",
            value.strip(),
            flags=re.IGNORECASE,
        )
    )


def apply_requested_identity(
    path_identity: BookIdentityDTO,
    *,
    requested_title: str | None = None,
    requested_author: str | None = None,
) -> BookIdentityDTO:
    """Apply only explicit user intent before format metadata is available."""

    path_evidence = IdentityEvidenceDTO(
        source=path_identity.source,
        title=_clean_value(path_identity.title),
        author=_clean_value(path_identity.author),
        confidence=_confidence(path_identity.confidence),
    )
    evidence = _merge_evidence(path_identity.evidence, (path_evidence,))

    requested_title_value = _valid_title(requested_title)
    requested_author_value = _valid_author(requested_author)
    if requested_title_value is None and requested_author_value is None:
        return replace(path_identity, evidence=evidence)
    evidence = _merge_evidence(
        evidence,
        (
            IdentityEvidenceDTO(
                source="requested",
                title=requested_title_value,
                author=requested_author_value,
                confidence=1.0,
            ),
        ),
    )

    return replace(
        path_identity,
        title=requested_title_value or path_identity.title,
        author=requested_author_value or path_identity.author,
        source="requested",
        confidence=1.0,
        selection_reason="explicit_user_fields",
        evidence=evidence,
    )


def _merge_evidence(
    current: tuple[IdentityEvidenceDTO, ...],
    additions: tuple[IdentityEvidenceDTO, ...],
) -> tuple[IdentityEvidenceDTO, ...]:
    merged = list(current)
    keys = {(item.source, item.title, item.author, item.confidence) for item in current}
    for item in additions:
        key = (item.source, item.title, item.author, item.confidence)
        if key not in keys:
            merged.append(item)
            keys.add(key)
    return tuple(merged)


def _valid_title(value: object) -> str | None:
    cleaned = _clean_value(value)
    return cleaned if _identity_key(cleaned) not in _UNKNOWN_VALUES else None


def _valid_author(value: object) -> str | None:
    cleaned = _clean_value(value)
    return cleaned if _identity_key(cleaned) not in _UNKNOWN_VALUES else None


def _clean_value(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _identity_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s._\-()/（）]+", "", normalized)


# Precomputed junk keys: building these per call would re-normalize every
# element (NFKC + regex) for each of the tens of thousands of per-file checks.
_JUNK_EMBEDDED_TITLE_KEYS = frozenset(
    _identity_key(value) for value in _JUNK_EMBEDDED_TITLES
)
_JUNK_EMBEDDED_AUTHOR_KEYS = frozenset(
    _identity_key(value) for value in _JUNK_EMBEDDED_AUTHORS
)


def _confidence(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
