"""Fuzzy duplicate-work detection across four confidence tiers.

Tier 1 (0.98)  exact normalized title + author
Tier 3 (0.90)  equal title after stripping edition/translation/source markers
Tier 2 (0.82)  equal normalized title but different author records
Tier 4 (0.72)  high title similarity (copies with suffix numbers)
Tier 4 (0.70)  shared core book-title fragment (different translations)

A work is claimed by the highest-confidence tier it qualifies for, so each
work appears in at most one duplicate group.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.services.book_identity import UNKNOWN_AUTHOR, normalize_identity_part

# --- Tier 3: duplicate-title key ---------------------------------------------

# 第N版：句中与结尾都剥离（不同版次属于同一本书）。分册卷号由尾部纯数字括号
# （(2)/(5)）承担，不会被误删，因此剥离第N版不会把不同分册并为一本。
_EDITION_NUMBER_RE = re.compile(r"第\s*[一二三四五六七八九十百\d]{0,3}\s*版")

# 版本 / 来源标记（8th Edition、修订版、Z-Library 等）：仅匹配标题结尾的标记。
# 「丛书 / 系列 / 全集」常是丛书名的一部分（如「数理化自学丛书」），只允许在
# 结尾剥离，避免把丛书名拆坏。
_EDITION_MARKER_SUFFIX_RE = re.compile(
    r"(?:"
    r"\b(?:\d+\s*)?(?:st|nd|rd|th)\s*editions?\b"  # 8th Edition / th Edition
    r"|修订版|增订版|典藏版|珍藏版|精装版|平装版|纪念版|影印版"
    r"|扫描版|高清版|完整版|双语版|中英对照版|全译本|节译本|简体版|繁体版"
    r"|全集|套装|合集|典藏集|文库|丛书|系列"
    r"|z\s*[-–—]?\s*library"  # Z-Library 来源标记
    r")\s*$",
    re.IGNORECASE,
)

# 尾部括号元数据：(Z-Library)、(梁宁)、(1987)。括号内为纯数字时保留（如
# 「数理化自学丛书第2版 化学 (2)」的卷号），年份 (1987) 是发布年不参与去重键。
_TRAILING_PAREN_RE = re.compile(r"[\s　]*[\(（][^)）]*[^)）\d][^)）]*[\)）]\s*$")

# 尾部括号纯数字：浏览器重复下载的副本序号，也常是分册卷号（数理化 (2)/(5)）。
# 两条记录都带且数字不同时视为不同分册，Tier 4a 跳过。
_TRAILING_NUMBER_PAREN_RE = re.compile(r"[\s　]*[\(（](\d{1,3})[\)）]\s*$")

# --- Tier 4b: core-title extraction ------------------------------------------

# 「哥伦比亚马尔克斯」「黑龙江人民出版社」「蒋宗曹、姜风光译」这类片段不是
# 书名核心，按国家名 / 出版 / 译者后缀过滤。
_COUNTRY_NAMES = frozenset(
    {
        "中国", "日本", "美国", "英国", "法国", "德国", "俄罗斯", "苏联",
        "韩国", "朝鲜", "印度", "意大利", "西班牙", "葡萄牙", "阿根廷",
        "墨西哥", "哥伦比亚", "智利", "秘鲁", "古巴", "加拿大", "澳大利亚",
        "巴西", "荷兰", "瑞士", "瑞典", "奥地利", "爱尔兰", "希腊",
    }
)

_CORE_TITLE_SUFFIX_WORDS = frozenset(
    {
        "出版社", "书局", "文库", "丛书", "译", "著", "编", "整理", "编写",
        "编译", "主编", "原著", "译者", "译者简介",
    }
)

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_TITLE_SEPARATOR_RE = re.compile(r"[\s\-—–.。·、，,;；:：()（）\[\]【】《》“”]+")

# --- Tier 4a: similarity guards ----------------------------------------------

# 卷标记：前置数字（1984 / Harry Potter 1）、第N卷部册集、vol/book/part N。
# 两个作品都带卷标记且卷号不同 → 是系列的不同卷，不是重复。
_LEADING_VOLUME_RE = re.compile(r"^\d+\b|第[一二三四五六七八九十百\d]+[卷部册集]")
_VOLUME_TOKEN_RE = re.compile(
    r"\b(?:vol\.?|volume|book|part)\s*[一二三四五六七八九十百\d]+", re.IGNORECASE
)

_SIMILARITY_THRESHOLD = 0.85
_MIN_TIER2_TITLE = 4  # 同标题异作者对短通用名（数学/英语）误报太高，4 字以上才进入
_MIN_TIER3_KEY = 3
_MIN_TIER4_TITLE = 4
_MAX_SIMILARITY_BLOCK = 300  # 相似度配对的安全上限，超出则跳过该块

_UNKNOWN_AUTHOR_KEY = normalize_identity_part(UNKNOWN_AUTHOR)


@dataclass(frozen=True)
class _WorkRecord:
    id: str
    title: str
    author: str
    ntitle: str
    nauthor: str


def _author_bucket(nauthor: str) -> str:
    """把空作者与「未知作者」归入同一桶，相似度规则对两者一视同仁。"""
    if not nauthor or nauthor == _UNKNOWN_AUTHOR_KEY:
        return ""
    return nauthor


def duplicate_title_key(title: str) -> str:
    """NFKC 规范化 + 剥离版本/翻译/来源标记，用于 Tier 3 去重键。"""
    value = str(title or "").strip()
    for _ in range(2):  # 括号元数据与版本标记可能交替出现（如 (Z-Library) 在内层）
        while True:
            match = _TRAILING_PAREN_RE.search(value)
            if match is None:
                break
            value = value[: match.start()].strip()
        value = _EDITION_NUMBER_RE.sub("", value).strip()
        value = _EDITION_MARKER_SUFFIX_RE.sub("", value).strip()
    return normalize_identity_part(value)


def _core_title_candidates(title: str) -> frozenset[str]:
    """从原始标题中提取疑似书名核心的连续中文字段。"""
    parts = _TITLE_SEPARATOR_RE.split(str(title or ""))
    candidates: set[str] = set()
    for part in parts:
        # 先剥离第N版，避免「第2版」被数字拆开后残留「丛书第」误当核心
        cleaned = "".join(_CJK_RUN_RE.findall(_EDITION_NUMBER_RE.sub("", part)))
        if len(cleaned) < 5:
            continue
        if any(cleaned.endswith(word) for word in _CORE_TITLE_SUFFIX_WORDS):
            continue
        if any(country in cleaned for country in _COUNTRY_NAMES):
            continue
        candidates.add(cleaned)
    return frozenset(candidates)


def _volume_marker(ntitle: str) -> str | None:
    match = _LEADING_VOLUME_RE.search(ntitle)
    if match is not None:
        return match.group(0)
    match = _VOLUME_TOKEN_RE.search(ntitle)
    if match is not None:
        return match.group(0)
    return None


def _trailing_number_paren(title: str) -> int | None:
    """尾部纯数字括号的数值：浏览器副本序号或分册卷号（数理化 (2)/(5)）。"""
    match = _TRAILING_NUMBER_PAREN_RE.search(str(title or ""))
    if match is None:
        return None
    return int(match.group(1))


def _similarity_ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _group_id(index: int, group_key: str) -> str:
    digest = hashlib.sha1(group_key.encode()).hexdigest()[:12]
    return f"duplicate_{index}_{digest}"


def build_duplicate_groups(
    records: list[_WorkRecord],
) -> list[dict[str, Any]]:
    """返回四层查重合并后的分组列表（置信度从高到低）。"""
    groups: list[dict[str, Any]] = []
    claimed: set[str] = set()

    def remaining() -> list[_WorkRecord]:
        return [record for record in records if record.id not in claimed]

    def emit(work_ids: list[str], confidence: float, reasons: list[str]) -> None:
        ordered = [work_id for work_id in work_ids if work_id not in claimed]
        if len(ordered) < 2:
            return
        claimed.update(ordered)
        groups.append(
            {
                "id": _group_id(len(groups), ":".join(ordered)),
                "confidence": confidence,
                "reasons": reasons,
                "workIds": ordered,
            }
        )

    # --- Tier 1: 标题 + 作者规范化后完全相同 --------------------------------
    by_identity: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in records:
        by_identity[(record.ntitle, record.nauthor)].append(record.id)
    for work_ids in by_identity.values():
        if len(work_ids) < 2:
            continue
        emit(
            work_ids,
            0.98,
            ["标题与作者规范化后相同"],
        )

    # --- Tier 3: 去除版本/翻译/来源标记后标题相同（normalized 标题不同） ----
    by_key: dict[str, list[_WorkRecord]] = defaultdict(list)
    for record in remaining():
        by_key[duplicate_title_key(record.title)].append(record)
    for key, bucket in by_key.items():
        if len(bucket) < 2 or len(key) < _MIN_TIER3_KEY:
            continue
        distinct_titles = {record.ntitle for record in bucket}
        if len(distinct_titles) < 2:
            continue
        emit(
            [record.id for record in bucket],
            0.90,
            ["去除版本/翻译/来源标记后标题相同，可能为同一本书的不同版本"],
        )

    # --- Tier 2: 标题相同、作者记录不同 -------------------------------------
    by_title: dict[str, list[_WorkRecord]] = defaultdict(list)
    for record in remaining():
        by_title[record.ntitle].append(record)
    for title, bucket in by_title.items():
        if len(bucket) < 2 or len(title) < _MIN_TIER2_TITLE:
            continue
        distinct_authors = {record.nauthor for record in bucket}
        if len(distinct_authors) < 2:
            continue
        emit(
            [record.id for record in bucket],
            0.82,
            ["标题相同但作者记录不同，可能为不同翻译或版本"],
        )

    # --- Tier 4a: 标题高度相似（同作者桶）-----------------------------------
    by_author_bucket: dict[str, dict[str, list[_WorkRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in remaining():
        bucket_key = _author_bucket(record.nauthor)
        prefix = record.ntitle[:2] or record.ntitle[:1] or ""
        by_author_bucket[bucket_key][prefix].append(record)
    for bucket_map in by_author_bucket.values():
        for block in bucket_map.values():
            if len(block) < 2 or len(block) > _MAX_SIMILARITY_BLOCK:
                continue
            parent = {record.id: record.id for record in block}

            def find(work_id: str) -> str:
                root = work_id
                while parent[root] != root:
                    root = parent[root]
                while parent[work_id] != work_id:
                    next_id = parent[work_id]
                    parent[work_id] = root
                    work_id = next_id
                return root

            def union(left: str, right: str) -> None:
                left_root, right_root = find(left), find(right)
                if left_root != right_root:
                    parent[right_root] = left_root

            for index, left in enumerate(block):
                if left.id in claimed:
                    continue
                for right in block[index + 1 :]:
                    if right.id in claimed:
                        continue
                    shorter = min(left.ntitle, right.ntitle, key=len)
                    if len(shorter) < _MIN_TIER4_TITLE:
                        continue
                    left_marker = _volume_marker(left.ntitle)
                    right_marker = _volume_marker(right.ntitle)
                    if (
                        left_marker is not None
                        and right_marker is not None
                        and left_marker != right_marker
                    ):
                        continue
                    left_copy = _trailing_number_paren(left.title)
                    right_copy = _trailing_number_paren(right.title)
                    if (
                        left_copy is not None
                        and right_copy is not None
                        and left_copy != right_copy
                    ):
                        # 尾部数字括号不同 → 是不同分册（数理化 (2)/(5)），非重复
                        continue
                    if _similarity_ratio(left.ntitle, right.ntitle) >= _SIMILARITY_THRESHOLD:
                        union(left.id, right.id)
            components: dict[str, list[str]] = defaultdict(list)
            for record in block:
                components[find(record.id)].append(record.id)
            for component in components.values():
                emit(
                    list(dict.fromkeys(component)),
                    0.72,
                    ["标题高度相似，可能为同一本书的重复文件或不同版本"],
                )

    # --- Tier 4b: 共享书名核心（不同翻译/版本）-------------------------------
    by_core: dict[str, list[_WorkRecord]] = defaultdict(list)
    for record in remaining():
        for core in _core_title_candidates(record.title):
            by_core[core].append(record)
    claimed_cores: set[str] = set()
    for core, bucket in by_core.items():
        if len(bucket) < 2 or core in claimed_cores:
            continue
        bucket = [record for record in bucket if record.id not in claimed]
        if len(bucket) < 2:
            continue
        # 一条记录可能命中多个核心，只归入第一个满足条件的分组
        for record in bucket:
            claimed_cores.update(_core_title_candidates(record.title))
        emit(
            [record.id for record in bucket],
            0.70,
            ["书名核心相同，可能为不同翻译或版本"],
        )

    return groups


def work_records_from_rows(rows: list[Any]) -> list[_WorkRecord]:
    """把 SELECT 行（id/title/author/normalized_title/normalized_author）转成记录。"""
    records = []
    for row in rows:
        title = str(row.title or "")
        author = str(row.author or "")
        records.append(
            _WorkRecord(
                id=str(row.id),
                title=title,
                author=author,
                ntitle=normalize_identity_part(
                    getattr(row, "normalized_title", None) or title
                ),
                nauthor=normalize_identity_part(
                    getattr(row, "normalized_author", None) or author
                ),
            )
        )
    return records
