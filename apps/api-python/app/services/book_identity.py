from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.imports.application.identity_policy import (
    contains_explicit_volume_range,
    split_explicit_volume,
    split_numeric_volume_fallback,
)
from app.services.metadata_provider_registry import metadata_provider_runtime_config

UNKNOWN_AUTHOR = "未知作者"
IDENTITY_PARSER_VERSION = 11

# Audio/textbook collections routinely contain duplicate copies whose file or
# folder names carry a parenthetical copy number attached directly to the
# previous character, e.g. ``0022_0(1).mp3`` or ``6.6_20(1).mp3``.  A
# space-separated ``Title (1)`` is still a real volume number (comics), so the
# copy suffix is detected by the lack of whitespace before the parenthesis.
_COPY_SUFFIX_RE = re.compile(r"[^\s(（][\(（]\s*\d{1,3}\s*[\)）]\s*$")

# 下载源域名（_looks_like_download_source 高频调用，模块级避免每次重编译）
_DOWNLOAD_DOMAIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/\S*)?", re.I
)

# 下载版标题中的版本/整理标记（_clean_download_title 高频调用）
_DOWNLOAD_EDITION_MARKER_RE = re.compile(
    r"校[对對訂订]|精校|全本|完整版|完[结結]|番外|修[订訂]|珍藏|典藏|插[图圖]|实[体體]|增[补補]|全集",
    re.I,
)

_BOOK_TITLE_BRACKETS_RE = re.compile(r"《\s*(.+?)\s*》")

# 剥离尾部空格分隔的副本序号括号（如「化学 第4册 (2)」）
_COPY_PARENTHETICAL_RE = re.compile(r"[\s　]*[\(（]\s*\d{1,3}\s*[\)）]\s*$")

# normalize_identity_part 全书调用最频繁，模块级编译避免每次字符串模式走 re 缓存
_NORMALIZE_PUNCTUATION_RE = re.compile(
    r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\]+"
)

# _clean_author 每本书的作者清理都会调用，预编译避免每次走 re 缓存
_LEADING_NATIONALITY_RE = re.compile(
    r"^[\(（]\s*(?:日|美|英|德|法|韩|意|俄|苏)\s*[\)）]"
)
_TRAILING_ROLE_WORD_RE = re.compile(r"(?:主编|编译|著者|译者|编写|编著|整理|著|译|编)$")
_ETC_TAIL_RE = re.compile(r"[,，]?\s*etc\.?$", re.IGNORECASE)
_LEADING_PARENTHETICAL_RE = re.compile(r"^[\(（][^)）]+[\)）]\s*")

# _clean_title 每个标题都会调用，预编译避免每次走 re 缓存
_TRAILING_EBOOK_EXT_RE = re.compile(
    r"\.(?:epub|cbz|zip|pdf|m4b|m4a|mp3)$", re.IGNORECASE
)
_WS_COLLAPSE_RE = re.compile(r"\s+")

_VOLUME_ONLY_LATIN_RE = re.compile(r"\s*(?:vol(?:ume)?\.?|v)\s*\d+(?:\.\d+)?\s*", re.I)
_VOLUME_ONLY_CJK_RE = re.compile(
    r"\s*第?\s*\d+(?:\.\d+)?\s*(?:卷|冊|册|集)\s*", re.I
)


@dataclass(frozen=True)
class BookIdentity:
    title: str
    author: str
    volume_index: float | None
    source: Literal["ai", "regex"]
    confidence: float
    logical_path: str
    fallback_reason: str | None = None
    fallback_code: str | None = None
    cache_hit: bool = False

    def raw_metadata(self) -> dict[str, Any]:
        return {
            "parserVersion": IDENTITY_PARSER_VERSION,
            "input": {"logicalPath": self.logical_path},
            "output": {
                "title": self.title,
                "author": self.author,
                "volumeIndex": self.volume_index,
                "confidence": self.confidence,
            },
            "title": self.title,
            "author": self.author,
            "volumeIndex": self.volume_index,
            "source": self.source,
            "confidence": self.confidence,
            "logicalPath": self.logical_path,
            "fallbackReason": self.fallback_reason,
            "fallbackCode": self.fallback_code,
            "cacheHit": self.cache_hit,
        }


