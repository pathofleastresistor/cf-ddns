"""Cloudflare API client for DNS record management."""

import requests

CF_API_BASE = "https://api.cloudflare.com/client/v4"

PROXIABLE_TYPES = {"A", "AAAA", "CNAME"}
PRIORITY_TYPES = {"MX", "SRV", "URI"}


class CloudflareAPI:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        r = requests.request(
            method, f"{CF_API_BASE}{path}", headers=self.headers, timeout=10, **kwargs
        )
        r.raise_for_status()
        return r.json()

    def get_zones(self) -> list[dict]:
        return self._request("GET", "/zones", params={"per_page": 100}).get("result", [])

    def get_dns_records(self, zone_id: str) -> list[dict]:
        return self._request(
            "GET", f"/zones/{zone_id}/dns_records", params={"per_page": 500}
        ).get("result", [])

    def create_dns_record(self, zone_id: str, data: dict) -> dict:
        return self._request(
            "POST", f"/zones/{zone_id}/dns_records", json=data
        ).get("result", {})

    def update_dns_record(self, zone_id: str, record_id: str, data: dict) -> dict:
        return self._request(
            "PUT", f"/zones/{zone_id}/dns_records/{record_id}", json=data
        ).get("result", {})

    def delete_dns_record(self, zone_id: str, record_id: str) -> dict:
        return self._request(
            "DELETE", f"/zones/{zone_id}/dns_records/{record_id}"
        ).get("result", {})
