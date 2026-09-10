from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest
from sqlalchemy import select, text

from app.models.import_pipeline import Source
from app.services import book_identity
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    identity_merge_key,
    recognize_book_identity,
    recognize_book_identity_with_regex,
)
from app.services.metadata_provider_registry import list_metadata_providers


def _configure_ai_provider(db, *, enabled: bool = True, complete: bool = True) -> None:
    list_metadata_providers(db)
    source = db.scalar(
        select(Source).where(Source.kind == "metadata", Source.provider_type == "ai")
    )
    assert source is not None
    source.enabled = enabled
    source.config = json.dumps(
        {
            "baseUrl": "https://ai.example/v1",
            "apiKey": "secret",
            "model": "identity-model",
        }
        if complete
        else {}
    )
    db.commit()


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self._body


def test_regex_identity_prefers_nearest_bracketed_series_directory():
    identity = recognize_book_identity_with_regex(
        "小说/[辣妹因为惩罚游戏才向我这个边缘人告白][結石][Vol.01-Vol.10]/辣妹因为惩罚游戏才向我这个边缘人告白 09.epub"
    )

    assert identity.title == "辣妹因为惩罚游戏才向我这个边缘人告白"
    assert identity.author == "結石"
    assert identity.volume_index == 9
    assert identity.source == "regex"


@pytest.mark.parametrize(
    ("logical_path", "expected_title", "expected_author", "expected_volume"),
    [
        (
            "/monitor/comic/[柊裕一][鹰峰同学请穿上衣服][東立][Zero有水印][8未]/鹰峰同学请穿上衣服 [柊裕一][东立][扫图][繁中] Vol.08.zip",
            "鹰峰同学请穿上衣服",
            "柊裕一",
            8,
        ),
        (
            "/monitor/comic/[山本崇一朗][擅长捉弄的高木同学（境外版）][bili][Vol.01-Vol.20][完结]/擅长捉弄的高木同学（境外版） Vol.08.zip",
            "擅长捉弄的高木同学（境外版）",
            "山本崇一朗",
            8,
        ),
        (
            "/monitor/comic/[Chainsaw Man][电锯人][藤本タツキ][Vol.01-Vol.11]/VOL11.zip",
            "电锯人",
            "藤本タツキ",
            11,
        ),
    ],
)
def test_regex_identity_infers_author_first_tagged_comic_directories(
    logical_path, expected_title, expected_author, expected_volume
):
    identity = recognize_book_identity_with_regex(logical_path)

    assert (identity.title, identity.author, identity.volume_index) == (
        expected_title,
        expected_author,
        expected_volume,
    )
    assert identity.source == "regex"


@pytest.mark.parametrize(
    ("filename", "expected_volume"),
    [
        ("FX戦士久留美 (1).zip", 1),
        ("FX戦士久留美 [02].zip", 2),
        ("FX戦士久留美_003.zip", 3),
        ("004 FX戦士久留美.zip", 4),
    ],
)
def test_regex_identity_uses_standalone_number_as_volume_fallback(
    filename, expected_volume
):
    identity = recognize_book_identity_with_regex(
        "/monitor/comic/"
        "[FX戦士久留美][ですにゃん×荒酸だいすき][角川][Vol.01-Vol.05][未完]/"
        f"{filename}"
    )

    assert (identity.title, identity.author, identity.volume_index) == (
        "FX戦士久留美",
        "ですにゃん×荒酸だいすき",
        expected_volume,
    )
    assert identity.source == "regex"


@pytest.mark.parametrize(
    ("filename", "expected_volume"),
    [
        ("龙与猫之国.Vlo.1.册-穿越时空的木乃伊之眼.pdf", 1),
        ("怪物大师10冰封的时之轮.pdf", 10),
        ("作品前传12特别篇.pdf", 12),
    ],
)
def test_regex_identity_uses_short_number_at_any_filename_position(
    filename, expected_volume
):
    identity = recognize_book_identity_with_regex(f"comic/{filename}")

    assert identity.volume_index == expected_volume


@pytest.mark.parametrize("filename", ["作品2024版.zip", "作品123456特别篇.zip"])
def test_regex_identity_does_not_treat_long_attached_digits_as_volume(filename):
    identity = recognize_book_identity_with_regex(f"comic/{filename}")

    assert identity.volume_index is None


