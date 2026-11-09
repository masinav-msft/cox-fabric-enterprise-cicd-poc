#!/usr/bin/env python3
"""
Production-Hardened Microsoft Fabric REST API Client for Cox Enterprises.
Features:
  1. Automatic OAuth2 Token Refresh via Azure Identity (OIDC / SPN / CLI) or FABRIC_TOKEN env
  2. Full continuationToken / continuationUri Pagination across all list endpoints
  3. Exponential Backoff & HTTP 429 Retry-After header enforcement (500 RPM FabCon scale)
  4. Asynchronous HTTP 202 Accepted Long-Running Operation (LRO) state polling
"""
import os
import time
import logging
import subprocess
import requests
from typing import Dict, List, Any, Optional
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FabricEnterpriseClient")

FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"


class FabricEnterpriseClient:
    def __init__(self, max_retries: int = 6, lro_timeout_sec: int = 1800, session: Optional[requests.Session] = None):
        self.credential = None
        self.max_retries = max_retries
        self.lro_timeout_sec = lro_timeout_sec
        self.session = session or requests.Session()
        self._token: Optional[str] = os.environ.get("FABRIC_TOKEN")
        self._token_expires_on: float = (time.time() + 3000) if self._token else 0.0

    def _acquire_token(self) -> str:
        env_tok = os.environ.get("FABRIC_TOKEN")
        if env_tok:
            self._token = env_tok
            self._token_expires_on = time.time() + 3000
            return env_tok

        # Fallback: try DefaultAzureCredential when running in GitHub Actions OIDC or SPN env
        if os.environ.get("AZURE_CLIENT_ID") or os.environ.get("MSI_ENDPOINT") or os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
            if self.credential is None:
                self.credential = DefaultAzureCredential()
            token_obj = self.credential.get_token(FABRIC_SCOPE)
            self._token = token_obj.token
            self._token_expires_on = float(token_obj.expires_on)
            return self._token

        # Fast local CLI token acquisition on Windows/Linux
        try:
            az_cmd = "az.cmd" if os.name == "nt" else "az"
            res = subprocess.run(
                [az_cmd, "account", "get-access-token", "--resource", "https://api.fabric.microsoft.com", "--query", "accessToken", "-o", "tsv"],
                capture_output=True, text=True, timeout=20, check=True
            )
            tok = res.stdout.strip()
            if tok:
                self._token = tok
                self._token_expires_on = time.time() + 3000
                return tok
        except Exception:
            pass

        if self.credential is None:
            self.credential = DefaultAzureCredential()
        token_obj = self.credential.get_token(FABRIC_SCOPE)
        self._token = token_obj.token
        self._token_expires_on = float(token_obj.expires_on)
        return self._token

    def _get_headers(self) -> Dict[str, str]:
        now = time.time()
        if not self._token or now >= (self._token_expires_on - 120):
            self._acquire_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "x-ms-fabric-skill": "git-integration-operations-cli"
        }

    def request(
        self,
        method: str,
        path_or_url: str,
        json_body: Any = None,
        params: Optional[Dict[str, Any]] = None,
        poll_lro: bool = True
    ) -> Dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else f"{FABRIC_API_BASE}{path_or_url}"
        attempt = 0

        while True:
            attempt += 1
            resp = self.session.request(
                method=method,
                url=url,
                headers=self._get_headers(),
                json=json_body,
                params=params,
                timeout=60
            )

            # Handle HTTP 429 Too Many Requests or Transient 5xx
            if resp.status_code in (429, 502, 503, 504):
                if attempt > self.max_retries:
                    resp.raise_for_status()
                retry_after = int(resp.headers.get("Retry-After", min(2 ** attempt, 60)))
                logger.warning(
                    f"HTTP {resp.status_code} on {method} {url}. Backing off {retry_after}s (attempt {attempt}/{self.max_retries})..."
                )
                time.sleep(retry_after)
                continue

            # Handle Asynchronous HTTP 202 Accepted (Long-Running Operation)
            if resp.status_code == 202 and poll_lro:
                op_url = resp.headers.get("Location")
                op_id = resp.headers.get("x-ms-operation-id")
                retry_interval = int(resp.headers.get("Retry-After", 5))
                if not op_url and op_id:
                    op_url = f"{FABRIC_API_BASE}/operations/{op_id}"
                if op_url:
                    return self.poll_operation(op_url, initial_wait=retry_interval)
                return {"status": "AcceptedNoLocation"}

            resp.raise_for_status()
            if not resp.text or resp.status_code == 204:
                return {}
            return resp.json()

    def poll_operation(self, operation_url: str, initial_wait: int = 5) -> Dict[str, Any]:
        """Polls a Fabric LRO endpoint until status is Succeeded, Completed, Failed, or Cancelled."""
        logger.info(f"Polling Fabric LRO: {operation_url}")
        start_time = time.time()
        wait_sec = max(initial_wait, 1)

        while (time.time() - start_time) < self.lro_timeout_sec:
            time.sleep(wait_sec)
            resp = self.session.get(operation_url, headers=self._get_headers(), timeout=30)
            if resp.status_code == 429:
                wait_sec = int(resp.headers.get("Retry-After", 10))
                continue
            resp.raise_for_status()
            if not resp.text:
                return {"status": "Succeeded"}
            data = resp.json()
            status = data.get("status", "Succeeded")
            pct = data.get("percentComplete", 100)
            logger.info(f"  LRO Status: {status} ({pct}%)")

            if status in ("Succeeded", "Completed"):
                return data
            if status in ("Failed", "Cancelled", "Deduped"):
                error_msg = data.get("error") or data.get("failureReason") or data
                raise RuntimeError(f"Fabric LRO {status} at {operation_url}: {error_msg}")
            wait_sec = int(resp.headers.get("Retry-After", 5))

        raise TimeoutError(f"Timed out after {self.lro_timeout_sec}s waiting for LRO: {operation_url}")

    def list_all_paginated(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Loops across continuationUri / continuationToken until all pages are retrieved."""
        results: List[Dict[str, Any]] = []
        next_url: Optional[str] = path if path.startswith("http") else f"{FABRIC_API_BASE}{path}"
        query_params = dict(params) if params else None

        while next_url:
            data = self.request("GET", next_url, params=query_params, poll_lro=False)
            query_params = None
            page_items = data.get("value", [])
            results.extend(page_items)

            next_url = data.get("continuationUri")
            token = data.get("continuationToken")
            if not next_url and token:
                base_path = path if path.startswith("http") else f"{FABRIC_API_BASE}{path}"
                sep = "&" if "?" in base_path else "?"
                next_url = f"{base_path}{sep}continuationToken={token}"

        return results
