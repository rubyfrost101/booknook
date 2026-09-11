"""HTTP contract tests for POST /organize/runs (manual batch organize trigger)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import LibraryMediaVersion, LibraryVolume


def _login(client, db_session: Session) -> None:
    user = User(
        email="organize-runs@example.com",
        name="整理接口用户",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "organize-runs@example.com", "password": "starshipnas"},
    )
    assert response.status_code == 200


def _insert_work(db_session: Session, work_id: str) -> None:
    db_session.execute(
        text(
            """
            INSERT INTO `LibraryWork`
                (`id`, `origin`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`,
                 `tags`, `metadataQuality`, `organizeStatus`, `hidden`, `organized`,
                 `createdAt`, `updatedAt`)
            VALUES
                (:id, 'MANUAL', :title, :title, '未知作者', '未知作者', '[]', 0,
                 'UNASSESSED', 0, 0, '2026-07-21T00:00:00+00:00', '2026-07-21T00:00:00+00:00')
            """
        ),
        {"id": work_id, "title": f"测试作品 {work_id}"},
    )
    db_session.commit()


def _insert_volume(
    db_session: Session,
    *,
    work_id: str,
    media_version_id: str,
    media_kind: str,
    volume_id: str,
    volume_format: str,
) -> None:
    db_session.add(
        LibraryMediaVersion(
            id=media_version_id,
            work_id=work_id,
            media_kind=media_kind,
        )
    )
    db_session.add(
        LibraryVolume(
            id=volume_id,
            media_version_id=media_version_id,
            title=f"卷册 {volume_id}",
            format=volume_format,
            resource_key=f"resource:{volume_id}",
            sort_order=0,
        )
    )
    db_session.commit()


def _job_rows(db_session: Session, work_id: str) -> list[dict]:
    return [
        dict(row)
        for row in db_session.execute(
            text(
                "SELECT `workId`, `trigger`, `runId` FROM `OrganizeJob` "
                "WHERE `workId` = :work_id ORDER BY `createdAt`"
            ),
            {"work_id": work_id},
        ).mappings()
    ]


def test_create_organize_run_requires_authentication(client) -> None:
    response = client.post("/api/organize/runs", json={"workIds": []})
    assert response.status_code == 401


def test_create_organize_run_queues_candidates_and_returns_run(
    client, db_session
) -> None:
    _login(client, db_session)
    _insert_work(db_session, "batch-run-work")
    _insert_volume(
        db_session,
        work_id="batch-run-work",
        media_version_id="batch-media",
        media_kind="EBOOK",
        volume_id="batch-volume",
        volume_format="EPUB",
    )

    response = client.post(
        "/api/organize/runs",
        json={"workIds": [], "limit": 2000},
    )

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["trigger"] == "MANUAL"
    assert run["queuedCount"] == 1
    assert run["scope"]["workIds"] == []
    assert run["scope"]["rules"] == {"unrecognized": True, "missingMetadata": True}
    jobs = _job_rows(db_session, "batch-run-work")
    assert len(jobs) == 1
    assert jobs[0]["trigger"] == "MANUAL"
    assert jobs[0]["runId"] == run["id"]


def test_create_organize_run_with_work_ids_scopes_the_queue(client, db_session) -> None:
    _login(client, db_session)
    for work_id in ("scoped-work-a", "scoped-work-b"):
        _insert_work(db_session, work_id)
        _insert_volume(
            db_session,
            work_id=work_id,
            media_version_id=f"media-{work_id}",
            media_kind="EBOOK",
            volume_id=f"volume-{work_id}",
            volume_format="EPUB",
        )

    response = client.post(
        "/api/organize/runs",
        json={"workIds": ["scoped-work-a"], "limit": 500},
    )

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["scope"]["workIds"] == ["scoped-work-a"]
    assert run["queuedCount"] == 1
    assert len(_job_rows(db_session, "scoped-work-a")) == 1
    assert _job_rows(db_session, "scoped-work-b") == []


def test_create_organize_run_clamps_out_of_range_limit(client, db_session) -> None:
    _login(client, db_session)
    for work_id in ("limit-clamp-a", "limit-clamp-b"):
        _insert_work(db_session, work_id)
        _insert_volume(
            db_session,
            work_id=work_id,
            media_version_id=f"media-{work_id}",
            media_kind="EBOOK",
            volume_id=f"volume-{work_id}",
            volume_format="EPUB",
        )

    oversized = client.post(
        "/api/organize/runs",
        json={"workIds": ["limit-clamp-a"], "limit": 999_999},
    )
    assert oversized.status_code == 200
    assert oversized.json()["data"]["run"]["queuedCount"] == 1

    tiny = client.post(
        "/api/organize/runs",
        json={"workIds": ["limit-clamp-b"], "limit": 0},
    )
    assert tiny.status_code == 200
    assert tiny.json()["data"]["run"]["queuedCount"] == 1


def test_create_organize_run_rejects_non_numeric_limit(client, db_session) -> None:
    _login(client, db_session)
    response = client.post(
        "/api/organize/runs",
        json={"workIds": [], "limit": "many"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"]


def test_create_organize_run_accepts_missing_body(client, db_session) -> None:
    _login(client, db_session)
    response = client.post("/api/organize/runs")
    assert response.status_code == 200
    assert response.json()["data"]["run"]["queuedCount"] == 0