def test_regex_identity_ignores_short_numbers_in_download_source_suffix():
    identity = recognize_book_identity_with_regex(
        "白夜行_(东野圭吾)_(z-library.sk_1lib.sk_z-lib.sk).epub"
    )

    assert identity.volume_index is None


@pytest.mark.parametrize(
    ("filename", "expected_title", "expected_volume"),
    [
        ("第01卷大雄的恐龙.pdf", "大雄的恐龙", 1),
        ("大雄第02卷宇宙开拓史.pdf", "大雄宇宙开拓史", 2),
        ("大雄的魔界大冒险 第03卷.pdf", "大雄的魔界大冒险", 3),
        ("Vol.04 大雄的海底鬼岩城.pdf", "大雄的海底鬼岩城", 4),
        ("[東京卍復仇者(全彩版)]卷05.pdf", "[東京卍復仇者(全彩版)]", 5),
        ("册06 大雄的宇宙小战争.pdf", "大雄的宇宙小战争", 6),
        ("大雄集07铁人兵团.pdf", "大雄铁人兵团", 7),
        ("大雄与龙骑士 巻08.pdf", "大雄与龙骑士", 8),
        ("哆啦A梦珍藏版Vol_43卷.mobi", "哆啦A梦珍藏版", 43),
    ],
)
def test_regex_identity_recognizes_explicit_volume_at_any_filename_position(
    filename, expected_title, expected_volume
):
    identity = recognize_book_identity_with_regex(f"comic/{filename}")

    assert identity.title == expected_title
    assert identity.volume_index == expected_volume


@pytest.mark.parametrize(
    "filename",
    [
        "合集 Vol.01-Vol.24.pdf",
        "合集 第01卷-第24卷.pdf",
        "合集 卷01-卷24.pdf",
        "合集 册01-24.pdf",
    ],
)
def test_regex_identity_does_not_treat_volume_range_as_one_volume(filename):
    identity = recognize_book_identity_with_regex(f"comic/{filename}")

    assert identity.volume_index is None


def test_regex_identity_supports_bracketed_filename_and_dash_filename():
    bracketed = recognize_book_identity_with_regex("电子书/[活着][余华].epub")
    dashed = recognize_book_identity_with_regex(
        "电子书/斯泰尔斯庄园奇案 - (英)阿加莎·克里斯蒂.epub"
    )

    assert (bracketed.title, bracketed.author) == ("活着", "余华")
    assert (dashed.title, dashed.author) == ("斯泰尔斯庄园奇案", "阿加莎·克里斯蒂")


@pytest.mark.parametrize(
    ("logical_path", "expected_title", "expected_author"),
    [
        (
            "/monitor/authorized/books-1991864018/无限恐怖 (zhttty) (mirror.example, archive.example).epub",
            "无限恐怖",
            "zhttty",
        ),
        (
            "/monitor/authorized/books-1991864018/《惊悚乐园》(校对版全本+番外) (三天两觉) (mirror.example, archive.example).epub",
            "惊悚乐园",
            "三天两觉",
        ),
        (
            "/monitor/authorized/books-1991864018/calibre/[英]菲利普•普尔曼(Philip Pullman)/黑暗物质三部曲 (68)/黑暗物质三部曲 - [英]菲利普•普尔曼(Philip Pullman).epub",
            "黑暗物质三部曲",
            "[英]菲利普•普尔曼(Philip Pullman)",
        ),
        (
            "/monitor/authorized/books-1991864018/calibre/[日] 山崎丰子/白色巨塔 (52)/白色巨塔 - [日] 山崎丰子.epub",
            "白色巨塔",
            "[日] 山崎丰子",
        ),
        (
            "/monitor/authorized/books-1991864018/calibre/天下霸唱/鬼吹灯-全八册 (50)/鬼吹灯-全八册 - 天下霸唱.epub",
            "鬼吹灯-全八册",
            "天下霸唱",
        ),
    ],
)
def test_regex_identity_recognizes_real_download_and_calibre_paths(
    logical_path, expected_title, expected_author
):
    identity = recognize_book_identity_with_regex(logical_path)

    assert (identity.title, identity.author) == (expected_title, expected_author)
    assert identity.volume_index is None


