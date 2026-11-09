#!/usr/bin/env python3
"""
cicd/provision_ephemeral_canary.py
Addresses REQ-05 & Issue 20 (Viktor, Matthew & Amudha: Ephemeral CI/CD Testing Without Breaking QA/Prod).
Dynamically provisions or tears down an isolated 2-workspace Canary pair:
  - FAB_CANARY_PR{N}_RAW (Upstream Stage 1 Raw Workspace + Lakehouse)
  - FAB_CANARY_PR{N}_FIN (Downstream Stage 2 Domain Workspace + Lakehouse)
"""
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Any
from fabric_enterprise_client import FabricEnterpriseClient, logger
from deploy_workspace import deploy_workspace


def provision_canary_pair(
    pr_number: str,
    topology_path: str = "config/enterprise-topology.json",
    run_deploy_and_test: bool = False
) -> Dict[str, Any]:
    topology = json.loads(Path(topology_path).read_text(encoding="utf-8"))
    ent = topology["enterpriseSettings"]
    cap_id = ent["nonProdCapacityId"]
    spn_obj_id = ent["spnObjectId"]

    client = FabricEnterpriseClient()
    raw_ws_name = f"FAB_CANARY_PR{pr_number}_RAW"
    fin_ws_name = f"FAB_CANARY_PR{pr_number}_FIN"

    existing = {w["displayName"]: w["id"] for w in client.list_all_paginated("/workspaces")}

    created_ids = {}
    for ws_name, desc in [
        (raw_ws_name, f"Ephemeral PR #{pr_number} Upstream Raw Canary Workspace"),
        (fin_ws_name, f"Ephemeral PR #{pr_number} Downstream Finance Canary Workspace")
    ]:
        if ws_name not in existing:
            logger.info(f"[CANARY] Creating ephemeral workspace '{ws_name}' on capacity {cap_id}...")
            res = client.request("POST", "/workspaces", json_body={
                "displayName": ws_name,
                "description": desc,
                "capacityId": cap_id
            })
            ws_id = res["id"]
        else:
            ws_id = existing[ws_name]
            logger.info(f"[CANARY] Reusing existing ephemeral workspace '{ws_name}' ({ws_id})")

        created_ids[ws_name] = ws_id
        # Grant SPN Admin role
        roles = client.list_all_paginated(f"/workspaces/{ws_id}/roleAssignments")
        if not any(r.get("principal", {}).get("id") == spn_obj_id for r in roles):
            client.request("POST", f"/workspaces/{ws_id}/roleAssignments", json_body={
                "principal": {"id": spn_obj_id, "type": "ServicePrincipal"},
                "role": "Admin"
            })

    # Create Lakehouses in Canary pair
    raw_ws_id = created_ids[raw_ws_name]
    fin_ws_id = created_ids[fin_ws_name]

    raw_lhs = {l["displayName"]: l["id"] for l in client.list_all_paginated(f"/workspaces/{raw_ws_id}/lakehouses")}
    if "lh_d365_raw" not in raw_lhs:
        lh = client.request("POST", f"/workspaces/{raw_ws_id}/lakehouses", json_body={"displayName": "lh_d365_raw"})
        raw_lh_id = lh["id"]
    else:
        raw_lh_id = raw_lhs["lh_d365_raw"]

    fin_lhs = {l["displayName"]: l["id"] for l in client.list_all_paginated(f"/workspaces/{fin_ws_id}/lakehouses")}
    if "lh_d365_silver_gl" not in fin_lhs:
        lh = client.request("POST", f"/workspaces/{fin_ws_id}/lakehouses", json_body={"displayName": "lh_d365_silver_gl"})
        fin_lh_id = lh["id"]
    else:
        fin_lh_id = fin_lhs["lh_d365_silver_gl"]

    if run_deploy_and_test:
        logger.info(f"[CANARY] Deploying Finance artifacts into '{fin_ws_name}'...")
        deploy_workspace(
            workspace_dir="workspace/DP_FinanceAndAccounting",
            target_ws_name=fin_ws_name,
            env="CANARY",
            use_fabric_cicd_lib=False,
            client=client
        )

    logger.info(f"[CANARY READY] Raw={raw_ws_name} ({raw_ws_id}), Fin={fin_ws_name} ({fin_ws_id})")
    return {
        "rawWorkspaceName": raw_ws_name,
        "rawWorkspaceId": raw_ws_id,
        "rawLakehouseId": raw_lh_id,
        "finWorkspaceName": fin_ws_name,
        "finWorkspaceId": fin_ws_id,
        "finLakehouseId": fin_lh_id
    }


def teardown_canary_pair(pr_number: str) -> None:
    client = FabricEnterpriseClient()
    raw_ws_name = f"FAB_CANARY_PR{pr_number}_RAW"
    fin_ws_name = f"FAB_CANARY_PR{pr_number}_FIN"
    existing = {w["displayName"]: w["id"] for w in client.list_all_paginated("/workspaces")}

    for ws_name in (fin_ws_name, raw_ws_name):
        if ws_name in existing:
            ws_id = existing[ws_name]
            logger.info(f"[CANARY TEARDOWN] Deleting ephemeral workspace '{ws_name}' ({ws_id})...")
            client.request("DELETE", f"/workspaces/{ws_id}")
            logger.info(f"[CANARY TEARDOWN] Deleted '{ws_name}'.")
        else:
            logger.info(f"[CANARY TEARDOWN] Workspace '{ws_name}' already absent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=["provision", "teardown"])
    parser.add_argument("--pr-number", required=True)
    parser.add_argument("--topology", default="config/enterprise-topology.json")
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()
    if args.action == "provision":
        provision_canary_pair(args.pr_number, args.topology, run_deploy_and_test=args.deploy)
    else:
        teardown_canary_pair(args.pr_number)