def normalize_identity_part(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return _NORMALIZE_PUNCTUATION_RE.sub("", normalized).strip()


def identity_merge_key(title: str, author: str | None) -> str:
    return f"{normalize_identity_part(title)}:{normalize_identity_part(author or UNKNOWN_AUTHOR)}"


def logical_import_path(
    db: Session, settings: Settings, path: Path, original_name: str | None = None
) -> str:
    resolved = path.expanduser().resolve()
    roots: list[tuple[str, Path]] = []
    try:
        if "MonitorFolder" in inspect(db.connection()).get_table_names():
            from app.models.settings import MonitorFolder

            for row in db.execute(
                select(MonitorFolder.name, MonitorFolder.root_path).where(
                    MonitorFolder.enabled.is_(True)
                )
            ):
                try:
                    roots.append(
                        (
                            str(row.name or Path(str(row.root_path)).name),
                            Path(str(row.root_path)).expanduser().resolve(),
                        )
                    )
                except OSError:
                    continue
    except Exception:
        roots = []
    matching = [
        (name, root)
        for name, root in roots
        if resolved == root or root in resolved.parents
    ]
    if matching:
        name, root = max(matching, key=lambda item: len(item[1].parts))
        relative = resolved.relative_to(root)
        if original_name and relative.name != original_name:
            relative = relative.with_name(Path(original_name).name)
        return (Path(name) / relative).as_posix()

    filename = Path(original_name or resolved.name).name
    parent_name = resolved.parent.name
    parent_has_identity = (
        parse_bracketed_series_identity(parent_name, filename) is not None
    )
    _parent_title, parent_volume = _directory_title_and_volume(parent_name)
    return (
        (Path(parent_name) / filename).as_posix()
        if parent_name and (parent_has_identity or parent_volume is not None)
        else filename
    )


def recognize_book_identity(
    db: Session,
    settings: Settings,
    path: Path,
    original_name: str | None = None,
) -> BookIdentity:
    logical_path = logical_import_path(db, settings, path, original_name)
    cached_identity = _load_identity_cache(db, logical_path)
    if cached_identity is not None:
        return cached_identity

    regex_identity = recognize_book_identity_with_regex(logical_path)
    if _identity_has_normal_title_and_author(regex_identity):
        _save_identity_cache(db, regex_identity)
        return regex_identity

    ai_config, config_fallback_reason = _ai_config(db)
    if ai_config is not None:
        try:
            ai_identity = _recognize_with_ai(logical_path, ai_config)
        except Exception as exc:
            fallback_code, fallback_reason = _ai_identity_failure(exc)
            return BookIdentity(
                title=regex_identity.title,
                author=regex_identity.author,
                volume_index=regex_identity.volume_index,
                source="regex",
                confidence=regex_identity.confidence,
                logical_path=logical_path,
                fallback_reason=fallback_reason,
                fallback_code=fallback_code,
            )
        if ai_identity.volume_index is None and regex_identity.volume_index is not None:
            ai_identity = replace(ai_identity, volume_index=regex_identity.volume_index)
        _save_identity_cache(db, ai_identity)
        return ai_identity
    if not config_fallback_reason:
        return regex_identity
    return BookIdentity(
        title=regex_identity.title,
        author=regex_identity.author,
        volume_index=regex_identity.volume_index,
        source="regex",
        confidence=regex_identity.confidence,
        logical_path=logical_path,
        fallback_reason=config_fallback_reason,
        fallback_code="AI_CONFIGURATION_MISSING",
    )


def _identity_cache_available(db: Session) -> bool:
    try:
        return "BookIdentityCache" in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def _load_identity_cache(db: Session, logical_path: str) -> BookIdentity | None:
    if not _identity_cache_available(db):
        return None
    from app.models.settings import BookIdentityCache

    row = (
        db.execute(
            select(
                BookIdentityCache.title,
                BookIdentityCache.author,
                BookIdentityCache.volume_index,
                BookIdentityCache.source,
                BookIdentityCache.confidence,
            ).where(
                BookIdentityCache.logical_path == logical_path,
                BookIdentityCache.parser_version == IDENTITY_PARSER_VERSION,
            )
        )
        .mappings()
        .first()
    )
    if not row or row.get("source") not in {"ai", "regex"}:
        return None
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    author = str(row.get("author") or "").strip() or UNKNOWN_AUTHOR
    try:
        confidence = min(1.0, max(0.0, float(row.get("confidence"))))
    except (TypeError, ValueError):
        return None
    return BookIdentity(
        title=title,
        author=author,
        volume_index=_number_or_none(
            row.get("volume_index") if "volume_index" in row else row.get("volumeIndex")
        ),
        source=row["source"],
        confidence=confidence,
        logical_path=logical_path,
        cache_hit=True,
    )


def _save_identity_cache(db: Session, identity: BookIdentity) -> None:
    if identity.cache_hit or not _identity_cache_available(db):
        return
    if identity.source != "ai" and not _identity_has_normal_title_and_author(identity):
        return
    now = datetime.now()
    try:
        with db.begin_nested():
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            from app.models.settings import BookIdentityCache

            statement = (
                sqlite_insert(BookIdentityCache)
                .values(
                    logical_path=identity.logical_path,
                    title=identity.title,
                    author=identity.author,
                    volume_index=identity.volume_index,
                    source=identity.source,
                    confidence=identity.confidence,
                    parser_version=IDENTITY_PARSER_VERSION,
                    raw_json=json.dumps(identity.raw_metadata(), ensure_ascii=False),
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[BookIdentityCache.logical_path],
                    set_={
                        "title": identity.title,
                        "author": identity.author,
                        "volumeIndex": identity.volume_index,
                        "source": identity.source,
                        "confidence": identity.confidence,
                        "parserVersion": IDENTITY_PARSER_VERSION,
                        "rawJson": json.dumps(
                            identity.raw_metadata(), ensure_ascii=False
                        ),
                        "updatedAt": now,
                    },
                )
            )
            db.execute(statement)
    except Exception:
        return


def _identity_significant_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character)[:1] in {"L", "N"}
    )


