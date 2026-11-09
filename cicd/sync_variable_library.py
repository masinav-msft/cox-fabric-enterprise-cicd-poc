#!/usr/bin/env python3
"""
Auto-Resolves Workspace, Lakehouse, SQL Analytics Endpoint, and Connection GUIDs
for ALL domains defined in config/enterprise-topology.json using paginated Fabric REST APIs.
Addresses REQ-01, REQ-02, REQ-03 (Eliminates 35-40 manual GUID copy-paste across Dev/QA/Prod).
"""
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any
from fabric_enterprise_client import FabricEnterpriseClient, logger


def find_by_name(items: List[Dict[str, Any]], display_name: str, entity_label: str) -> Dict[str, Any]:
    for item in items:
        if item.get("displayName") == display_name:
            return item
    raise ValueError(
        f"[{entity_label}] '{display_name}' not found in Fabric tenant (searched {len(items)} paginated items)."
    )


def resolve_domain_environment(
    client: FabricEnterpriseClient,
    topology: Dict[str, Any],
    domain_cfg: Dict[str, Any],
    env: str,
    all_workspaces: List[Dict[str, Any]],
    all_connections: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    ent = topology["enterpriseSettings"]
    env_global = ent["environments"][env]
    env_dom = domain_cfg["environments"][env]

    raw_ws = find_by_name(all_workspaces, env_dom["upstreamRawWorkspaceName"], "Upstream Raw Workspace")
    silver_ws = find_by_name(all_workspaces, env_dom["targetWorkspaceName"], "Target Domain Workspace")
    sql_conn = find_by_name(all_connections, env_dom["sqlEndpointConnectionName"], "SQL Connection")
    kv_conn = find_by_name(all_connections, ent.get("keyVaultWebConnectionName", "CONN_KEYVAULT_PIPELINE_WEB"), "KeyVault Web Connection")
    graph_conn = find_by_name(all_connections, ent.get("graphWebConnectionName", "CONN_GRAPH_PIPELINE_WEB"), "Graph Web Connection")

    # Paginated fetch of Lakehouses in both Workspaces
    raw_lhs = client.list_all_paginated(f"/workspaces/{raw_ws['id']}/lakehouses")
    silver_lhs = client.list_all_paginated(f"/workspaces/{silver_ws['id']}/lakehouses")

    raw_lh = find_by_name(raw_lhs, env_dom["rawLakehouseName"], "Raw Lakehouse")
    silver_lh = find_by_name(silver_lhs, env_dom["silverLakehouseName"], "Silver Lakehouse")

    # Fetch SQL Analytics Endpoint properties (Server FQDN + SQL Endpoint GUID)
    raw_lh_detail = client.request("GET", f"/workspaces/{raw_ws['id']}/lakehouses/{raw_lh['id']}")
    silver_lh_detail = client.request("GET", f"/workspaces/{silver_ws['id']}/lakehouses/{silver_lh['id']}")

    raw_sql_props = raw_lh_detail.get("properties", {}).get("sqlEndpointProperties", {})
    silver_sql_props = silver_lh_detail.get("properties", {}).get("sqlEndpointProperties", {})

    return [
        {"name": "v_env_name",                 "type": "String", "value": env},
        {"name": "v_raw_workspace_id",         "type": "String", "value": raw_ws["id"]},
        {"name": "v_raw_lakehouse_id",         "type": "String", "value": raw_lh["id"]},
        {"name": "v_raw_lakehouse_name",       "type": "String", "value": raw_lh["displayName"]},
        {"name": "v_raw_sql_endpoint_server",  "type": "String", "value": raw_sql_props.get("connectionString", "")},
        {"name": "v_raw_sql_endpoint_id",      "type": "String", "value": raw_sql_props.get("id", "")},
        {"name": "v_raw_sql_connection_id",    "type": "String", "value": sql_conn["id"]},
        {"name": "v_silver_workspace_id",      "type": "String", "value": silver_ws["id"]},
        {"name": "v_silver_lakehouse_id",      "type": "String", "value": silver_lh["id"]},
        {"name": "v_silver_lakehouse_name",    "type": "String", "value": silver_lh["displayName"]},
        {"name": "v_silver_sql_endpoint_id",   "type": "String", "value": silver_sql_props.get("id", "")},
        {"name": "v_key_vault_uri",            "type": "String", "value": env_global["keyVaultUri"]},
        {"name": "v_spn_secret_name",          "type": "String", "value": ent.get("spnSecretName", "fabric-cicd-spn-secret")},
        {"name": "v_kv_web_connection_id",     "type": "String", "value": kv_conn["id"]},
        {"name": "v_graph_web_connection_id",  "type": "String", "value": graph_conn["id"]},
        {"name": "v_tenant_id",                "type": "String", "value": ent["tenantId"]},
        {"name": "v_spn_client_id",            "type": "String", "value": ent["spnClientId"]},
        {"name": "v_alert_sender_mailbox",     "type": "String", "value": ent.get("alertSenderMailbox", "admin@MngEnvMCAP927255.onmicrosoft.com")},
        {"name": "v_alert_notification_email", "type": "String", "value": env_global["alertRecipients"]}
    ]


def resolve_gold_environment(
    client: FabricEnterpriseClient,
    topology: Dict[str, Any],
    gold_cfg: Dict[str, Any],
    env: str,
    all_workspaces: List[Dict[str, Any]],
    all_connections: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    ent = topology["enterpriseSettings"]
    env_global = ent["environments"][env]
    env_dom = gold_cfg["environments"][env]

    fin_ws = find_by_name(all_workspaces, env_dom["upstreamFinanceWorkspaceName"], "Upstream Finance Workspace")
    fleet_ws = find_by_name(all_workspaces, env_dom["upstreamFleetWorkspaceName"], "Upstream Fleet Workspace")
    gold_ws = find_by_name(all_workspaces, env_dom["targetWorkspaceName"], "Target Gold Workspace")
    sql_conn = find_by_name(all_connections, env_dom["sqlEndpointConnectionName"], "SQL Connection")
    kv_conn = find_by_name(all_connections, ent.get("keyVaultWebConnectionName", "CONN_KEYVAULT_PIPELINE_WEB"), "KeyVault Web Connection")
    graph_conn = find_by_name(all_connections, ent.get("graphWebConnectionName", "CONN_GRAPH_PIPELINE_WEB"), "Graph Web Connection")

    fin_lhs = client.list_all_paginated(f"/workspaces/{fin_ws['id']}/lakehouses")
    fleet_lhs = client.list_all_paginated(f"/workspaces/{fleet_ws['id']}/lakehouses")
    gold_lhs = client.list_all_paginated(f"/workspaces/{gold_ws['id']}/lakehouses")

    fin_lh = find_by_name(fin_lhs, env_dom["financeLakehouseName"], "Finance Silver Lakehouse")
    fleet_lh = find_by_name(fleet_lhs, env_dom["fleetLakehouseName"], "Fleet Silver Lakehouse")
    gold_lh = find_by_name(gold_lhs, env_dom["goldLakehouseName"], "Enterprise Gold Lakehouse")

    fin_detail = client.request("GET", f"/workspaces/{fin_ws['id']}/lakehouses/{fin_lh['id']}")
    gold_detail = client.request("GET", f"/workspaces/{gold_ws['id']}/lakehouses/{gold_lh['id']}")

    fin_sql = fin_detail.get("properties", {}).get("sqlEndpointProperties", {})
    gold_sql = gold_detail.get("properties", {}).get("sqlEndpointProperties", {})

    return [
        {"name": "v_env_name",                 "type": "String", "value": env},
        {"name": "v_raw_workspace_id",         "type": "String", "value": fin_ws["id"]},
        {"name": "v_raw_lakehouse_id",         "type": "String", "value": fin_lh["id"]},
        {"name": "v_raw_lakehouse_name",       "type": "String", "value": fin_lh["displayName"]},
        {"name": "v_raw_sql_endpoint_server",  "type": "String", "value": fin_sql.get("connectionString", "")},
        {"name": "v_raw_sql_endpoint_id",      "type": "String", "value": fin_sql.get("id", "")},
        {"name": "v_raw_sql_connection_id",    "type": "String", "value": sql_conn["id"]},
        {"name": "v_fleet_workspace_id",       "type": "String", "value": fleet_ws["id"]},
        {"name": "v_fleet_lakehouse_id",       "type": "String", "value": fleet_lh["id"]},
        {"name": "v_silver_workspace_id",      "type": "String", "value": gold_ws["id"]},
        {"name": "v_silver_lakehouse_id",      "type": "String", "value": gold_lh["id"]},
        {"name": "v_silver_lakehouse_name",    "type": "String", "value": gold_lh["displayName"]},
        {"name": "v_silver_sql_endpoint_id",   "type": "String", "value": gold_sql.get("id", "")},
        {"name": "v_key_vault_uri",            "type": "String", "value": env_global["keyVaultUri"]},
        {"name": "v_spn_secret_name",          "type": "String", "value": ent.get("spnSecretName", "fabric-cicd-spn-secret")},
        {"name": "v_kv_web_connection_id",     "type": "String", "value": kv_conn["id"]},
        {"name": "v_graph_web_connection_id",  "type": "String", "value": graph_conn["id"]},
        {"name": "v_tenant_id",                "type": "String", "value": ent["tenantId"]},
        {"name": "v_spn_client_id",            "type": "String", "value": ent["spnClientId"]},
        {"name": "v_alert_sender_mailbox",     "type": "String", "value": ent.get("alertSenderMailbox", "admin@MngEnvMCAP927255.onmicrosoft.com")},
        {"name": "v_alert_notification_email", "type": "String", "value": env_global["alertRecipients"]}
    ]


def sync_all(topology_path: str, domain_filter: str = "ALL", envs: List[str] = None, update_dev_defaults: bool = False) -> Dict[str, Any]:
    if envs is None:
        envs = ["QA", "PROD"]
    topology = json.loads(Path(topology_path).read_text(encoding="utf-8"))
    client = FabricEnterpriseClient()

    all_workspaces = client.list_all_paginated("/workspaces")
    all_connections = client.list_all_paginated("/connections")
    summary: Dict[str, Any] = {}

    all_stage_configs = [
        ("stage2", d) for d in topology.get("stage2_domainWorkspaces", [])
    ] + [
        ("stage3", g) for g in topology.get("stage3_goldWorkspaces", [])
    ]

    for stage_type, cfg in all_stage_configs:
        dkey = cfg["domainKey"]
        if domain_filter != "ALL" and dkey != domain_filter:
            continue

        var_lib_root = Path(cfg["folderPath"]) / f"{cfg['variableLibraryName']}.VariableLibrary"
        var_lib_dir = var_lib_root / "valueSets"
        var_lib_dir.mkdir(parents=True, exist_ok=True)
        summary[dkey] = {}

        target_envs = list(envs)
        if update_dev_defaults and "DEV" not in target_envs:
            target_envs.insert(0, "DEV")

        for env in target_envs:
            logger.info(f"Resolving {dkey} -> {env}...")
            if stage_type == "stage2":
                resolved_vars = resolve_domain_environment(client, topology, cfg, env, all_workspaces, all_connections)
            else:
                resolved_vars = resolve_gold_environment(client, topology, cfg, env, all_workspaces, all_connections)

            if env == "DEV" and update_dev_defaults:
                vars_json_path = var_lib_root / "variables.json"
                vars_payload = {
                    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/variableLibrary/definition/variables/1.0.0/schema.json",
                    "variables": [
                        {"name": v["name"], "note": f"Auto-resolved by sync_variable_library.py ({env})", "type": v["type"], "value": v["value"]}
                        for v in resolved_vars
                    ]
                }
                vars_json_path.write_text(json.dumps(vars_payload, indent=2), encoding="utf-8")
                logger.info(f"[OK] Wrote {len(resolved_vars)} DEV default variables to {vars_json_path}")

            if env in envs and env != "DEV":
                overrides = [{"name": v["name"], "value": v["value"]} for v in resolved_vars]
                payload = {
                    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/variableLibrary/definition/valueSet/1.0.0/schema.json",
                    "name": env,
                    "variableOverrides": overrides
                }
                out_file = var_lib_dir / f"{env}.json"
                out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                logger.info(f"[OK] Wrote {len(overrides)} verified GUIDs/endpoints to {out_file}")
                summary[dkey][env] = len(overrides)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Auto-sync Variable Library ValueSets across all Cox domains.")
    parser.add_argument("--topology", default="config/enterprise-topology.json")
    parser.add_argument("--domain", default="ALL", help="Specific domainKey or ALL")
    parser.add_argument("--envs", nargs="+", default=["QA", "PROD"])
    parser.add_argument("--update-dev-defaults", action="store_true", help="Also populate variables.json with DEV resolved values")
    args = parser.parse_args()
    sync_all(args.topology, args.domain, args.envs, args.update_dev_defaults)


if __name__ == "__main__":
    main()
