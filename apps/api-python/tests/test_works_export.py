from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import LibraryFile, LibraryMediaVersion, LibraryVolume, LibraryWork


def _login(client: TestClient, db: Session) -> None:
    db.add(
        User(
            email="export-api@example.com",
            name="导出接口用户",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
    )
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "export-api@example.com", "password": "starshipnas"},
    )
    assert response.status_code == 200


def _work_with_file(
    db: Session,
    work_id: str,
    title: str,
    *,
    path: str,
    kind: str = "ebook",
    hidden: bool = False,
) -> None:
    work = LibraryWork(
        id=work_id,
        title=title,
        normalized_title=title.casefold(),
        author="林川",
        normalized_author="林川",
        tags='["收藏"]',
        hidden=hidden,
    )
    db.add(work)
    media = LibraryMediaVersion(id=f"media-{work_id}", work_id=work_id, media_kind="EBOOK")
    db.add(media)
    volume = LibraryVolume(
        id=f"volume-{work_id}",
        media_version_id=media.id,
        title=f"{title} 默认卷",
        sort_order=0,
        format="EPUB",
        resource_key=f"key-{work_id}",
        publisher="星海出版社",
    )
    db.add(volume)
    db.add(
        LibraryFile(
            id=f"file-{work_id}",
            volume_id=volume.id,
            path=path,
            kind=kind,
            mime_type="application/epub+zip",
            sort_order=0,
        )
    )
    db.commit()


def test_works_export_requires_auth(client: TestClient) -> None:
    response = client.get("/api/works/export")
    assert response.status_code in (401, 403)


def test_works_export_returns_csv_with_files(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    _work_with_file(
        db_session,
        "export-visible",
        "外刊精读：经济学人2024",
        path="外刊/经济学人/2024/0318.pdf",
        kind="ebook",
    )
    _work_with_file(
        db_session,
        "export-hidden",
        "隐藏的书",
        path="private/secret.pdf",
        hidden=True,
    )

    response = client.get("/api/works/export")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]

    body = response.content.decode("utf-8-sig")
    assert body.startswith("标题")
    assert "外刊精读：经济学人2024" in body
    assert "外刊/经济学人/2024/0318.pdf" in body
    # 隐藏书不应导出
    assert "隐藏的书" not in body
    # 一行表头 + 可见书一行
    assert body.count("外刊精读：经济学人2024") == 1


def test_works_export_escapes_csv_special_chars(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    _work_with_file(
        db_session,
        "export-comma",
        '含,逗号和"引号"的书',
        path='外刊/报告"特别".pdf',
    )

    response = client.get("/api/works/export")
    assert response.status_code == 200
    body = response.content.decode("utf-8-sig")
    # 含逗号/引号字段被双引号包裹，内层引号转义为双引号
    assert '"含,逗号和""引号""的书"' in body
    assert '"外刊/报告""特别"".pdf"' in body