def _identity_value_is_abnormal(value: Any) -> bool:
    significant = _identity_significant_text(value)
    if not 2 <= len(significant) <= 10:
        return True
    if all(character.isdigit() for character in significant):
        return True
    return bool(re.fullmatch(r"[a-z]+", significant, re.I))


def _identity_has_normal_title_and_author(identity: BookIdentity) -> bool:
    author_key = normalize_identity_part(identity.author)
    return bool(
        author_key
        and author_key != normalize_identity_part(UNKNOWN_AUTHOR)
        and not _identity_value_is_abnormal(identity.title)
        and not _identity_value_is_abnormal(identity.author)
    )


def recognize_book_identity_with_regex(logical_path: str) -> BookIdentity:
    path = Path(logical_path)
    stem = path.stem.strip()
    volume_stem = _strip_download_suffixes(stem)
    _stem_title, suffix_volume = _strip_volume_suffix(_clean_title(volume_stem))
    volume_index = _volume_index(volume_stem) or suffix_volume

    for ancestor in reversed(path.parent.parts):
        bracketed = parse_bracketed_series_identity(ancestor, stem)
        if bracketed:
            return BookIdentity(
                title=bracketed[0],
                author=bracketed[1],
                volume_index=volume_index,
                source="regex",
                confidence=0.98,
                logical_path=logical_path,
            )

    bracketed_file = _bracket_identity(stem, allow_volume_range=False)
    if bracketed_file:
        return BookIdentity(
            title=bracketed_file[0],
            author=bracketed_file[1],
            volume_index=volume_index,
            source="regex",
            confidence=0.96,
            logical_path=logical_path,
        )

    download_identity = _download_filename_identity(stem)
    if download_identity:
        return BookIdentity(
            title=download_identity[0],
            author=download_identity[1],
            volume_index=volume_index,
            source="regex",
            confidence=0.94,
            logical_path=logical_path,
        )

    dash_parts = re.split(r"\s+-\s+", stem, maxsplit=1)
    if len(dash_parts) == 2:
        title = _clean_title(dash_parts[0].split("_", 1)[0])
        author = _clean_author(dash_parts[1])
        title, suffix_volume = _strip_volume_suffix(title)
        if title:
            return BookIdentity(
                title=title,
                author=author or UNKNOWN_AUTHOR,
                volume_index=volume_index
                if volume_index is not None
                else suffix_volume,
                source="regex",
                confidence=0.9 if author else 0.72,
                logical_path=logical_path,
            )

    parenthesized_year_identity = _parenthesized_year_author_identity(stem)
    if parenthesized_year_identity:
        title, author = parenthesized_year_identity
        return BookIdentity(
            title=title,
            author=author,
            volume_index=volume_index,
            source="regex",
            confidence=0.9,
            logical_path=logical_path,
        )

    for ancestor in reversed(path.parent.parts):
        ancestor_title, ancestor_volume = _directory_title_and_volume(ancestor)
        if ancestor_volume is not None and ancestor_title:
            return BookIdentity(
                title=ancestor_title,
                author=UNKNOWN_AUTHOR,
                volume_index=volume_index
                if volume_index is not None
                else ancestor_volume,
                source="regex",
                confidence=0.7,
                logical_path=logical_path,
            )
        grade_volume = _grade_directory_volume(ancestor)
        if grade_volume is not None and volume_index is None:
            volume_index = grade_volume

    stripped_title = _clean_title(stem)
    suffix_volume = None
    has_grade_directory = any(
        _grade_directory_volume(ancestor) is not None
        for ancestor in path.parent.parts
    )
    if has_grade_directory and volume_index is not None:
        # Volume already came from the grade directory; keep embedded digits
        # such as "g2 vocabulary cards" inside the title.
        stripped_title = _clean_title(stem)
    else:
        stripped_title, suffix_volume = _strip_volume_suffix(stripped_title)
    volume_index = volume_index if volume_index is not None else suffix_volume
    if not stripped_title or _is_volume_only(stem):
        parent = path.parent.name
        parent_identity = _bracket_identity(parent, allow_volume_range=True)
        if parent_identity:
            stripped_title, author = parent_identity
        else:
            stripped_title, _parent_volume = _strip_volume_suffix(_clean_title(parent))
            author = UNKNOWN_AUTHOR
    else:
        author = UNKNOWN_AUTHOR

    return BookIdentity(
        title=stripped_title or stem or path.name,
        author=author,
        volume_index=volume_index,
        source="regex",
        confidence=0.62 if author == UNKNOWN_AUTHOR else 0.82,
        logical_path=logical_path,
    )