def test_download_filename_rule_requires_a_domain_source_suffix():
    identity = recognize_book_identity_with_regex(
        "小说/时间机器 (插图版) (威尔斯).epub"
    )

    assert identity.title == "时间机器 (插图版) (威尔斯)"
    assert identity.author == UNKNOWN_AUTHOR


@pytest.mark.parametrize(
    ("logical_path", "expected_title", "expected_author", "expected_volume"),
    [
        (
            "电子书/真需求 (梁宁) (Z-Library).epub",
            "真需求",
            "梁宁",
            None,
        ),
        (
            "电子书/Charlottes Web (E. B. White) (Z-Library).pdf",
            "Charlottes Web",
            "E. B. White",
            None,
        ),
        (
            "电子书/Charlottes Web (E.B.White) (Z-Library).epub",
            "Charlottes Web",
            "E.B.White",
            None,
        ),
        (
            "电子书/Hillbilly Elegy (J. D. Vance) (Z-Library) (2).pdf",
            "Hillbilly Elegy",
            "J. D. Vance",
            None,
        ),
        (
            "电子书/白夜行_(东野圭吾)_(z-library.sk_1lib.sk_z-lib.sk).epub",
            "白夜行",
            "东野圭吾",
            None,
        ),
        (
            "电子书/股票投资要义-(胡斐)-2015.pdf",
            "股票投资要义",
            "胡斐",
            None,
        ),
    ],
)
def test_regex_identity_cleans_download_source_and_extracts_author(
    logical_path, expected_title, expected_author, expected_volume
):
    identity = recognize_book_identity_with_regex(logical_path)

    assert (identity.title, identity.author, identity.volume_index) == (
        expected_title,
        expected_author,
        expected_volume,
    )
    assert identity.source == "regex"


def test_dotted_author_names_are_not_mistaken_for_download_hostnames():
    assert not book_identity._looks_like_download_source("E.B.White")
    assert not book_identity._looks_like_download_source("T.S.Eliot")
    assert not book_identity._looks_like_download_source("E. B. White")
    assert book_identity._looks_like_download_source("z-lib.sk")
    assert book_identity._looks_like_download_source("libgen.is")
    assert book_identity._looks_like_download_source("ebooks.example.com")


def test_regex_identity_keeps_plain_volume_parenthetical():
    identity = recognize_book_identity_with_regex(
        "漫画/[FX戦士久留美][ですにゃん×荒酸だいすき][角川][Vol.01-Vol.05][未完]/FX戦士久留美 (1).zip"
    )

    assert identity.volume_index == 1
    assert identity.title == "FX戦士久留美"


def test_regex_identity_uses_grade_directory_as_volume():
    identity = recognize_book_identity_with_regex(
        "Wonders/G2/g2 vocabulary cards.pdf"
    )

    assert identity.title == "g2 vocabulary cards"
    assert identity.author == UNKNOWN_AUTHOR
    assert identity.volume_index == 2
    assert identity.source == "regex"


def test_regex_identity_keeps_file_volume_over_grade_directory():
    identity = recognize_book_identity_with_regex(
        "Wonders/G6/Unit 3 Week 2 03.pdf"
    )

    assert identity.volume_index == 3


def test_regex_identity_uses_parent_for_volume_only_filename():
    identity = recognize_book_identity_with_regex(
        "漫画/[齐木楠雄的灾难][麻生周一]/Vol.05.cbz"
    )

    assert identity.title == "齐木楠雄的灾难"
    assert identity.author == "麻生周一"
    assert identity.volume_index == 5


def test_regex_identity_falls_back_to_filename_and_unknown_author():
    identity = recognize_book_identity_with_regex("电子书/星舰手册.pdf")

    assert identity.title == "星舰手册"
    assert identity.author == UNKNOWN_AUTHOR
    assert identity.volume_index is None


