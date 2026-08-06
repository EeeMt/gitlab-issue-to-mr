from pathlib import Path


def test_skill_upload_route_allows_the_documented_package_size():
    repo_root = Path(__file__).resolve().parents[3]
    nginx_config = (repo_root / "deploy" / "nginx" / "default.conf").read_text(
        encoding="utf-8"
    )

    skill_location = nginx_config.index("location /api/skills")
    body_limit = nginx_config.index("client_max_body_size 16m", skill_location)
    generic_api_location = nginx_config.index("location /api/ {", skill_location)

    assert skill_location < body_limit < generic_api_location


def test_frontend_image_uses_the_checked_nginx_config():
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = (repo_root / "deploy" / "Dockerfile.frontend").read_text(encoding="utf-8")

    assert "COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf" in dockerfile


def test_spa_entry_is_revalidated_and_hashed_assets_are_immutable():
    repo_root = Path(__file__).resolve().parents[3]
    nginx_config = (repo_root / "deploy" / "nginx" / "default.conf").read_text(
        encoding="utf-8"
    )

    index_location = nginx_config.index("location = /index.html")
    assert "Cache-Control \"no-cache, must-revalidate\"" in nginx_config[index_location:]

    assets_location = nginx_config.index("location /assets/")
    assert "max-age=31536000, immutable" in nginx_config[assets_location:]