def _ai_config(db: Session) -> tuple[dict[str, str] | None, str | None]:
    runtime_config = metadata_provider_runtime_config(db, "ai")
    if runtime_config is None:
        return None, None
    config = {
        "base_url": str(runtime_config.get("baseUrl") or "").strip().rstrip("/"),
        "api_key": str(runtime_config.get("apiKey") or "").strip(),
        "model": str(runtime_config.get("model") or "").strip(),
    }
    if all(config.values()):
        return config, None
    return (
        None,
        "AI identity recognition is enabled but its base URL, model, or API key is missing",
    )


def _recognize_with_ai(logical_path: str, config: dict[str, str]) -> BookIdentity:
    body = {
        "model": config["model"],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是图书文件身份解析器。只根据用户给出的相对路径和文件名识别作品标题、作者和卷号。"
                    "不要读取或推断正文内容，不要编造作者。只返回 JSON："
                    '{"title":"作品标题","author":"作者或空字符串","volumeIndex":数字或null,"confidence":0到1。}'
                ),
            },
            {"role": "user", "content": logical_path},
        ],
    }
    request = UrlRequest(
        f"{config['base_url']}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = _ai_content(payload)
    title = _clean_title(str(content.get("title") or ""))
    if not title:
        raise ValueError("AI returned an empty title")
    author = _clean_author(str(content.get("author") or "")) or UNKNOWN_AUTHOR
    volume_index = _number_or_none(content.get("volumeIndex"))
    try:
        confidence = min(1.0, max(0.0, float(content.get("confidence", 0.8))))
    except (TypeError, ValueError):
        confidence = 0.8
    return BookIdentity(
        title=title,
        author=author,
        volume_index=volume_index,
        source="ai",
        confidence=confidence,
        logical_path=logical_path,
    )


def _ai_identity_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, HTTPError) and exc.code == 402:
        return (
            "AI_BILLING_REQUIRED",
            "AI 标题识别失败：AI 服务计费不可用，请检查服务商套餐、账户余额和计费设置",
        )
    return "AI_REQUEST_FAILED", f"AI identity recognition failed: {exc}"


