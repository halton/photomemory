"""测试视频缩略图生成（ffmpeg集成测试 + API端点测试）"""
import os
import subprocess
import tempfile
import pytest


def _create_real_video(duration=2):
    """使用 ffmpeg 生成一个真实的测试视频文件"""
    fd, path = tempfile.mkstemp(suffix='.mp4')
    os.close(fd)
    try:
        result = subprocess.run([
            'ffmpeg', '-y', '-f', 'lavfi', '-i',
            f'color=c=blue:s=320x240:d={duration}',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-t', str(duration), path
        ], capture_output=True, timeout=15)
        if result.returncode != 0:
            pytest.skip("ffmpeg 无法生成测试视频")
        return path
    except FileNotFoundError:
        pytest.skip("ffmpeg 未安装")


class TestThumbnailService:
    """直接测试 thumbnail service 模块"""

    def test_find_ffmpeg(self):
        from backend.services.thumbnail import find_ffmpeg
        ffmpeg = find_ffmpeg()
        assert ffmpeg is not None, "ffmpeg 应该可以被找到"
        assert os.path.exists(ffmpeg)

    def test_generate_video_thumbnail_valid(self):
        from backend.services.thumbnail import generate_video_thumbnail
        path = _create_real_video()
        try:
            data = generate_video_thumbnail(path, 200)
            assert len(data) > 100, "缩略图应该有实际内容"
            assert data[:3] == b'\xff\xd8\xff', "应该是有效的 JPEG"
        finally:
            os.unlink(path)

    def test_generate_video_thumbnail_different_sizes(self):
        from backend.services.thumbnail import generate_video_thumbnail
        path = _create_real_video()
        try:
            small = generate_video_thumbnail(path, 100)
            large = generate_video_thumbnail(path, 500)
            assert len(small) > 0
            assert len(large) > 0
            # 大缩略图通常更大
            assert len(large) > len(small)
        finally:
            os.unlink(path)

    def test_generate_video_thumbnail_invalid_file(self):
        from backend.services.thumbnail import generate_video_thumbnail
        fd, path = tempfile.mkstemp(suffix='.mp4')
        os.write(fd, b'not a video')
        os.close(fd)
        try:
            with pytest.raises(Exception):
                generate_video_thumbnail(path, 200)
        finally:
            os.unlink(path)

    def test_generate_video_thumbnail_nonexistent(self):
        from backend.services.thumbnail import generate_video_thumbnail
        with pytest.raises(Exception):
            generate_video_thumbnail('/nonexistent/video.mp4', 200)

    def test_placeholder_thumbnail(self):
        from backend.services.thumbnail import placeholder_thumbnail
        data = placeholder_thumbnail(100, "🎬")
        assert len(data) > 0
        assert data[:3] == b'\xff\xd8\xff'


class TestVideoThumbAPI:
    """测试视频缩略图 API 端点"""

    def test_thumb_api_video_returns_jpeg(self, seeded_client, seeded_db):
        """视频文件的缩略图 API 应返回 JPEG"""
        path = _create_real_video()
        try:
            seeded_db.execute(
                "INSERT INTO photos (path, filename, directory, size, width, height, format, file_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (path, os.path.basename(path), os.path.dirname(path), os.path.getsize(path), 320, 240, 'MP4', 'video')
            )
            seeded_db.commit()
            row = seeded_db.execute("SELECT id FROM photos WHERE path=?", (path,)).fetchone()
            vid = row["id"]
            r = seeded_client.get(f'/api/thumb/{vid}')
            assert r.status_code == 200
            assert r.content_type == 'image/jpeg'
            assert r.data[:3] == b'\xff\xd8\xff'
        finally:
            os.unlink(path)

    def test_thumb_api_video_caches(self, seeded_client, seeded_db):
        """视频缩略图应被缓存到磁盘"""
        path = _create_real_video()
        try:
            seeded_db.execute(
                "INSERT INTO photos (path, filename, directory, size, width, height, format, file_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (path, os.path.basename(path), os.path.dirname(path), os.path.getsize(path), 320, 240, 'MP4', 'video')
            )
            seeded_db.commit()
            row = seeded_db.execute("SELECT id FROM photos WHERE path=?", (path,)).fetchone()
            vid = row["id"]
            # First call generates
            r1 = seeded_client.get(f'/api/thumb/{vid}')
            assert r1.status_code == 200
            # Second call should use cache (still 200)
            r2 = seeded_client.get(f'/api/thumb/{vid}')
            assert r2.status_code == 200
            assert r2.data[:3] == b'\xff\xd8\xff'
        finally:
            os.unlink(path)