def test_regex_identity_can_use_a_volume_directory():
    identity = recognize_book_identity_with_regex(
        "漫画/齐木楠雄的灾难 第6卷/chapter.cbz"
    )

    assert (identity.title, identity.author, identity.volume_index) == (
        "齐木楠雄的灾难",
        UNKNOWN_AUTHOR,
        6,
    )


def test_identity_merge_key_uses_only_normalized_title_and_author():
    assert identity_merge_key("《活着》", "余 华") == "活着:余华"


@pytest.mark.parametrize(
    ("value", "abnormal"),
    [
        ("！！@#", True),
        ("12345", True),
        ("１２３４５", True),
        ("Book", True),
        ("活", True),
        ("一二三四五六七八九十", False),
        ("一二三四五六七八九十一", True),
        ("活着", False),
        ("3D打印", False),
    ],
)
def test_regex_identity_value_anomaly_detection(value, abnormal):
    assert book_identity._identity_value_is_abnormal(value) is abnormal


def test_complete_regex_identity_is_reused_from_path_cache(
    db_session, test_settings, tmp_path, monkeypatch
):
    source = tmp_path / "活着 - 余华.epub"
    source.write_bytes(b"book")

    first = recognize_book_identity(db_session, test_settings, source, source.name)
    db_session.commit()

    assert first.source == "regex"
    assert first.cache_hit is False
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM BookIdentityCache")).scalar() == 1
    )
    monkeypatch.setattr(
        book_identity,
        "recognize_book_identity_with_regex",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("regex must not run after a cache hit")
        ),
    )

    second = recognize_book_identity(db_session, test_settings, source, source.name)

    assert second.cache_hit is True
    assert second.source == "regex"
    assert (second.title, second.author) == ("活着", "余华")
    assert second.raw_metadata()["cacheHit"] is True


def test_successful_ai_identity_is_reused_without_regex_or_ai(
    db_session, test_settings, tmp_path, monkeypatch
):
    source = tmp_path / "messy-name.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"星舰小说","author":"作者甲","volumeIndex":2,"confidence":0.93}'
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(book_identity, "urlopen", fake_urlopen)
    first = recognize_book_identity(db_session, test_settings, source, source.name)
    db_session.commit()

    assert first.source == "ai"
    assert first.cache_hit is False
    monkeypatch.setattr(
        book_identity,
        "recognize_book_identity_with_regex",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("regex must not run after a cache hit")
        ),
    )
    monkeypatch.setattr(
        book_identity,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("AI must not run after a cache hit")
        ),
    )

    second = recognize_book_identity(db_session, test_settings, source, source.name)

    assert len(requests) == 1
    assert second.cache_hit is True
    assert second.source == "ai"
    assert (second.title, second.author, second.volume_index) == (
        "星舰小说",
        "作者甲",
        2,
    )


def test_incomplete_regex_fallback_is_not_cached_without_ai(
    db_session, test_settings, tmp_path
):
    source = tmp_path / "活着.epub"
    source.write_bytes(b"book")

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "regex"
    assert identity.author == UNKNOWN_AUTHOR
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM BookIdentityCache")).scalar() == 0
    )


def test_identity_cache_with_old_parser_version_is_refreshed(
    db_session, test_settings, tmp_path
):
    source = tmp_path / "活着 - 余华.epub"
    source.write_bytes(b"book")
    recognize_book_identity(db_session, test_settings, source, source.name)
    db_session.execute(
        text("UPDATE BookIdentityCache SET parserVersion = :version"),
        {"version": book_identity.IDENTITY_PARSER_VERSION - 1},
    )
    db_session.commit()

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.cache_hit is False
    assert (
        db_session.execute(text("SELECT parserVersion FROM BookIdentityCache")).scalar()
        == book_identity.IDENTITY_PARSER_VERSION
    )


def test_enabled_ai_is_fallback_for_incomplete_regex_and_receives_monitor_relative_path(
    db_session, test_settings, tmp_path, monkeypatch
):
    monitor = test_settings.resolved_monitor_root
    source_dir = monitor / "novels"
    source_dir.mkdir(parents=True)
    source = source_dir / "messy-name.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "星舰小说",
                                    "author": "作者甲",
                                    "volumeIndex": 2,
                                    "confidence": 0.93,
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(book_identity, "urlopen", fake_urlopen)

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "ai"
    assert identity.title == "星舰小说"
    assert identity.author == "作者甲"
    assert identity.volume_index == 2
    assert identity.logical_path == "messy-name.epub"
    request_body = json.loads(requests[0][0].data.decode("utf-8"))
    assert request_body["messages"][1]["content"] == identity.logical_path
    assert str(tmp_path) not in request_body["messages"][1]["content"]


