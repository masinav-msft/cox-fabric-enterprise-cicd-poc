#!/usr/bin/env python3
"""
Enterprise Fabric Workspace Deployment Engine (fabric-cicd + REST API Item & ValueSet Engine)
1. Deploys VariableLibrary, Lakehouse, Notebook, DataPipeline, CopyJob in dependency order
2. Protects Stateful Items (Lakehouse, Warehouse, SQLDatabase) from accidental orphan deletion (GATE-09)
3. Activates target ValueSet ('QA' or 'PROD') on Var_GlobalConfig via REST PATCH with LRO polling (REQ-03)
"""
import base64
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from fabric_enterprise_client import FabricEnterpriseClient, logger

# Stateless item types safe for automatic orphan cleanup; Lakehouse/Warehouse/SQLDatabase are NEVER auto-deleted
STATELESS_ORPHAN_SAFE_TYPES = ["DataPipeline", "CopyJob", "Notebook", "Environment", "SparkJobDefinition"]
STATEFUL_PROTECTED_TYPES = ["Lakehouse", "Warehouse", "SQLDatabase"]
ORDERED_DEPLOY_TYPES = ["VariableLibrary", "Lakehouse", "Environment", "Notebook", "CopyJob", "DataPipeline"]


def _encode_b64(content_bytes: bytes) -> str:
    return base64.b64encode(content_bytes).decode("utf-8")


