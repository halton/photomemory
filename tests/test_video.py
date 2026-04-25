"""测试视频流 API /api/video/<id>"""
import os
import tempfile


def _insert_video(db, path):
    """Helper: insert a video record."""
    db.execute(
        "INSERT INTO photos (path, filename, directory, size, width, height, format, file_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (path, os.path.basename(path), os.path.dirname(path), 4096, 1920, 1080, 'MP4', 'video')
    )
    db.commit()
    row = db.execute("SELECT id FROM photos WHERE path=?", (path,)).fetchone()
    return row["id"]


def _make_video_file():
    """Create a temp .mp4 file in the DB_PATH parent dir so is_safe_path passes."""
    import backend.api_server as api_mod
    target_dir = os.path.dirname(api_mod.DB_PATH) if api_mod.DB_PATH else os.getcwd()
    fd, path = tempfile.mkstemp(suffix='.mp4', dir=target_dir)
    os.write(fd, b'\x00' * 4096)
    os.close(fd)
    return path


def test_video_nonexistent_id(seeded_client):
    r = seeded_client.get('/api/video/999999')
    assert r.status_code == 404


def test_non_video_file_returns_error(seeded_client, seeded_db):
    """A photo (non-video) file should return 400 or 403"""
    r = seeded_client.get('/api/video/1')
    assert r.status_code in (400, 403)


def test_video_valid_returns_200(seeded_client, seeded_db):
    """Valid video ID returns 200 with correct content-type"""
    path = _make_video_file()
    try:
        vid = _insert_video(seeded_db, path)
        r = seeded_client.get(f'/api/video/{vid}')
        assert r.status_code == 200
        assert 'video' in r.content_type
    finally:
        os.unlink(path)


def test_range_request_returns_206(seeded_client, seeded_db):
    path = _make_video_file()
    try:
        vid = _insert_video(seeded_db, path)
        r = seeded_client.get(f'/api/video/{vid}', headers={'Range': 'bytes=0-1023'})
        assert r.status_code == 206
        assert 'Content-Range' in r.headers
    finally:
        os.unlink(path)


def test_range_start_only(seeded_client, seeded_db):
    path = _make_video_file()
    try:
        vid = _insert_video(seeded_db, path)
        r = seeded_client.get(f'/api/video/{vid}', headers={'Range': 'bytes=1024-'})
        assert r.status_code == 206
        assert 'Content-Range' in r.headers
    finally:
        os.unlink(path)
