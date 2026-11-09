#!/usr/bin/env python3
"""
Pre-Flight Production Gate (Addresses REQ-07, GATE-08, Issue 6, Issue 14):
Verifies that the CI/CD Service Principal has access to:
  1. Target Fabric Workspace (Admin or Member role required for deployment)
  2. Every Connection GUID referenced in valueSets/{ENV}.json or variables.json
Fails fast BEFORE touching any production items if an admin forgot to share a connection.
"""
import json
import sys
import argparse
from pathlib import Path
from typing import List
from fabric_enterprise_client import FabricEnterpriseClient, logger


def check_preflight_errors(
    client: FabricEnterpriseClient,
    workspace_dir: Path,
    target_ws_name: str,
    env: str,
    spn_principal_id: str
) -> List[str]:
    errors: List[str] = []

    # 1. Verify Target Workspace Exists & SPN has Role Assignment
    workspaces = client.list_all_paginated("/workspaces")
    ws = next((w for w in workspaces if w.get("displayName") == target_ws_name), None)
    if not ws:
        errors.append(f"[PREFLIGHT FAIL] Target workspace '{target_ws_name}' not found.")
        return errors

    ws_id = ws["id"]
    logger.info(f"[PREFLIGHT] Found workspace '{target_ws_name}' ({ws_id})")

    ws_roles = client.list_all_paginated(f"/workspaces/{ws_id}/roleAssignments")
    has_ws_role = any(r.get("principal", {}).get("id") == spn_principal_id for r in ws_roles)
    if not has_ws_role:
        errors.append(
            f"Workspace '{target_ws_name}' ({ws_id}) does not have a roleAssignment for SPN Object ID {spn_principal_id}."
        )
    else:
        logger.info(f"[PREFLIGHT OK] Verified SPN access on workspace '{target_ws_name}' ({ws_id})")

    # 2. Inspect ValueSet (or DEV variables.json) Connection GUIDs
    if env == "DEV":
        target_files = list(workspace_dir.rglob("*.VariableLibrary/variables.json"))
        list_key = "variables"
    else:
        target_files = list(workspace_dir.rglob(f"*.VariableLibrary/valueSets/{env}.json"))
        list_key = "variableOverrides"

    for vs_file in target_files:
        data = json.loads(vs_file.read_text(encoding="utf-8"))
        for override in data.get(list_key, []):
            if "connection_id" in override["name"].lower():
                conn_id = override["value"]
                try:
                    conn = client.request("GET", f"/connections/{conn_id}")
                    roles = client.list_all_paginated(f"/connections/{conn_id}/roleAssignments")
                    has_role = any(r.get("principal", {}).get("id") == spn_principal_id for r in roles)
                    if not has_role:
                        errors.append(
                            f"Connection '{conn.get('displayName', conn_id)}' ({conn_id}) does not have an explicit "
                            f"roleAssignment for SPN Object ID {spn_principal_id}."
                        )
                    else:
                        logger.info(f"[PREFLIGHT OK] Verified SPN access on connection {conn.get('displayName', conn_id)} ({conn_id})")
                except Exception as exc:
                    errors.append(f"Cannot access Connection GUID {conn_id} in {vs_file.name}: {exc}")

    return errors


def validate_preflight(workspace_dir: Path, target_ws_name: str, env: str, spn_principal_id: str) -> None:
    client = FabricEnterpriseClient()
    errors = check_preflight_errors(client, workspace_dir, target_ws_name, env, spn_principal_id)
    if errors:
        logger.error("PRE-FLIGHT RBAC VALIDATION FAILED:")
        for e in errors:
            logger.error(f"  - {e}")
        sys.exit(1)
    logger.info(f"[PREFLIGHT PASS] All Workspace & Connection permissions verified for {target_ws_name} ({env}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-dir", required=True)
    parser.add_argument("--target-workspace-name", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--spn-object-id", required=True)
    args = parser.parse_args()
    validate_preflight(Path(args.workspace_dir), args.target_workspace_name, args.environment, args.spn_object_id)