def test_complete_regex_identity_skips_enabled_ai(
    db_session, test_settings, tmp_path, monkeypatch
):
    source = tmp_path / "活着 - 余华.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)
    monkeypatch.setattr(
        book_identity,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("AI must not replace a complete regex identity")
        ),
    )

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "regex"
    assert (identity.title, identity.author) == ("活着", "余华")
    assert identity.fallback_reason is None


def test_ai_fallback_result_takes_precedence_over_regex_volume(
    db_session, test_settings, tmp_path, monkeypatch
):
    source = tmp_path / "星舰小说 02.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)
    monkeypatch.setattr(
        book_identity,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"星舰小说","author":"作者甲","volumeIndex":9,"confidence":0.9}'
                        }
                    }
                ]
            }
        ),
    )

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "ai"
    assert (identity.title, identity.author, identity.volume_index) == (
        "星舰小说",
        "作者甲",
        9,
    )


def test_ai_fallback_keeps_regex_volume_when_ai_omits_it(
    db_session, test_settings, tmp_path, monkeypatch
):
    series_dir = (
        tmp_path
        / "[山本崇一朗][擅长捉弄的高木同学（境外版）][bili][Vol.01-Vol.20][完结]"
    )
    series_dir.mkdir()
    source = series_dir / "擅长捉弄的高木同学（境外版） Vol.08.zip"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)
    monkeypatch.setattr(
        book_identity,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"擅长捉弄的高木同学（境外版）","author":"山本崇一朗","volumeIndex":null,"confidence":0.95}'
                        }
                    }
                ]
            }
        ),
    )

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "ai"
    assert (identity.title, identity.author, identity.volume_index) == (
        "擅长捉弄的高木同学（境外版）",
        "山本崇一朗",
        8,
    )


def test_ai_fallback_failure_keeps_incomplete_regex_result(
    db_session, test_settings, tmp_path, monkeypatch
):
    source = tmp_path / "活着.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)

    def failing_urlopen(request, timeout):
        raise TimeoutError("gateway timeout")

    monkeypatch.setattr(book_identity, "urlopen", failing_urlopen)

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "regex"
    assert (identity.title, identity.author) == ("活着", UNKNOWN_AUTHOR)
    assert identity.fallback_reason == "AI identity recognition failed: gateway timeout"
    assert identity.logical_path == source.name


def test_ai_payment_required_explains_how_to_restore_recognition(
    db_session, test_settings, tmp_path, monkeypatch
):
    source = tmp_path / "活着.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)

    def payment_required(request, timeout):
        raise HTTPError(
            request.full_url,
            402,
            "Payment Required",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(book_identity, "urlopen", payment_required)

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "regex"
    assert identity.fallback_reason == (
        "AI 标题识别失败：AI 服务计费不可用，请检查服务商套餐、账户余额和计费设置"
    )
    assert identity.fallback_code == "AI_BILLING_REQUIRED"


def test_incomplete_regex_with_incomplete_ai_config_records_reason(
    db_session, test_settings, tmp_path
):
    source = tmp_path / "活着.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session, complete=False)

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "regex"
    assert (identity.title, identity.author) == ("活着", UNKNOWN_AUTHOR)
    assert "is missing" in str(identity.fallback_reason)


@pytest.mark.parametrize(
    "content",
    ["not-json", '{"title":"","author":"余华","volumeIndex":null,"confidence":0.5}'],
)
def test_invalid_or_empty_ai_output_falls_back_to_regex(
    db_session, test_settings, tmp_path, monkeypatch, content
):
    source = tmp_path / "活着.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session)
    monkeypatch.setattr(
        book_identity,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {"choices": [{"message": {"content": content}}]}
        ),
    )

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "regex"
    assert (identity.title, identity.author) == ("活着", UNKNOWN_AUTHOR)
    assert identity.fallback_reason.startswith("AI identity recognition failed:")


