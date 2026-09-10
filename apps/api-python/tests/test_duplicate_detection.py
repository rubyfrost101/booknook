"""Tests for the four-tier fuzzy duplicate-work detection."""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.library.application.duplicate_detection import (
    build_duplicate_groups,
    duplicate_title_key,
    work_records_from_rows,
)
from app.services.book_identity import UNKNOWN_AUTHOR, normalize_identity_part


def _rec(
    work_id: str,
    title: str,
    author: str = "",
    *,
    ntitle: str | None = None,
    nauthor: str | None = None,
) -> SimpleNamespace:
    normalized_title = (
        ntitle if ntitle is not None else normalize_identity_part(title)
    )
    normalized_author = (
        nauthor
        if nauthor is not None
        else normalize_identity_part(author or UNKNOWN_AUTHOR)
    )
    return SimpleNamespace(
        id=work_id,
        title=title,
        author=author,
        normalized_title=normalized_title,
        normalized_author=normalized_author,
    )


def _groups(records: list[SimpleNamespace]) -> list[dict]:
    return build_duplicate_groups(work_records_from_rows(records))


# --- Tier 1: exact normalized title + author ---------------------------------


def test_tier1_exact_title_and_author_match() -> None:
    groups = _groups(
        [
            _rec("a", "星海列车", "林川"),
            _rec("b", "星海列车", "林川"),
            _rec("c", "另外的书", "王五"),
        ]
    )
    assert len(groups) == 1
    assert set(groups[0]["workIds"]) == {"a", "b"}
    assert groups[0]["confidence"] == 0.98


def test_tier1_requires_same_author() -> None:
    groups = _groups(
        [
            _rec("a", "星海列车", "林川"),
            _rec("b", "星海列车", "王五"),
        ]
    )
    # 标题相同但作者不同：不进入 Tier 1，由 Tier 2 处理
    assert len(groups) == 1
    assert groups[0]["confidence"] == 0.82


# --- Tier 3: edition/translation/source markers stripped ---------------------


def test_tier3_edition_marker_stripped() -> None:
    groups = _groups(
        [
            _rec(
                "a",
                "Lehninger Principles of Biochemistry, 8th Edition (David L.N)",
            ),
            _rec(
                "b",
                "Lehninger Principles of Biochemistry, th Edition (David L.N)",
            ),
        ]
    )
    assert len(groups) == 1
    assert set(groups[0]["workIds"]) == {"a", "b"}
    assert groups[0]["confidence"] == 0.90


def test_tier3_zlibrary_and_author_parenthesis_stripped() -> None:
    groups = _groups(
        [
            _rec("a", "真需求 (梁宁) (Z-Library)"),
            _rec("b", "真需求"),
        ]
    )
    assert len(groups) == 1
    assert set(groups[0]["workIds"]) == {"a", "b"}
    assert groups[0]["confidence"] == 0.90


def test_tier3_pure_number_parenthesis_is_volume_not_edition() -> None:
    # (2)/(5) 是分册卷号，不得因剥离括号而误判为同一本
    groups = _groups(
        [
            _rec("a", "数理化自学丛书第2版 化学 (2)"),
            _rec("b", "数理化自学丛书第2版 化学 (5)"),
        ]
    )
    assert len(groups) == 0


def test_tier3_trailing_edition_marker_only() -> None:
    # 「第2版」位于标题结尾时剥离；位于句中（后跟分册名）时保留
    groups = _groups(
        [
            _rec("a", "经济学原理 第2版"),
            _rec("b", "经济学原理"),
        ]
    )
    assert len(groups) == 1
    assert groups[0]["confidence"] == 0.90


# --- Tier 2: same title, different author records ----------------------------


def test_tier2_same_title_different_author() -> None:
    groups = _groups(
        [
            _rec("a", "哈利波特与魔法石", "罗琳"),
            _rec("b", "哈利波特与魔法石", "J.K.罗琳"),
        ]
    )
    assert len(groups) == 1
    assert set(groups[0]["workIds"]) == {"a", "b"}
    assert groups[0]["confidence"] == 0.82


def test_tier2_short_generic_title_skipped() -> None:
    # 「数学」等 2-4 字通用书名极易误报，长度不足时不进入 Tier 2
    groups = _groups(
        [
            _rec("a", "数学", "张三"),
            _rec("b", "数学", "李四"),
        ]
    )
    assert len(groups) == 0


# --- Tier 4a: high title similarity ------------------------------------------


def test_tier4_copy_suffix_similarity() -> None:
    groups = _groups(
        [
            _rec("a", "Economics in One Lesson"),
            _rec("b", "Economics in One Lesson (1)"),
        ]
    )
    assert len(groups) == 1
    assert set(groups[0]["workIds"]) == {"a", "b"}
    assert groups[0]["confidence"] == 0.72


def test_tier4_different_volume_numbers_not_duplicates() -> None:
    groups = _groups(
        [
            _rec("a", "Harry Potter 1 - Harry Potter and the Goblet of Fire"),
            _rec("b", "Harry Potter 2 - Harry Potter and the Chamber of Secrets"),
        ]
    )
    assert len(groups) == 0


def test_tier4_similarity_requires_same_author_bucket() -> None:
    groups = _groups(
        [
            _rec("a", "三体 全集", "刘慈欣"),
            _rec("b", "三体 全本", "另一个作者"),
        ]
    )
    assert len(groups) == 0


# --- Tier 4b: shared core book-title fragment --------------------------------


def test_tier4b_different_translations_share_core_title() -> None:
    groups = _groups(
        [
            _rec(
                "a",
                "马尔克斯-霍乱时期的爱情[哥伦比亚]马尔克斯.蒋宗曹、姜风光译.黑龙江人民出版社(1987)",
            ),
            _rec("b", "霍乱时期的爱情-马尔克斯.徐鹤林、魏民译.漓江出版社(1987)"),
        ]
    )
    assert len(groups) == 1
    assert set(groups[0]["workIds"]) == {"a", "b"}
    assert groups[0]["confidence"] == 0.70


def test_tier4b_publisher_fragment_is_not_core_title() -> None:
    # 「人民文学出版社」是出版社片段，不得作为书名核心造成跨书误报
    groups = _groups(
        [
            _rec("a", "三国演义-人民文学出版社"),
            _rec("b", "红楼梦-人民文学出版社"),
        ]
    )
    assert len(groups) == 0


# --- dedup / precedence ------------------------------------------------------


def test_work_claimed_only_once_by_highest_tier() -> None:
    # 三本同标题同作者：全部进入 Tier 1 单组，不重复出现在模糊组
    groups = _groups(
        [
            _rec("a", "星海列车", "林川"),
            _rec("b", "星海列车", "林川"),
            _rec("c", "星海列车", "林川"),
        ]
    )
    assert len(groups) == 1
    assert set(groups[0]["workIds"]) == {"a", "b", "c"}
    assert groups[0]["confidence"] == 0.98


def test_duplicate_title_key_helpers() -> None:
    assert duplicate_title_key("Lehninger Principles of Biochemistry, 8th Edition") == (
        "lehningerprinciplesofbiochemistry"
    )
    assert duplicate_title_key("真需求 (梁宁) (Z-Library)") == "真需求"
    # 纯数字括号保留（卷号语义）
    assert duplicate_title_key("数理化自学丛书第2版 化学 (2)") == (
        "数理化自学丛书化学2"
    )