def _ai_content(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("AI response is not an object")
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            cleaned = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I
            )
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
    if all(key in payload for key in ["title", "author"]):
        return payload
    raise ValueError("AI response does not contain identity JSON")


def _bracket_identity(value: str, allow_volume_range: bool) -> tuple[str, str] | None:
    raw_parts = re.findall(r"\[([^\]]+)\]", value)
    if len(raw_parts) < 2 or not re.fullmatch(r"\s*(?:\[[^\]]+\]\s*)+", value):
        return None
    if len(raw_parts) > 2 and not allow_volume_range:
        return None
    if len(raw_parts) > 2 and not _looks_like_volume_range(raw_parts[2]):
        return None
    title = _clean_title(raw_parts[0])
    author = _clean_author(raw_parts[1])
    return (title, author or UNKNOWN_AUTHOR) if title else None


def parse_bracketed_series_identity(
    folder_name: str, filename: str | None = None
) -> tuple[str, str] | None:
    """Resolve title/author from an all-bracket series directory.

    Besides the conventional ``[title][author][Vol.01-Vol.10]`` layout, some
    comic sources put the author first and insert publisher/source tags before
    the volume range.  In that case the filename is used only to determine
    which of the first two directory parts is the title; the other part is the
    author.  ``[latin alias][localized title][author][volume range]`` is also
    supported when a volume-only filename cannot corroborate the title.
    Arbitrary tag-only directories are not guessed.
    """
    raw_parts = re.findall(r"\[([^\]]+)\]", folder_name)
    if len(raw_parts) < 2 or not re.fullmatch(r"\s*(?:\[[^\]]+\]\s*)+", folder_name):
        return None
    parts = [_clean_title(part) for part in raw_parts]
    if not parts[0] or not parts[1]:
        return None

    filename_title = _filename_series_title(filename) if filename else ""
    filename_key = normalize_identity_part(filename_title)
    first_keys = [normalize_identity_part(parts[0]), normalize_identity_part(parts[1])]
    if filename_key:
        for title_index, part_key in enumerate(first_keys):
            if filename_key == part_key:
                author_index = 1 - title_index
                author = _clean_author(parts[author_index]) or UNKNOWN_AUTHOR
                return parts[title_index], author

    volume_range_indexes = [
        index
        for index, part in enumerate(raw_parts)
        if index >= 2 and _looks_like_volume_range(part)
    ]
    if (
        len(parts) >= 4
        and volume_range_indexes
        and volume_range_indexes[0] == 3
        and _looks_like_latin_alias(parts[0])
        and not _looks_like_latin_alias(parts[1])
        and not _looks_like_latin_alias(parts[2])
    ):
        author = _clean_author(parts[2]) or UNKNOWN_AUTHOR
        return parts[1], author

    if len(parts) == 2 or (
        len(raw_parts) > 2 and _looks_like_volume_range(raw_parts[2])
    ):
        author = _clean_author(parts[1]) or UNKNOWN_AUTHOR
        return parts[0], author
    return None


