from pathlib import Path


def test_skill_upload_route_allows_the_documented_package_size():
    dockerfile = (
        Path(__file__).resolve().parents[3] / "deploy" / "Dockerfile.frontend"
    ).read_text(encoding="utf-8")

    skill_location = dockerfile.index("location /api/skills")
    body_limit = dockerfile.index("client_max_body_size 16m", skill_location)
    generic_api_location = dockerfile.index("location /api/ {", skill_location)

    assert skill_location < body_limit < generic_api_location
