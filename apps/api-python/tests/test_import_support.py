"""Tag-merge behavior of ``_ensure_work`` (import support layer)."""

from __future__ import annotations

import json
import uuid

from app.modules.imports.application.import_support import _ensure_work


class _FakeQueries:
    def __init__(self) -> None:
        self.works: dict[str, dict] = {}

    def get_work_by_merge_key(self, merge_key: str) -> dict | None:
        for work in self.works.values():
            if work.get("mergeKey") == merge_key:
                return dict(work)
        return None

    def get_work_by_normalized_title(self, normalized_title: str) -> dict | None:
        for work in self.works.values():
            if work.get("normalizedTitle") == normalized_title:
                return dict(work)
        return None

    def get_work_by_id(self, work_id: str) -> dict | None:
        return dict(self.works[work_id]) if work_id in self.works else None


class _FakeStore:
    def __init__(self, queries: _FakeQueries) -> None:
        self.queries = queries
        self.updated: list[tuple[str, dict]] = []

    def insert_library_work(self, columns: dict) -> dict:
        row = dict(columns)
        self.queries.works[row["id"]] = row
        return row

    def update_library_work(self, work_id: str, columns: dict) -> None:
        self.queries.works[work_id].update(columns)
        self.updated.append((work_id, dict(columns)))


def _make_store(existing: dict | None = None) -> tuple[_FakeStore, _FakeQueries]:
    queries = _FakeQueries()
    if existing is not None:
        queries.works[existing["id"]] = dict(existing)
    return _FakeStore(queries), queries


def _work_data(**overrides: object) -> dict:
    data: dict[str, object] = {
        "mergeKey": f"mk-{uuid.uuid4().hex[:8]}",
        "origin": "LOCAL",
        "title": "g2 vocabulary cards",
        "author": "未知作者",
        "tags": [],
        "monitorFolderId": None,
    }
    data.update(overrides)
    return data


def _tags_of(work: dict) -> list[str]:
    return json.loads(work["tags"])


def test_ensure_work_merges_category_tags_on_insert() -> None:
    store, _queries = _make_store()
    data = _work_data(origin="AUDIO", tags=["已读"])

    row, created = _ensure_work(
        store, _queries, data, logical_path="/monitor/Wonders/G2/g2 vocabulary cards.mp3"
    )

    assert created is True
    assert _tags_of(row) == ["已读", "小学生教材-Wonders"]


def test_ensure_work_merges_category_tags_into_existing_work() -> None:
    existing = {
        "id": "work-1",
        "mergeKey": "mk-existing",
        "normalizedTitle": "g2 vocabulary cards",
        "title": "g2 vocabulary cards",
        "author": "未知作者",
        "tags": json.dumps(["用户自定标签"], ensure_ascii=False),
    }
    store, queries = _make_store(existing)
    data = _work_data(
        mergeKey="mk-existing", title="g2 vocabulary cards", tags=["已读"]
    )

    _row, created = _ensure_work(
        store, queries, data, logical_path="/monitor/Wonders/G2/g2 vocabulary cards.mp3"
    )

    assert created is False
    merged = _tags_of(queries.works["work-1"])
    assert merged == ["用户自定标签", "小学生教材-Wonders"]
    # 用户手改标签与既有标签都不应被删除或覆盖
    assert "用户自定标签" in merged


def test_ensure_work_keeps_existing_tags_when_no_category_tags() -> None:
    existing = {
        "id": "work-1",
        "mergeKey": "mk-existing",
        "normalizedTitle": "plain book",
        "title": "plain book",
        "author": "未知作者",
        "tags": json.dumps(["旧标签"], ensure_ascii=False),
    }
    store, queries = _make_store(existing)
    data = _work_data(mergeKey="mk-existing", title="plain book", tags=[])

    _row, created = _ensure_work(store, queries, data)

    assert created is False
    assert _tags_of(queries.works["work-1"]) == ["旧标签"]
    # 没有标签变化时不应触发 tags 写回
    for _work_id, columns in store.updated:
        assert "tags" not in columns


def test_ensure_work_deduplicates_repeated_imports() -> None:
    store, queries = _make_store()
    data = _work_data(origin="PDF", tags=[])
    path = "/monitor/Glencoe/生物学(BIOLOGY)/x.pdf"

    _row, _created = _ensure_work(store, queries, data, logical_path=path)
    _row, created = _ensure_work(store, queries, data, logical_path=path)

    assert created is False
    merged = _tags_of(queries.works[list(queries.works)[0]])
    assert merged == ["中学教材-生物"]


def test_ensure_work_without_logical_path_keeps_plain_tags() -> None:
    store, _queries = _make_store()
    data = _work_data(tags=["已读"])

    row, created = _ensure_work(store, _queries, data)

    assert created is True
    assert _tags_of(row) == ["已读"]