def _looks_like_latin_alias(value: str) -> bool:
    cleaned = unicodedata.normalize("NFKC", value).strip()
    return bool(
        re.fullmatch(r"[A-Z][A-Z0-9 ._'’&:+-]*", cleaned, re.I)
        and re.search(r"[A-Z]", cleaned, re.I)
    )


def _filename_series_title(filename: str) -> str:
    stem = _clean_title(filename)
    without_volume, _volume = _strip_volume_suffix(stem)
    title = re.split(r"\s+\[", without_volume, maxsplit=1)[0]
    return _clean_title(title)


def _looks_like_volume_range(value: str) -> bool:
    return bool(
        re.search(
            r"(?:vol(?:ume)?\.?|v|第)?\s*\d+(?:\.\d+)?\s*[-~至到]\s*(?:vol(?:ume)?\.?|v|第)?\s*\d+(?:\.\d+)?",
            value,
            re.I,
        )
    )


def _download_filename_identity(value: str) -> tuple[str, str] | None:
    """Parse ``title (author) (download-source.example)`` filenames.

    A download-source suffix is deliberately required so ordinary titles
    containing parentheses are left to the normal fallback rules.  Known
    sources such as ``(Z-Library)`` and numeric copy suffixes such as
    ``(2)`` directly after a source are also accepted, so
    ``Title (Author) (Z-Library) (2)`` resolves to ``Title``/``Author``.
    """
    value = _clean_title(value)
    stripped = _strip_download_suffixes(value)
    if stripped == value:
        return None

    raw_title, raw_author = _split_trailing_parenthetical(stripped)
    author = _clean_author(raw_author or "")
    if not raw_title or not author or _looks_like_download_source(author):
        return None

    title = _clean_download_title(raw_title)
    return (title, author) if title else None


def _parenthesized_year_author_identity(
    value: str,
) -> tuple[str, str] | None:
    """Parse ``Title-(Author)-YYYY`` filenames.

    This covers compact bookstore-style names such as
    ``股票投资要义-(胡斐)-2015`` where the author appears in parentheses
    between the title and the edition year.  The trailing four-digit year is
    dropped, never treated as a volume index.
    """
    match = re.fullmatch(
        r"^(.*?)\s*-\s*\(([^()（）\-_]+)\)\s*-\s*(\d{4})\s*$",
        value.strip(),
    )
    if not match:
        return None
    title = _clean_title(match.group(1))
    author = _clean_author(match.group(2))
    if not title or not author:
        return None
    return title, author


def _strip_download_suffixes(value: str) -> str:
    """Remove trailing download-source and copy-number parentheticals.

    A plain numeric parenthetical is only removed when a download-source
    suffix was already stripped, so real volume numbers such as
    ``Title (1)`` are preserved.  ``Title (Author) (Z-Library) (2)``
    therefore collapses to ``Title (Author)``.
    """
    cleaned = value.rstrip()
    stripped_any = False
    while True:
        without, suffix = _split_trailing_parenthetical(cleaned)
        if suffix is None:
            return cleaned
        is_source = _looks_like_download_source(suffix) or _looks_like_known_source(
            suffix
        )
        is_copy = bool(re.fullmatch(r"\d+", suffix.strip())) and (
            stripped_any or _contains_download_source(without)
        )
        if not (is_source or is_copy):
            return cleaned
        cleaned = without
        stripped_any = True


def _contains_download_source(value: str) -> bool:
    """Return whether any trailing parenthetical is a download source."""

    cleaned = value.rstrip()
    while True:
        without, suffix = _split_trailing_parenthetical(cleaned)
        if suffix is None:
            return False
        if _looks_like_download_source(suffix) or _looks_like_known_source(suffix):
            return True
        cleaned = without


