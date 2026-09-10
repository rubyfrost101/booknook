"""Path-derived category tags for imported works.

The user's library is organized as textbook/resource collections whose
directory hierarchy is itself a taxonomy (``Wonders``, ``Texas Journeys``,
``Glencoe``, ``DK``, ``A409 外刊精读``, ...).  This module maps a file's
logical path (and, as a fallback, its filename) to a stable set of
``主分类-子分类`` tags attached to the imported work.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_DIRECTORY_TAG_RULES: tuple[tuple[str, str], ...] = (
    ("wonders", "小学生教材-Wonders"),
    ("texas journeys", "小学生教材-Journeys"),
    ("dk", "DK百科"),
    ("national geographic", "科普"),
    ("外刊精读", "外刊精读"),
    ("21 grammar in use", "英语语法"),
    ("昂克英文", "英语教学资源"),
    ("英语扩句跟读训练", "英语教学资源"),
    ("english", "英语学习"),
    ("数理化自学丛书", "中学理科"),
    ("史记", "历史"),
    ("资治通鉴", "历史"),
    ("书虫", "分级读物"),
    ("my weird school", "章节书"),
    ("哈利波特", "哈利波特"),
    ("children", "儿童读物"),
    ("苏联十年制学校教材", "教材-苏联十年制"),
    ("计算机", "计算机"),
)

# Glencoe is a middle-school textbook collection; the first subdirectory
# carries the subject, so the tag is more specific than a bare ``中学教材``.
_GLENCOE_SUBDIR_TAGS: tuple[tuple[str, str], ...] = (
    ("历史学", "中学教材-历史"),
    ("数学几何代数", "中学教材-数学"),
    ("经济学", "中学教材-经济"),
    ("科学", "中学教材-科学"),
    ("艺术", "中学教材-艺术"),
    ("生物学", "中学教材-生物"),
    ("物理", "中学教材-物理"),
    ("化学", "中学教材-化学"),
    ("政治", "中学教材-政治"),
)

# Filename keyword fallback, used only when the directory revealed nothing.
_FILENAME_TAG_RULES: tuple[tuple[str, str], ...] = (
    ("eyewitness", "DK百科"),
    ("economist", "外刊精读"),
    ("外刊", "外刊精读"),
    ("精读", "外刊精读"),
    ("harry potter", "哈利波特"),
    ("哈利波特", "哈利波特"),
    ("history", "历史"),
    ("历史", "历史"),
    ("物理", "中学理科"),
    ("化学", "中学理科"),
    ("biology", "中学理科"),
    ("journeys", "小学生教材-Journeys"),
    ("wonders", "小学生教材-Wonders"),
)

# Resource-site residue names (Windows copy artifacts, merged download
# bundles, renamed folders) are not real publications; they get their own
# tag so they stay out of the way in browsing/filtering.
_RESIDUE_NAMES: tuple[str, ...] = (
    "new folder with items",
    "merged-audio-units",
    "appendixes audio",
    "3-unit",
    "新建文件夹",
)

# A bare ``CS`` directory is a computer-science collection, but the short
# needle ``cs`` is also a substring of words such as ``phonics``; only match
# it when it is a whole path segment.
_CS_DIRECTORY_SEGMENT_RE = re.compile(r"(?:^| / )cs(?: / |$)", re.IGNORECASE)


def _glencoe_subdir_tag(dir_text: str) -> str | None:
    """Map a ``Glencoe/<subject>`` subdirectory to a subject tag."""
    if "glencoe" not in dir_text:
        return None
    for needle, tag in _GLENCOE_SUBDIR_TAGS:
        if needle in dir_text:
            return tag
    return "中学教材"


def categorize_work_tags(
    logical_path: str | None,
    *,
    title: str | None = None,
) -> tuple[str, ...]:
    """Return stable category tags derived from the file's directory path.

    Directory names carry most of the signal (``Wonders``, ``Glencoe/历史学``,
    ``A409 外刊精读``, ...); the filename provides a keyword fallback when
    the directory reveals nothing.  Known resource-site residue names are
    tagged ``未整理资源`` regardless of location.  Returned tags are unique
    and ordered.
    """
    if not logical_path:
        return ()
    parts = PurePosixPath(logical_path).parts
    if len(parts) < 2:
        return ()
    dir_text = " / ".join(parts[:-1]).casefold()
    filename_text = parts[-1].casefold()
    combined = f"{dir_text} / {filename_text} {title or ''}".casefold()

    tags: list[str] = []

    glencoe_tag = _glencoe_subdir_tag(dir_text)
    if glencoe_tag is not None:
        tags.append(glencoe_tag)
    else:
        for needle, tag in _DIRECTORY_TAG_RULES:
            if needle in dir_text:
                tags.append(tag)
        if _CS_DIRECTORY_SEGMENT_RE.search(dir_text):
            tags.append("计算机")

    if not tags:
        for needle, tag in _FILENAME_TAG_RULES:
            if needle in filename_text:
                tags.append(tag)

    if any(needle in combined for needle in _RESIDUE_NAMES):
        tags.append("未整理资源")

    return tuple(dict.fromkeys(tags))