def _build_item_definition_parts(
    item_dir: Path,
    item_type: str,
    existing_map: Optional[Dict[tuple, str]] = None
) -> List[Dict[str, str]]:
    parts: List[Dict[str, str]] = []
    for file_path in sorted(item_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(item_dir).as_posix()
        raw_bytes = file_path.read_bytes()
        if item_type == "DataPipeline" and rel_path == "pipeline-content.json" and existing_map:
            text_content = raw_bytes.decode("utf-8")
            for (ref_name, ref_type), ref_id in existing_map.items():
                if ref_type == "DataPipeline":
                    text_content = text_content.replace(f'"referenceName": "{ref_name}"', f'"referenceName": "{ref_id}"')
            raw_bytes = text_content.encode("utf-8")
        parts.append({
            "path": rel_path,
            "payload": _encode_b64(raw_bytes),
            "payloadType": "InlineBase64"
        })
    return parts


def deploy_workspace(
    workspace_dir: str,
    target_ws_name: str,
    env: str,
    var_lib_name: str = "Var_GlobalConfig",
    prune_stateless_orphans: bool = False,
    use_fabric_cicd_lib: bool = True,
    client: Optional[FabricEnterpriseClient] = None
) -> Dict[str, Any]:
    client = client or FabricEnterpriseClient()
    ws_path = Path(workspace_dir)

    # 1. Resolve Target Workspace GUID via Paginated API
    all_workspaces = client.list_all_paginated("/workspaces")
    ws_obj = next((w for w in all_workspaces if w.get("displayName") == target_ws_name), None)
    if not ws_obj:
        raise RuntimeError(f"Target workspace '{target_ws_name}' not found.")
    ws_id = ws_obj["id"]
    logger.info(f"Deploying '{workspace_dir}' -> '{target_ws_name}' ({ws_id}) for environment '{env}'...")

    deployed_items: List[str] = []
    preserved_stateful: List[str] = []
    pruned_orphans: List[str] = []

    # 2. Discover local item folders
    local_items: Dict[tuple, Path] = {}
    for child in ws_path.iterdir():
        if child.is_dir() and "." in child.name:
            display_name, item_type = child.name.rsplit(".", 1)
            local_items[(display_name, item_type)] = child

    # Try official Microsoft fabric-cicd library first when running with standard credentials
    used_cicd_sdk = False
    if use_fabric_cicd_lib:
        try:
            from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items
            present_types = sorted({itype for (_, itype) in local_items.keys() if itype in [
                "VariableLibrary", "Lakehouse", "Warehouse", "Environment", "Notebook", "DataPipeline", "CopyJob", "SemanticModel", "Report"
            ]})
            if present_types:
                target_ws = FabricWorkspace(
                    workspace_id=ws_id,
                    environment=env,
                    repository_directory=str(ws_path.resolve()),
                    item_type_in_scope=present_types
                )
                publish_all_items(target_ws)
                used_cicd_sdk = True
                deployed_items.extend([f"{dn}.{it}" for (dn, it) in local_items.keys() if it in present_types])
                logger.info(f"[fabric-cicd] Published {len(deployed_items)} items to {target_ws_name}")
        except Exception as exc:
            logger.warning(f"fabric-cicd publish_all_items fallback to direct REST API: {exc}")

    # Direct Fabric Control-Plane REST deployment (ensures 100% deterministic deployment of VariableLibrary, Pipelines, CopyJobs, Notebooks)
    existing_items = client.list_all_paginated(f"/workspaces/{ws_id}/items")
    existing_map = {(i["displayName"], i["type"]): i["id"] for i in existing_items}

    for item_type in ORDERED_DEPLOY_TYPES:
        # Sort so utility pipelines (e.g. pl_00_*) deploy before parent domain pipelines
        sorted_local = sorted(local_items.items(), key=lambda kv: kv[0][0])
        for (display_name, itype), item_dir in sorted_local:
            if itype != item_type:
                continue
            item_key = (display_name, itype)
            if itype == "Lakehouse":
                if item_key not in existing_map:
                    logger.info(f"Creating Lakehouse '{display_name}' in '{target_ws_name}'...")
                    created = client.request("POST", f"/workspaces/{ws_id}/lakehouses", json_body={"displayName": display_name})
                    if created and "id" in created:
                        existing_map[item_key] = created["id"]
                else:
                    logger.info(f"Stateful Lakehouse '{display_name}' already exists ({existing_map[item_key]})")
                if f"{display_name}.{itype}" not in deployed_items:
                    deployed_items.append(f"{display_name}.{itype}")
                continue

            parts = _build_item_definition_parts(item_dir, itype, existing_map=existing_map)
            if item_key not in existing_map:
                logger.info(f"Creating {itype} '{display_name}' in '{target_ws_name}'...")
                body = {
                    "displayName": display_name,
                    "type": itype,
                    "definition": {"parts": parts}
                }
                created = client.request("POST", f"/workspaces/{ws_id}/items", json_body=body, poll_lro=True)
                if created and "id" in created:
                    existing_map[item_key] = created["id"]
            elif not used_cicd_sdk or itype in ("VariableLibrary", "CopyJob", "DataPipeline"):
                item_id = existing_map[item_key]
                logger.info(f"Updating {itype} '{display_name}' ({item_id}) in '{target_ws_name}'...")
                client.request(
                    "POST",
                    f"/workspaces/{ws_id}/items/{item_id}/updateDefinition?updateMetadata=true",
                    json_body={"definition": {"parts": parts}},
                    poll_lro=True
                )
            if f"{display_name}.{itype}" not in deployed_items:
                deployed_items.append(f"{display_name}.{itype}")

    # 3. Safe Orphan Cleanup (NEVER deletes Lakehouses, Warehouses, or SQL Databases - GATE-09)
    current_items = client.list_all_paginated(f"/workspaces/{ws_id}/items")
    for remote_item in current_items:
        r_name = remote_item.get("displayName")
        r_type = remote_item.get("type")
        r_id = remote_item.get("id")
        if (r_name, r_type) not in local_items:
            if r_type in STATEFUL_PROTECTED_TYPES or r_type == "SQLEndpoint":
                preserved_stateful.append(f"{r_name}.{r_type}")
                logger.info(f"[STATEFUL GUARDRAIL] Preserving stateful item '{r_name}.{r_type}' ({r_id}) from orphan deletion.")
            elif prune_stateless_orphans and r_type in STATELESS_ORPHAN_SAFE_TYPES:
                logger.info(f"[ORPHAN CLEANUP] Deleting stateless orphan '{r_name}.{r_type}' ({r_id})...")
                client.request("DELETE", f"/workspaces/{ws_id}/items/{r_id}")
                pruned_orphans.append(f"{r_name}.{r_type}")

    # 4. Activate Target ValueSet ('QA' or 'PROD') in Var_GlobalConfig via Fabric REST API PATCH (REQ-03)
    active_vs_result = "Default (DEV)"
    if (var_lib_name, "VariableLibrary") in local_items and env in ("QA", "PROD"):
        var_libs = client.list_all_paginated(f"/workspaces/{ws_id}/variableLibraries")
        vl = next((v for v in var_libs if v.get("displayName") == var_lib_name), None)
        if not vl:
            all_ws_items = client.list_all_paginated(f"/workspaces/{ws_id}/items")
            vl = next((v for v in all_ws_items if v.get("displayName") == var_lib_name and v.get("type") == "VariableLibrary"), None)
        if not vl:
            raise RuntimeError(f"Variable Library '{var_lib_name}' not found in workspace '{target_ws_name}'.")
        vl_id = vl["id"]
        logger.info(f"Activating ValueSet '{env}' on {var_lib_name} ({vl_id})...")
        client.request(
            method="PATCH",
            path_or_url=f"/workspaces/{ws_id}/variableLibraries/{vl_id}",
            json_body={"properties": {"activeValueSetName": env}},
            poll_lro=True
        )
        verified = client.request("GET", f"/workspaces/{ws_id}/variableLibraries/{vl_id}")
        active_vs = verified.get("properties", {}).get("activeValueSetName")
        if active_vs != env:
            raise RuntimeError(f"ValueSet activation mismatch: expected '{env}', got '{active_vs}'")
        active_vs_result = active_vs
        logger.info(f"[VERIFIED] {var_lib_name}.activeValueSetName == '{active_vs}' in {target_ws_name}")

    return {
        "workspaceId": ws_id,
        "workspaceName": target_ws_name,
        "environment": env,
        "deployedItems": deployed_items,
        "preservedStatefulItems": preserved_stateful,
        "prunedStatelessOrphans": pruned_orphans,
        "activeValueSetName": active_vs_result
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-dir", required=True)
    parser.add_argument("--target-workspace-name", required=True)
    parser.add_argument("--environment", required=True, choices=["DEV", "QA", "PROD", "CANARY"])
    parser.add_argument("--prune-stateless-orphans", action="store_true")
    parser.add_argument("--rest-only", action="store_true")
    args = parser.parse_args()
    deploy_workspace(
        args.workspace_dir,
        args.target_workspace_name,
        args.environment,
        prune_stateless_orphans=args.prune_stateless_orphans,
        use_fabric_cicd_lib=not args.rest_only
    )
