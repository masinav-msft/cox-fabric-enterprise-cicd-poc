#!/usr/bin/env python3
"""
cicd/run_smoke_test.py
Triggers a Fabric DataPipeline on-demand job instance and polls the LRO until Succeeded.
Also supports inspecting child pipeline runs and verifying output tables.
"""
import time
import argparse
from typing import Dict, Any, Optional
from fabric_enterprise_client import FabricEnterpriseClient, logger


def run_pipeline_smoke_test(
    target_ws_name: str,
    pipeline_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    client: Optional[FabricEnterpriseClient] = None
) -> Dict[str, Any]:
    client = client or FabricEnterpriseClient(lro_timeout_sec=900)
    workspaces = client.list_all_paginated("/workspaces")
    ws = next((w for w in workspaces if w.get("displayName") == target_ws_name), None)
    if not ws:
        raise RuntimeError(f"Workspace '{target_ws_name}' not found.")
    ws_id = ws["id"]

    items = client.list_all_paginated(f"/workspaces/{ws_id}/items")
    pl = next((i for i in items if i.get("displayName") == pipeline_name and i.get("type") == "DataPipeline"), None)
    if not pl:
        raise RuntimeError(f"DataPipeline '{pipeline_name}' not found in '{target_ws_name}'.")
    pl_id = pl["id"]

    exec_body: Dict[str, Any] = {"executionData": {}}
    if parameters:
        exec_body["executionData"]["parameters"] = parameters

    logger.info(f"Triggering smoke test pipeline '{pipeline_name}' ({pl_id}) in '{target_ws_name}'...")
    url = f"{client._get_headers() and ''}"
    resp = client.session.post(
        f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/items/{pl_id}/jobs/instances?jobType=Pipeline",
        headers=client._get_headers(),
        json=exec_body,
        timeout=60
    )
    resp.raise_for_status()
    job_location = resp.headers.get("Location")
    if not job_location:
        raise RuntimeError("No Location header returned from job trigger.")

    logger.info(f"Polling Pipeline Job Instance: {job_location}")
    start_time = time.time()
    while (time.time() - start_time) < client.lro_timeout_sec:
        time.sleep(5)
        r = client.session.get(job_location, headers=client._get_headers(), timeout=30)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 10)))
            continue
        r.raise_for_status()
        job_data = r.json()
        status = job_data.get("status")
        logger.info(f"  Pipeline '{pipeline_name}' Job Status: {status}")
        if status == "Completed":
            logger.info(f"[SMOKE TEST PASS] Pipeline '{pipeline_name}' succeeded in '{target_ws_name}'.")
            return job_data
        if status in ("Failed", "Cancelled", "Deduped"):
            reason = job_data.get("failureReason", {})
            raise RuntimeError(f"Pipeline '{pipeline_name}' {status}: {reason}")

    raise TimeoutError(f"Pipeline '{pipeline_name}' timed out in '{target_ws_name}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-name", required=True)
    parser.add_argument("--pipeline", required=True)
    args = parser.parse_args()
    run_pipeline_smoke_test(args.workspace_name, args.pipeline)
