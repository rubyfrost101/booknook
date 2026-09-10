from __future__ import annotations

import pytest

from app.modules.imports.application.book_categories import categorize_work_tags


@pytest.mark.parametrize(
    ("logical_path", "expected"),
    [
        # Textbook collections and their grade subfolders.
        ("/monitor/Wonders/G2/g2 vocabulary cards.pdf", ("小学生教材-Wonders",)),
        (
            "/monitor/Texas Journeys/Texas Journeys G4/reader.pdf",
            ("小学生教材-Journeys",),
        ),
        # Reference/popular-science series.
        ("/monitor/DK/Animal & Nature/x.pdf", ("DK百科",)),
        ("/monitor/DK/Others/x.pdf", ("DK百科",)),
        ("/monitor/National Geographic/Kids/x.pdf", ("科普",)),
        # English-learning resources.
        ("/monitor/A409 外刊精读/2023 TE 外刊精读/x.pdf", ("外刊精读",)),
        ("/monitor/21 Grammar in use/02 中级 第5版/x.mp3", ("英语语法",)),
        (
            "/monitor/A8049 英语扩句跟读训练/【基础篇】/x.mp3",
            ("英语教学资源",),
        ),
        (
            "/monitor/english/英语词源典故词典.pdf",
            ("英语学习",),
        ),
        # Audiobook/resource bundles inherit the umbrella tag and their series.
        (
            "/monitor/昂克英文所有资料分享【grammar in use 视频作者】"
            "/04 哈利波特全套电子版及有声书/Chapter 01.mp3",
            ("英语教学资源", "哈利波特"),
        ),
        # Middle-school textbooks: subject subfolders and generic fallback.
        ("/monitor/Glencoe/历史学/x.pdf", ("中学教材-历史",)),
        ("/monitor/Glencoe/生物学(BIOLOGY)/x.pdf", ("中学教材-生物",)),
        ("/monitor/Glencoe/Others/x.pdf", ("中学教材",)),
        # Computer science: bare CS segment and Chinese-named subfolders.
        ("/monitor/CS/深入理解计算机系统.pdf", ("计算机",)),
        ("/monitor/CS/25年计算机408考研/2025王道计算机网络.pdf", ("计算机",)),
        # History and graded readers.
        ("/monitor/史记/史记.pdf", ("历史",)),
        ("/monitor/资治通鉴/x.pdf", ("历史",)),
        ("/monitor/书虫/入门级上（10册）/x.pdf", ("分级读物",)),
        ("/monitor/My Weird School 1-21 - Dan Gutman/x.pdf", ("章节书",)),
        # Math/physics/chemistry self-study series.
        ("/monitor/数理化自学丛书-第二版/第二版化学/x.pdf", ("中学理科",)),
        (
            "/monitor/苏联十年制学校教材 数学1-5年级五本/数学 一年级.pdf",
            ("教材-苏联十年制",),
        ),
        # Children's non-fiction.
        ("/monitor/Children/可怕的科学 发威的火山.pdf", ("儿童读物",)),
    ],
)
def test_categorize_work_tags_from_directory(logical_path, expected):
    assert categorize_work_tags(logical_path) == expected


def test_categorize_work_tags_short_cs_needle_does_not_match_phonics():
    tags = categorize_work_tags("/monitor/Wonders/G1/Phonics/x.pdf")

    assert "计算机" not in tags
    assert "小学生教材-Wonders" in tags


def test_categorize_work_tags_uses_filename_keyword_fallback():
    tags = categorize_work_tags("/monitor/books/Eyewitness Oceans.pdf")

    assert tags == ("DK百科",)


def test_categorize_work_tags_residue_names_are_tagged_unorganized():
    tags = categorize_work_tags(
        "/monitor/Wonders/G2/New Folder With Items/x.mp3"
    )

    assert "未整理资源" in tags


def test_categorize_work_tags_merges_glencoe_subject_and_residue():
    tags = categorize_work_tags(
        "/monitor/Glencoe/物理(PHYSICS)/新建文件夹/x.pdf"
    )

    assert tags == ("中学教材-物理", "未整理资源")


def test_categorize_work_tags_empty_or_shallow_paths_return_nothing():
    assert categorize_work_tags(None) == ()
    assert categorize_work_tags("x.pdf") == ()
