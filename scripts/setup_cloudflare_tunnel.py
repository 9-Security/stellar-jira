#!/usr/bin/env python3
"""Provision Cloudflare Tunnel (API) for stellar-soc → local serve_api :8000.

Reads secrets from .env only — never pass tokens on the command line.

Required in .env:
  CLOUDFLARE_API_TOKEN
  CLOUDFLARE_TUNNEL_HOSTNAME   e.g. xmdr.nine-security.com

Optional:
  CLOUDFLARE_ACCOUNT_ID          auto-resolved from API if omitted
  CLOUDFLARE_TUNNEL_NAME=stellar-soc
  CLOUDFLARE_ZONE_ID           (auto-resolved from hostname if omitted)
  CLOUDFLARE_TUNNEL_ORIGIN=http://127.0.0.1:8000
  CLOUDFLARE_TUNNEL_TOKEN_FILE=/opt/stellar-jira/.cloudflare/tunnel.token
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

API = "https://api.cloudflare.com/client/v4"


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or "").strip()


def _zone_name_from_hostname(hostname: str) -> str:
    parts = hostname.strip().lower().split(".")
    if len(parts) < 2:
        raise ValueError(f"invalid hostname: {hostname}")
    return ".".join(parts[-2:])


def _api(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resp = client.request(method, f"{API}{path}", json=json_body)
    data = resp.json()
    if not resp.is_success or not data.get("success", False):
        errors = data.get("errors") or resp.text
        raise RuntimeError(f"Cloudflare API {method} {path} failed: {errors}")
    return data


def _resolve_zone_id(client: httpx.Client, hostname: str, zone_id: str) -> str:
    if zone_id:
        return zone_id
    zone_name = _zone_name_from_hostname(hostname)
    data = _api(client, "GET", f"/zones?name={zone_name}")
    results = data.get("result") or []
    if not results:
        raise RuntimeError(f"zone not found for {zone_name}")
    return str(results[0]["id"])


def _resolve_account_id(client: httpx.Client, account_id: str, hostname: str) -> str:
    if account_id:
        return account_id
    data = _api(client, "GET", "/accounts")
    results = data.get("result") or []
    if len(results) == 1:
        resolved = str(results[0]["id"])
        print(f"Resolved CLOUDFLARE_ACCOUNT_ID={resolved}")
        return resolved
    if len(results) > 1:
        names = ", ".join(
            f"{row.get('name')} ({row.get('id')})" for row in results[:5]
        )
        raise RuntimeError(
            "multiple accounts; set CLOUDFLARE_ACCOUNT_ID in .env. "
            f"Visible: {names}"
        )
    zone_name = _zone_name_from_hostname(hostname)
    zone_data = _api(client, "GET", f"/zones?name={zone_name}")
    zone_rows = zone_data.get("result") or []
    if not zone_rows:
        raise RuntimeError(
            f"zone not found for {zone_name}; set CLOUDFLARE_ACCOUNT_ID in .env"
        )
    acct = (zone_rows[0].get("account") or {}).get("id")
    if not acct:
        raise RuntimeError("could not resolve account id; set CLOUDFLARE_ACCOUNT_ID in .env")
    resolved = str(acct)
    print(f"Resolved CLOUDFLARE_ACCOUNT_ID={resolved} (from zone {zone_name})")
    return resolved


def _find_tunnel(client: httpx.Client, account_id: str, name: str) -> dict[str, Any] | None:
    data = _api(client, "GET", f"/accounts/{account_id}/cfd_tunnel")
    for row in data.get("result") or []:
        if str(row.get("name") or "") == name:
            return row
    return None


def _create_tunnel(client: httpx.Client, account_id: str, name: str) -> dict[str, Any]:
    data = _api(
        client,
        "POST",
        f"/accounts/{account_id}/cfd_tunnel",
        json_body={"name": name, "config_src": "cloudflare"},
    )
    return data["result"]


def _tunnel_token(client: httpx.Client, account_id: str, tunnel_id: str) -> str:
    data = _api(
        client,
        "GET",
        f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token",
    )
    return str(data.get("result") or "")


def _put_ingress(
    client: httpx.Client,
    account_id: str,
    tunnel_id: str,
    hostname: str,
    origin: str,
) -> None:
    _api(
        client,
        "PUT",
        f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
        json_body={
            "config": {
                "ingress": [
                    {
                        "hostname": hostname,
                        "service": origin,
                        "originRequest": {"connectTimeout": 30},
                    },
                    {"service": "http_status:404"},
                ]
            }
        },
    )


def _dns_record_name(hostname: str, zone_name: str) -> str:
    host = hostname.lower().removesuffix(f".{zone_name.lower()}")
    return host if host else "@"


def _ensure_dns_cname(
    client: httpx.Client,
    zone_id: str,
    hostname: str,
    tunnel_id: str,
) -> None:
    zone_name = _zone_name_from_hostname(hostname)
    record_name = _dns_record_name(hostname, zone_name)
    target = f"{tunnel_id}.cfargotunnel.com"
    existing = _api(
        client,
        "GET",
        f"/zones/{zone_id}/dns_records?type=CNAME&name={record_name}",
    )
    for row in existing.get("result") or []:
        if str(row.get("content") or "") == target:
            print(f"DNS OK: {hostname} → {target}")
            return
        rid = row.get("id")
        if rid:
            _api(
                client,
                "PUT",
                f"/zones/{zone_id}/dns_records/{rid}",
                json_body={
                    "type": "CNAME",
                    "name": record_name,
                    "content": target,
                    "proxied": True,
                    "ttl": 1,
                },
            )
            print(f"DNS updated: {hostname} → {target}")
            return
    _api(
        client,
        "POST",
        f"/zones/{zone_id}/dns_records",
        json_body={
            "type": "CNAME",
            "name": record_name,
            "content": target,
            "proxied": True,
            "ttl": 1,
        },
    )
    print(f"DNS created: {hostname} → {target}")


def _write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _install_cloudflared() -> None:
    if shutil.which("cloudflared"):
        print(f"cloudflared OK: {subprocess.check_output(['cloudflared', '--version'], text=True).strip()}")
        return
    if os.geteuid() != 0:
        print("cloudflared not installed; run: sudo ./Tools/run cloudflare-tunnel-setup --preflight")
        return
    if not shutil.which("apt-get"):
        print("Install cloudflared manually: docs/CLOUDFLARE_TUNNEL.md")
        return
    keyring = Path("/usr/share/keyrings/cloudflare-main.gpg")
    if not keyring.is_file():
        subprocess.run(
            "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | "
            "tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null",
            shell=True,
            check=True,
        )
    list_file = Path("/etc/apt/sources.list.d/cloudflared.list")
    if not list_file.is_file():
        list_file.write_text(
            "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] "
            "https://pkg.cloudflare.com/cloudflared jammy main\n",
            encoding="utf-8",
        )
    subprocess.run(["apt-get", "update", "-qq"], check=True)
    subprocess.run(["apt-get", "install", "-y", "-qq", "cloudflared"], check=True)
    print(f"Installed {subprocess.check_output(['cloudflared', '--version'], text=True).strip()}")


def _install_soc_api_unit() -> None:
    api_unit = ROOT / "deploy/systemd/stellar-soc-api.service"
    if not shutil.which("systemctl"):
        print("systemctl not found; skip stellar-soc-api install")
        return
    if os.geteuid() != 0:
        print("Not root: skip stellar-soc-api install (use sudo --preflight)")
        return
    log_path = Path("/var/log/stellar_soc_api.log")
    if not log_path.is_file():
        log_path.touch()
        os.chmod(log_path, 0o644)
    subprocess.run(
        ["install", "-m", "644", str(api_unit), "/etc/systemd/system/stellar-soc-api.service"],
        check=True,
    )
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "stellar-soc-api.service"], check=True)
    subprocess.run(["systemctl", "restart", "stellar-soc-api.service"], check=True)
    print("systemd: stellar-soc-api enabled")


def _preflight(hostname: str, origin: str) -> int:
    web_index = ROOT / "web/dist/index.html"
    if not web_index.is_file():
        print("Missing web/dist — run: ./Tools/run web-build", file=sys.stderr)
        return 1
    secret = _env("PLATFORM_SECRET_KEY")
    if len(secret) < 32:
        print("PLATFORM_SECRET_KEY must be ≥32 chars in .env", file=sys.stderr)
        return 1
    _install_cloudflared()
    _install_soc_api_unit()
    print()
    print("Preflight OK.")
    print(f"  Local API:  curl -s {origin}/health")
    print(f"  Public URL: https://{hostname}/  (after tunnel setup)")
    print()
    print("Next: set CLOUDFLARE_API_TOKEN in .env, then:")
    print("  sudo ./Tools/run cloudflare-tunnel-setup")
    return 0


def _install_systemd(token_file: Path) -> None:
    api_unit = ROOT / "deploy/systemd/stellar-soc-api.service"
    tunnel_unit_src = ROOT / "deploy/systemd/cloudflared-stellar-soc-token.service"
    tunnel_unit_dst = Path("/etc/systemd/system/cloudflared-stellar-soc.service")
    if not shutil.which("systemctl"):
        print("systemctl not found; skip systemd install")
        return
    if os.geteuid() != 0:
        print("Not root: skip systemd install (run with sudo to install units)")
        return
    subprocess.run(
        ["install", "-m", "644", str(api_unit), "/etc/systemd/system/stellar-soc-api.service"],
        check=True,
    )
    content = tunnel_unit_src.read_text(encoding="utf-8").replace(
        "CLOUDFLARE_TUNNEL_TOKEN_FILE_PLACEHOLDER",
        str(token_file),
    )
    tunnel_unit_dst.write_text(content, encoding="utf-8")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "stellar-soc-api.service"], check=True)
    subprocess.run(["systemctl", "enable", "cloudflared-stellar-soc.service"], check=True)
    subprocess.run(["systemctl", "restart", "stellar-soc-api.service"], check=True)
    subprocess.run(["systemctl", "restart", "cloudflared-stellar-soc.service"], check=True)
    print("systemd: stellar-soc-api + cloudflared-stellar-soc enabled")


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup Cloudflare Tunnel via API")
    parser.add_argument("--dry-run", action="store_true", help="Only print planned actions")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Install cloudflared + stellar-soc-api (no Cloudflare API needed)",
    )
    args = parser.parse_args()

    _load_dotenv()

    token = _env("CLOUDFLARE_API_TOKEN")
    account_id = _env("CLOUDFLARE_ACCOUNT_ID")
    hostname = _env("CLOUDFLARE_TUNNEL_HOSTNAME")
    tunnel_name = _env("CLOUDFLARE_TUNNEL_NAME", "stellar-soc")
    zone_id = _env("CLOUDFLARE_ZONE_ID")
    origin = _env("CLOUDFLARE_TUNNEL_ORIGIN", "http://127.0.0.1:8000")
    token_file = Path(
        _env("CLOUDFLARE_TUNNEL_TOKEN_FILE", str(ROOT / ".cloudflare" / "tunnel.token"))
    )

    if args.preflight:
        if not hostname:
            print("Missing CLOUDFLARE_TUNNEL_HOSTNAME in .env", file=sys.stderr)
            return 1
        return _preflight(hostname, origin)

    missing = [k for k, v in [
        ("CLOUDFLARE_API_TOKEN", token),
        ("CLOUDFLARE_TUNNEL_HOSTNAME", hostname),
    ] if not v]
    if missing:
        print("Missing in .env:", ", ".join(missing), file=sys.stderr)
        print("See env.example Cloudflare section. Do NOT paste tokens in chat.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps({
            "tunnel_name": tunnel_name,
            "hostname": hostname,
            "origin": origin,
            "token_file": str(token_file),
        }, indent=2))
        return 0

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=60.0) as client:
        account_id = _resolve_account_id(client, account_id, hostname)
        zone_id = _resolve_zone_id(client, hostname, zone_id)
        existing = _find_tunnel(client, account_id, tunnel_name)
        if existing:
            tunnel_id = str(existing["id"])
            print(f"Reusing tunnel {tunnel_name} ({tunnel_id})")
        else:
            created = _create_tunnel(client, account_id, tunnel_name)
            tunnel_id = str(created["id"])
            print(f"Created tunnel {tunnel_name} ({tunnel_id})")

        run_token = _tunnel_token(client, account_id, tunnel_id)
        _put_ingress(client, account_id, tunnel_id, hostname, origin)
        _ensure_dns_cname(client, zone_id, hostname, tunnel_id)

    _write_token(token_file, run_token)
    print(f"Wrote connector token → {token_file}")

    if not shutil.which("cloudflared"):
        print("Install cloudflared: see docs/CLOUDFLARE_TUNNEL.md")
    else:
        _install_systemd(token_file)
        print(f"Done. Open https://{hostname}/ when cloudflared is healthy.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