def test_disabled_ai_never_calls_the_gateway(
    db_session, test_settings, tmp_path, monkeypatch
):
    source = tmp_path / "活着.epub"
    source.write_bytes(b"book")
    _configure_ai_provider(db_session, enabled=False)
    monkeypatch.setattr(
        book_identity,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("AI must stay disabled")
        ),
    )

    identity = recognize_book_identity(db_session, test_settings, source, source.name)

    assert identity.source == "regex"
    assert (identity.title, identity.author) == ("活着", UNKNOWN_AUTHOR)


@pytest.mark.parametrize(
    "value",
    [
        "0022_0(1)",
        "6.6_20(1)",
        "RD14_SA_232_0232_N_EQ(1)",
        "1000英语词汇(2)",
    ],
)
def test_attached_parenthetical_digit_is_a_copy_suffix_not_volume(value):
    assert book_identity._volume_index(value) is None
    _title, volume = book_identity._strip_volume_suffix(value)
    assert volume is None


def test_space_separated_parenthetical_digit_remains_a_volume():
    assert book_identity._volume_index("FX戦士久留美 (1)") == 1


def test_volume_directory_title_drops_residual_copy_suffix():
    title, volume = book_identity._strip_volume_suffix(
        "数理化自学丛书第2版 化学 第4册 (2)"
    )

    assert title == "数理化自学丛书第2版 化学"
    assert volume == 4


def test_regex_identity_audio_copy_number_keeps_grade_directory_volume():
    identity = recognize_book_identity_with_regex(
        "Wonders/G2/G2 Literature Anthology/Literature Anthology G2 MP3/0022_0(1).mp3"
    )

    assert identity.volume_index == 2
    assert "0022" in identity.title


def test_regex_identity_attached_copy_number_is_not_volume_without_grade_dir():
    identity = recognize_book_identity_with_regex(
        "21 Grammar in use/02 中级 第5版 （2019最新）/中级音频/"
        "appendixes audio/Appendixe-6/6.6_20(1).mp3"
    )

    assert identity.volume_index is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "（日）川胜博著；吴宗汉，彭双潮译, (日)川胜博著 , 吴宗汉, 彭双潮译, 川胜博, 吴崇汉 etc.",
            "川胜博",
        ),
        ("Zvi Bodie;Alex Kane;Alan Marcus;", "Zvi Bodie"),
        ("（英）阿加莎·克里斯蒂", "阿加莎·克里斯蒂"),
        ("[英]菲利普•普尔曼(Philip Pullman)", "[英]菲利普•普尔曼(Philip Pullman)"),
        ("汪曾祺 编", "汪曾祺"),
        ("余华", "余华"),
    ],
)
def test_clean_author_extracts_primary_author(value, expected):
    assert book_identity._clean_author(value) == expected


def test_regex_identity_cleans_download_author_blob():
    identity = recognize_book_identity_with_regex(
        "monitor/川胜教授的中学物理教案 上、下 "
        "(（日）川胜博著；吴宗汉，彭双潮译, (日)川胜博著 , 吴宗汉, 彭双潮译, 川胜博, 吴崇汉 etc.) "
        "(Z-Library).pdf"
    )

    assert identity.title == "川胜教授的中学物理教案 上、下"
    assert identity.author == "川胜博"
    assert identity.volume_index is None


def test_regex_identity_keeps_chinese_edition_number_out_of_volume():
    identity = recognize_book_identity_with_regex(
        "数理化自学丛书-第二版/数理化自学丛书第2版 - 佚名.pdf"
    )

    assert identity.title == "数理化自学丛书第2版"
    assert identity.volume_index is None


def test_regex_identity_keeps_english_edition_ordinal():
    identity = recognize_book_identity_with_regex(
        "Lehninger Principles of Biochemistry, 8th Edition "
        "(David L. Nelson, Michael M. Cox etc.) (Z-Library).pdf"
    )

    assert identity.title == "Lehninger Principles of Biochemistry, 8th Edition"
    assert identity.author == "David L. Nelson, Michael M. Cox"
    assert identity.volume_index is None