def _looks_like_known_source(value: str) -> bool:
    """Recognize well-known ebook-download source labels.

    Domain-style suffixes such as ``z-lib.sk`` are already handled by
    ``_looks_like_download_source``; this covers the plain labels that are
    common in the wild, including the hyphenated ``(Z-Library)``.
    """
    cleaned = re.sub(r"[\s_]+", " ", value.strip()).strip()
    return bool(
        re.fullmatch(
            r"(?:Z[- ]?Library|Z[- ]?Lib(?:rary)?|libgen(?:\.\w+)?|"
            r"Library Genesis|bookzz|b-ok(?:\.\w+)?|Anna's Archive|"
            r"oceanofpdf|archive\.org|overdrive)",
            cleaned,
            flags=re.IGNORECASE,
        )
    )


def _split_trailing_parenthetical(value: str) -> tuple[str, str | None]:
    cleaned = value.rstrip()
    if not cleaned or cleaned[-1] not in ")）":
        return cleaned, None
    closing = cleaned[-1]
    opening = "(" if closing == ")" else "（"
    depth = 0
    for index in range(len(cleaned) - 1, -1, -1):
        char = cleaned[index]
        if char == closing:
            depth += 1
        elif char == opening:
            depth -= 1
            if depth == 0:
                return cleaned[:index].rstrip(), cleaned[index + 1 : -1].strip()
    return cleaned, None


def _looks_like_download_source(value: str) -> bool:
    parts = [part.strip() for part in re.split(r"[_,，、\s]+", value) if part.strip()]
    if not parts:
        return False
    # Dotted personal names such as ``E.B.White`` or ``T.S.Eliot`` must not be
    # mistaken for download hostnames.  Real download hostnames are essentially
    # lowercase, whereas a personal dotted name has an uppercase-initialised
    # token (``E``/``B``/``White``).  A part that still matches an internet
    # domain and has no such token is treated as a source hostname.
    for part in parts:
        if not _DOWNLOAD_DOMAIN_RE.fullmatch(part):
            return False
        tokens = re.split(r"[.\-]", part)
        if any(token and token[0:1].isupper() for token in tokens):
            return False
    return bool(parts)


def _clean_download_title(value: str) -> str:
    cleaned = value.strip()
    while True:
        prefix, note = _split_trailing_parenthetical(cleaned)
        if not note or not _DOWNLOAD_EDITION_MARKER_RE.search(note):
            break
        cleaned = prefix
    cleaned = _clean_title(cleaned)
    book_title = _BOOK_TITLE_BRACKETS_RE.fullmatch(cleaned)
    return _clean_title(book_title.group(1)) if book_title else cleaned


def _has_bare_copy_suffix(value: str) -> bool:
    """Return whether a trailing ``(2)``-style copy number is attached.

    File managers and OS sync append a parenthetical counter to duplicate
    files/folders such as ``0022_0(1).mp3``; these must not be read as volume
    numbers.  A parenthetical preceded by whitespace (``Title (1)``) is kept as
    a genuine standalone volume number.
    """
    return _COPY_SUFFIX_RE.search(value) is not None


def _strip_copy_parenthetical(value: str) -> str:
    """Remove a trailing space-separated copy number such as ``(2)``.

    After an explicit volume marker has been removed, a residual parenthetical
    number is almost always a duplicate-folder counter (``化学 第4册 (2)``)
    rather than part of the title.
    """
    return _COPY_PARENTHETICAL_RE.sub("", value)


def _volume_index(value: str) -> float | None:
    explicit_volume = split_explicit_volume(value)
    if explicit_volume is not None:
        return explicit_volume[1]
    if contains_explicit_volume_range(value):
        return None
    for pattern in [
        r"(?:^|\s)(?:vol(?:ume)?\.?|v)\s*(\d+(?:\.\d+)?)\s*$",
        r"(?:^|\s)第\s*(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)\s*$",
        r"(?:^|\s)(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)\s*$",
    ]:
        match = re.search(pattern, value, re.I)
        if match:
            return float(match.group(1))
    if _has_bare_copy_suffix(value):
        return None
    numeric_fallback = split_numeric_volume_fallback(value)
    if numeric_fallback is not None:
        return numeric_fallback[1]
    return None


