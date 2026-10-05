"""Static checks on docker-compose files (run by scripts/security-scan.sh).

Fails if: an image is not pinned by digest; Postgres/Redis publish any port; a dev port is
bound to all interfaces (must be 127.0.0.1); in production anything but the reverse proxy
publishes ports; Redis has no password; or a production app container lacks
no-new-privileges / cap_drop ALL / a read-only root filesystem / a memory limit (app containers and GlitchTip).
"""

import os
import shutil
import subprocess
import sys

import yaml


def config(path: str) -> dict:
    env = {**os.environ, "DOMAIN": "example.test"}
    # The prod file reads secrets from .env.prod (never committed); render with the example.
    placeholder = not os.path.exists(".env.prod")
    if placeholder:
        shutil.copy(".env.example", ".env.prod")
    try:
        return _render(path, env)
    finally:
        if placeholder:
            os.remove(".env.prod")


def _render(path: str, env: dict[str, str]) -> dict:
    out = subprocess.run(
        ["docker", "compose", "-f", path, "--env-file", ".env.example", "config", "--format", "yaml"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    return yaml.safe_load(out)


def check(path: str, prod: bool) -> list[str]:
    errors: list[str] = []
    for name, svc in config(path)["services"].items():
        image = svc.get("image")
        if image and "@sha256:" not in image:
            errors.append(f"{path}:{name}: image not pinned by digest ({image})")
        for p in svc.get("ports") or []:
            host_ip = p.get("host_ip", "")
            if name in ("db", "redis"):
                errors.append(f"{path}:{name}: database/cache must not publish ports")
            elif not prod and host_ip != "127.0.0.1":
                errors.append(f"{path}:{name}: dev port {p.get('published')} bound to all interfaces")
            elif prod and name != "caddy":
                errors.append(f"{path}:{name}: only the reverse proxy may publish ports")
        if name == "redis" and "requirepass" not in " ".join(svc.get("command") or []):
            errors.append(f"{path}:redis: no password")
        if prod and name in ("api", "worker", "beat", "web", "glitchtip"):
            if "no-new-privileges:true" not in (svc.get("security_opt") or []):
                errors.append(f"{path}:{name}: missing no-new-privileges")
            if "ALL" not in (svc.get("cap_drop") or []):
                errors.append(f"{path}:{name}: capabilities not dropped")
            if not svc.get("read_only"):
                errors.append(f"{path}:{name}: root filesystem not read-only")
            if not svc.get("mem_limit"):
                errors.append(f"{path}:{name}: no memory limit")
    return errors


def main() -> int:
    errors = check("docker-compose.yml", prod=False) + check("docker-compose.prod.yml", prod=True)
    for e in errors:
        print("FAIL", e)
    print("compose checks:", "OK" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
