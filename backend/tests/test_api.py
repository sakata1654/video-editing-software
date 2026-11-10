"""End-to-end FastAPI API tests (health, settings, templates, upload validation, projects)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_settings():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        sres = client.get("/api/settings")
        assert sres.status_code == 200
        body = sres.json()
        assert body["ffmpeg_available"] is True
        assert body["ffprobe_available"] is True


def test_templates_crud():
    with TestClient(app) as client:
        # Default template seeded at startup
        list_res = client.get("/api/templates")
        assert list_res.status_code == 200
        assert len(list_res.json()) >= 1

        # Create template
        create_res = client.post(
            "/api/templates",
            json={
                "name": "Test Quranic Theme",
                "organization_name": "Test Org",
                "is_default": False,
            },
        )
        assert create_res.status_code == 201
        tid = create_res.json()["id"]

        # Update template
        patch_res = client.patch(
            f"/api/templates/{tid}",
            json={"organization_name": "Updated Org"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["organization_name"] == "Updated Org"

        # Delete template
        del_res = client.delete(f"/api/templates/{tid}")
        assert del_res.status_code == 204


def test_upload_validation_and_project_creation(tmp_path: Path):
    with TestClient(app) as client:
        # Reject unsupported extension
        bad_res = client.post(
            "/api/projects",
            data={"title": "Invalid"},
            files={"file": ("notes.txt", b"not a video", "text/plain")},
        )
        assert bad_res.status_code == 400

        # Upload real synthetic MP4
        mp4_path = tmp_path / "sample.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-y", str(mp4_path),
            ],
            check=True,
            capture_output=True,
        )

        with open(mp4_path, "rb") as f:
            ok_res = client.post(
                "/api/projects",
                data={"title": "Sample Islamic Lecture", "scholar_name": "Sheikh Test"},
                files={"file": ("sample.mp4", f, "video/mp4")},
            )
        assert ok_res.status_code == 201
        proj = ok_res.json()
        assert proj["title"] == "Sample Islamic Lecture"
        assert proj["width"] == 640
        assert proj["height"] == 360

        # Clean up created project
        del_res = client.delete(f"/api/projects/{proj['id']}")
        assert del_res.status_code == 204