def _strip_volume_suffix(value: str) -> tuple[str, float | None]:
    cleaned = value.strip()
    explicit_volume = split_explicit_volume(cleaned)
    if explicit_volume is not None:
        title, volume_index = explicit_volume
        return _clean_title(_strip_copy_parenthetical(title)), volume_index
    if contains_explicit_volume_range(cleaned):
        return cleaned, None
    patterns = [
        r"^(.*?)\s*(?:vol(?:ume)?\.?|v)\s*(\d+(?:\.\d+)?)$",
        r"^(.*?)\s*第\s*(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"^(.*?)\s+(\d+(?:\.\d+)?)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned, re.I)
        if match and match.group(1).strip():
            return _clean_title(match.group(1)), float(match.group(2))
    if _has_bare_copy_suffix(cleaned):
        return cleaned, None
    numeric_fallback = split_numeric_volume_fallback(cleaned)
    if numeric_fallback is not None:
        title, volume_index = numeric_fallback
        return _clean_title(title), volume_index
    return cleaned, None


def _directory_title_and_volume(value: str) -> tuple[str, float | None]:
    if not (
        re.search(r"(?:vol(?:ume)?\.?|v)\s*\d+(?:\.\d+)?\s*$", value, re.I)
        or re.search(r"第?\s*\d+(?:\.\d+)?\s*(?:卷|冊|册|集)\s*$", value, re.I)
        or re.search(r"\s+\d+(?:\.\d+)?\s*$", value)
    ):
        return _clean_title(value), None
    return _strip_volume_suffix(_clean_title(value))


def _grade_directory_volume(value: str) -> float | None:
    """Return a grade volume for directories such as ``G1``..``G6``.

    Textbook collections (e.g. Wonders) organize files under grade folders.
    The grade number is used as the volume index so the collection can be
    grouped while the file keeps its own title.
    """
    match = re.fullmatch(r"G(\d{1,2})", value.strip(), re.IGNORECASE)
    if not match:
        return None
    volume_index = float(match.group(1))
    return volume_index if volume_index > 0 else None


def _is_volume_only(value: str) -> bool:
    return bool(
        _VOLUME_ONLY_LATIN_RE.fullmatch(value)
        or _VOLUME_ONLY_CJK_RE.fullmatch(value)
    )


def _clean_title(value: str) -> str:
    # Preserve display punctuation. NFKC is applied only to the identity key.
    cleaned = _TRAILING_EBOOK_EXT_RE.sub("", value)
    return _WS_COLLAPSE_RE.sub(" ", cleaned.replace("_", " ")).strip(" ._-")


def _clean_author(value: str) -> str:
    cleaned = _clean_title(value)
    # Keep only the first author when several are listed with a semicolon
    # (``Zvi Bodie;Alex Kane;Alan Marcus`` or ``（日）川胜博著；吴宗汉，彭双潮译``).
    cleaned = cleaned.split(";", 1)[0].split("；", 1)[0]
    # Strip a leading nationality parenthetical such as ``（日）``.
    cleaned = _LEADING_NATIONALITY_RE.sub("", cleaned)
    # Strip trailing translator/editor/author role words (longest first so
    # ``编著`` collapses entirely rather than leaving ``编``).
    cleaned = _TRAILING_ROLE_WORD_RE.sub("", cleaned)
    # Drop ``etc.`` tails left by download sites.
    cleaned = _ETC_TAIL_RE.sub("", cleaned)
    # Strip any remaining leading parenthetical.
    cleaned = _LEADING_PARENTHETICAL_RE.sub("", cleaned)
    return cleaned.strip()


def _number_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
