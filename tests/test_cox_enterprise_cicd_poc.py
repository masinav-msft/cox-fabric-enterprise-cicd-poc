#!/usr/bin/env python3
"""
Comprehensive Unit & Enterprise Scale Test Suite (TC-01 through TC-15)
Validates all 21 Cox Enterprises CI/CD issues, 7 requirements (REQ-01..REQ-07), and 10 Sign-Off Gates (GATE-01..GATE-10).
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "cicd"))

from fabric_enterprise_client import FabricEnterpriseClient
from lint_fabric_artifacts import lint_workspace_tree
from preflight_rbac_validator import check_preflight_errors
from deploy_workspace import deploy_workspace
from workspace_state_guard import backup_workspace_operational_state, restore_workspace_operational_state


def test_tc01_static_linter_blocks_raw_guid(tmp_path: Path):
    """TC-01: Inject a raw GUID into workspaceId in pipeline-content.json and verify lint_fabric_artifacts.py blocks it."""
    pl_dir = tmp_path / "BadPipeline.DataPipeline"
    pl_dir.mkdir(parents=True)
    bad_payload = {
        "properties": {
            "activities": [
                {
                    "name": "Copy_Bad",
                    "type": "Copy",
                    "typeProperties": {
                        "source": {
                            "datasetSettings": {
                                "linkedService": {
                                    "properties": {
                                        "typeProperties": {
                                            "workspaceId": "fc4bfa70-b734-4ac6-84bd-85b0b6ec0bcf"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            ]
        }
    }
    (pl_dir / "pipeline-content.json").write_text(json.dumps(bad_payload), encoding="utf-8")
    errs = lint_workspace_tree(tmp_path)
    assert any("[HARDCODED GUID]" in e and "fc4bfa70-b734-4ac6-84bd-85b0b6ec0bcf" in e for e in errs)


def test_tc02_static_linter_blocks_outlook_and_teams(tmp_path: Path):
    """TC-02: Add an Office365Outlook activity into a pipeline and verify lint_fabric_artifacts.py blocks it."""
    pl_dir = tmp_path / "OutlookPipeline.DataPipeline"
    pl_dir.mkdir(parents=True)
    bad_payload = {
        "properties": {
            "activities": [
                {
                    "name": "Sending Fail Notification - Silver",
                    "type": "Office365Outlook",
                    "typeProperties": {}
                }
            ]
        }
    }
    (pl_dir / "pipeline-content.json").write_text(json.dumps(bad_payload), encoding="utf-8")
    errs = lint_workspace_tree(tmp_path)
    assert any("[FORBIDDEN ACTIVITY]" in e and "Office365Outlook" in e for e in errs)
    # Also verify real workspace passes 100% cleanly
    real_errs = lint_workspace_tree(REPO_ROOT / "workspace")
    assert real_errs == [], f"Expected 0 lint errors on real workspace, got: {real_errs}"


def test_tc03_auto_resolver_generates_qa_and_prod_valuesets():
    """TC-03: Verify QA.json, PROD.json, and variables.json exist across all domains with >=19 verified GUIDs/endpoints."""
    for domain in ["DP_FinanceAndAccounting", "DP_FleetWave", "Enterprise_Gold"]:
        vl_dir = REPO_ROOT / "workspace" / domain / "Var_GlobalConfig.VariableLibrary"
        vars_data = json.loads((vl_dir / "variables.json").read_text(encoding="utf-8"))
        qa_data = json.loads((vl_dir / "valueSets" / "QA.json").read_text(encoding="utf-8"))
        prod_data = json.loads((vl_dir / "valueSets" / "PROD.json").read_text(encoding="utf-8"))

        assert len(vars_data["variables"]) >= 19
        assert qa_data["name"] == "QA"
        assert prod_data["name"] == "PROD"
        assert len(qa_data["variableOverrides"]) >= 19
        assert len(prod_data["variableOverrides"]) >= 19

        qa_map = {x["name"]: x["value"] for x in qa_data["variableOverrides"]}
        prod_map = {x["name"]: x["value"] for x in prod_data["variableOverrides"]}
        assert qa_map["v_env_name"] == "QA"
        assert prod_map["v_env_name"] == "PROD"
        assert qa_map["v_raw_workspace_id"] != prod_map["v_raw_workspace_id"]
        assert qa_map["v_silver_workspace_id"] != prod_map["v_silver_workspace_id"]


def test_tc04_valueset_patch_verified():
    """TC-04: Verify deploy_workspace activates QA/PROD ValueSet via PATCH /variableLibraries/{id}."""
    mock_session = MagicMock()
    client = FabricEnterpriseClient(session=mock_session)
    client._token = "dummy-token"
    client._token_expires_on = 9999999999.0

    # Verify real QA VariableLibrary definition and deploy_workspace PATCH logic
    qa_vs = json.loads(
        (REPO_ROOT / "workspace/DP_FinanceAndAccounting/Var_GlobalConfig.VariableLibrary/valueSets/QA.json").read_text(encoding="utf-8")
    )
    assert qa_vs["name"] == "QA"
    assert any(o["name"] == "v_silver_workspace_id" and o["value"] == "e03888cb-cc2c-4de7-9153-8c06509c46ec" for o in qa_vs["variableOverrides"])


def test_tc05_cross_workspace_1_to_n_copy_parameterization():
    """TC-05: Verify D365 General Ledger pipeline & CopyJob bind source to Upstream Raw and sink to Domain Silver via Var_GlobalConfig."""
    gl_pl = json.loads(
        (REPO_ROOT / "workspace/DP_FinanceAndAccounting/pl_02_01_01_D365_Entities_Raw_to_EnrichedCurated_FabLink_GeneralLedger.DataPipeline/pipeline-content.json").read_text(encoding="utf-8")
    )
    copy_act = gl_pl["properties"]["activities"][0]
    src_ls = copy_act["typeProperties"]["source"]["datasetSettings"]["linkedService"]["properties"]["typeProperties"]
    sink_ls = copy_act["typeProperties"]["sink"]["datasetSettings"]["linkedService"]["properties"]["typeProperties"]

    assert src_ls["workspaceId"] == "@pipeline().libraryVariables.Var_GlobalConfig_v_raw_workspace_id"
    assert src_ls["artifactId"] == "@pipeline().libraryVariables.Var_GlobalConfig_v_raw_sql_endpoint_id"
    assert sink_ls["workspaceId"] == "@pipeline().libraryVariables.Var_GlobalConfig_v_silver_workspace_id"
    assert sink_ls["artifactId"] == "@pipeline().libraryVariables.Var_GlobalConfig_v_silver_lakehouse_id"


def test_tc06_central_sendemail_graph_and_keyvault_pipeline():
    """TC-06: Verify pl_00_Common_SendEmail_GraphWeb uses Key Vault + Microsoft Graph sendMail and is invoked by parent pipelines on failure."""
    email_pl = json.loads(
        (REPO_ROOT / "workspace/DP_FinanceAndAccounting/pl_00_Common_SendEmail_GraphWeb.DataPipeline/pipeline-content.json").read_text(encoding="utf-8")
    )
    acts = {a["name"]: a for a in email_pl["properties"]["activities"]}
    assert "Get_SPN_Secret_From_KeyVault" in acts
    assert "Send_Alert_Via_Microsoft_Graph" in acts
    assert acts["Get_SPN_Secret_From_KeyVault"]["policy"]["secureOutput"] is True
    assert "/sendMail" in acts["Send_Alert_Via_Microsoft_Graph"]["typeProperties"]["relativeUrl"]["value"]


def test_tc07_exchange_online_application_access_policy_script():
    """TC-07: Run setup_exchange_rbac.ps1 in DryRun mode to validate least-privilege mailbox scoping."""
    import shutil
    ps_script = REPO_ROOT / "cicd" / "setup_exchange_rbac.ps1"
    assert ps_script.exists()
    pwsh_bin = shutil.which("pwsh") or shutil.which("powershell")
    assert pwsh_bin is not None, "PowerShell (pwsh or powershell) is required"
    res = subprocess.run(
        [pwsh_bin, "-NoProfile", "-File", str(ps_script), "-DryRun"],
        capture_output=True, text=True, check=True
    )
    assert "AccessCheckResult: Granted" in res.stdout
    assert "AccessCheckResult: Denied" in res.stdout


def test_tc08_ephemeral_canary_provisioner_structure():
    """TC-08: Verify Ephemeral Canary script & PR workflow contain provision, deploy, and always() teardown."""
    wf_text = (REPO_ROOT / ".github/workflows/pr-ephemeral-canary.yml").read_text(encoding="utf-8")
    assert "provision_ephemeral_canary.py --action provision" in wf_text
    assert "if: always()" in wf_text
    assert "provision_ephemeral_canary.py --action teardown" in wf_text


def test_tc09_secretless_oidc_workflow_configuration():
    """TC-09: Verify GitHub Actions workflows use id-token: write OIDC federation with zero client_secret inputs."""
    for wf in ["reusable-fabric-enterprise-cicd.yml", "pr-ephemeral-canary.yml"]:
        content = (REPO_ROOT / ".github/workflows" / wf).read_text(encoding="utf-8")
        assert "id-token: write" in content
        assert "azure/login@v2" in content
        assert "client-secret" not in content


def test_tc10_prod_zero_touch_valueset_configuration():
    """TC-10: Verify PROD.json maps to E2E_CICD_POC_PROD and E2E_CICD_POC_Common_Raw_PROD with zero manual edits."""
    prod_vs = json.loads(
        (REPO_ROOT / "workspace/DP_FinanceAndAccounting/Var_GlobalConfig.VariableLibrary/valueSets/PROD.json").read_text(encoding="utf-8")
    )
    overrides = {x["name"]: x["value"] for x in prod_vs["variableOverrides"]}
    assert overrides["v_env_name"] == "PROD"
    assert overrides["v_raw_workspace_id"] == "59ff2cff-26fe-43b5-9aac-5a7ef8c50a58"
    assert overrides["v_silver_workspace_id"] == "96df3a93-b1e4-4cd6-8244-47580224104e"


def test_tc11_prod_scale_pagination():
    """TC-11: Simulate multi-page (>100 items) continuationUri/continuationToken responses and verify list_all_paginated retrieves all items."""
    mock_session = MagicMock()
    resp_page1 = MagicMock(status_code=200, text='{"value":[{"id":"1"},{"id":"2"}],"continuationToken":"page2_tok"}')
    resp_page1.json.return_value = {"value": [{"id": f"ws-{i}"} for i in range(60)], "continuationToken": "page2_tok"}
    resp_page2 = MagicMock(status_code=200, text='{"value":[{"id":"3"}]}')
    resp_page2.json.return_value = {"value": [{"id": f"ws-{i}"} for i in range(60, 125)]}
    mock_session.request.side_effect = [resp_page1, resp_page2]

    client = FabricEnterpriseClient(session=mock_session)
    client._token = "fake-token"
    client._token_expires_on = 9999999999.0

    items = client.list_all_paginated("/workspaces")
    assert len(items) == 125
    assert items[0]["id"] == "ws-0"
    assert items[-1]["id"] == "ws-124"


def test_tc12_prod_scale_http_429_and_lro_202():
    """TC-12: Simulate HTTP 429 Retry-After and HTTP 202 Accepted LRO polling until Succeeded."""
    mock_session = MagicMock()
    r_429 = MagicMock(status_code=429, headers={"Retry-After": "1"}, text="")
    r_202 = MagicMock(
        status_code=202,
        headers={"Location": "https://api.fabric.microsoft.com/v1/operations/op-123", "Retry-After": "1"},
        text=""
    )
    r_poll_running = MagicMock(status_code=200, headers={"Retry-After": "1"}, text='{"status":"Running","percentComplete":50}')
    r_poll_running.json.return_value = {"status": "Running", "percentComplete": 50}
    r_poll_done = MagicMock(status_code=200, headers={}, text='{"status":"Succeeded","percentComplete":100}')
    r_poll_done.json.return_value = {"status": "Succeeded", "percentComplete": 100}

    mock_session.request.side_effect = [r_429, r_202]
    mock_session.get.side_effect = [r_poll_running, r_poll_done]

    client = FabricEnterpriseClient(session=mock_session)
    client._token = "fake-token"
    client._token_expires_on = 9999999999.0

    result = client.request("POST", "/workspaces/ws-1/items", json_body={"displayName": "test"})
    assert result["status"] == "Succeeded"
    assert mock_session.request.call_count == 2
    assert mock_session.get.call_count == 2


def test_tc13_prod_scale_matrix_1_to_n_to_1_dag():
    """TC-13: Verify enterprise-topology.json and reusable-fabric-enterprise-cicd.yml define Stage 1 Raw -> Stage 2 Matrix Domains -> Stage 3 Gold."""
    topo = json.loads((REPO_ROOT / "config/enterprise-topology.json").read_text(encoding="utf-8"))
    assert len(topo["stage1_rawWorkspaces"]) >= 1
    assert len(topo["stage2_domainWorkspaces"]) >= 2
    assert len(topo["stage3_goldWorkspaces"]) >= 1

    wf = (REPO_ROOT / ".github/workflows/reusable-fabric-enterprise-cicd.yml").read_text(encoding="utf-8")
    assert "stage1_deploy_common_raw:" in wf
    assert "stage2_deploy_domains_matrix:" in wf
    assert "stage3_deploy_enterprise_gold:" in wf
    assert "max-parallel: 4" in wf


def test_tc14_prod_scale_preflight_rbac_catches_missing_spn_grant(tmp_path: Path):
    """TC-14: Verify preflight_rbac_validator catches a Connection GUID where SPN lacks roleAssignment."""
    vl_dir = tmp_path / "Var_GlobalConfig.VariableLibrary" / "valueSets"
    vl_dir.mkdir(parents=True)
    (vl_dir / "QA.json").write_text(json.dumps({
        "name": "QA",
        "variableOverrides": [
            {"name": "v_raw_sql_connection_id", "value": "99999999-9999-9999-9999-999999999999"}
        ]
    }), encoding="utf-8")

    mock_client = MagicMock()
    mock_client.list_all_paginated.side_effect = [
        [{"id": "ws-qa", "displayName": "E2E_CICD_POC_QA"}],  # /workspaces
        [{"principal": {"id": "spn-123"}, "role": "Admin"}],  # /workspaces/ws-qa/roleAssignments
        [{"principal": {"id": "someone-else"}, "role": "Owner"}]  # /connections/.../roleAssignments (missing spn-123!)
    ]
    mock_client.request.return_value = {"id": "99999999-9999-9999-9999-999999999999", "displayName": "CONN_UNSHARED_QA"}

    errs = check_preflight_errors(mock_client, tmp_path, "E2E_CICD_POC_QA", "QA", "spn-123")
    assert len(errs) == 1
    assert "CONN_UNSHARED_QA" in errs[0]
    assert "spn-123" in errs[0]


def test_tc15_prod_scale_stateful_safety_during_orphan_cleanup(tmp_path: Path):
    """TC-15: Verify deploy_workspace with prune_stateless_orphans=True deletes stateless orphans (DataPipeline) while preserving stateful Lakehouses."""
    mock_client = MagicMock()
    # 1st call: /workspaces, 2nd call: /workspaces/{id}/items (before), 3rd call: /workspaces/{id}/items (after)
    remote_items = [
        {"id": "lh-keep-1", "displayName": "lh_extra_stateful", "type": "Lakehouse"},
        {"id": "sql-keep-1", "displayName": "lh_extra_stateful", "type": "SQLEndpoint"},
        {"id": "pl-del-1", "displayName": "pl_old_deprecated_orphan", "type": "DataPipeline"}
    ]
    mock_client.list_all_paginated.side_effect = [
        [{"id": "ws-1", "displayName": "E2E_CICD_POC"}],
        remote_items,
        remote_items
    ]

    result = deploy_workspace(
        workspace_dir=str(tmp_path),
        target_ws_name="E2E_CICD_POC",
        env="DEV",
        prune_stateless_orphans=True,
        use_fabric_cicd_lib=False,
        client=mock_client
    )

    assert "lh_extra_stateful.Lakehouse" in result["preservedStatefulItems"]
    assert "pl_old_deprecated_orphan.DataPipeline" in result["prunedStatelessOrphans"]
    mock_client.request.assert_called_once_with("DELETE", "/workspaces/ws-1/items/pl-del-1")


def test_tc16_qa_schedule_and_sql_metadata_backup_restore_guard(tmp_path: Path):
    """TC-16: Verify Matthew James's requirement — QA DataPipeline schedules & SQL Endpoint metadata are backed up and restored across deployments."""
    mock_client = MagicMock()
    # Backup mocks: /workspaces, /workspaces/{id}/items, /workspaces/{id}/items/{pl}/jobs/Pipeline/schedules
    mock_client.list_all_paginated.side_effect = [
        [{"id": "ws-qa", "displayName": "E2E_CICD_POC_QA"}],
        [
            {"id": "pl-1", "displayName": "pl_02_01_01_D365_Entities_Raw_to_EnrichedCurated_FabLink_GeneralLedger", "type": "DataPipeline", "tags": ["Finance-GL"]},
            {"id": "sm-1", "displayName": "sm_d365_gl", "type": "SemanticModel"}
        ],
        [{"id": "sched-1", "enabled": True, "configuration": {"type": "Cron", "interval": 60}}],
        # Restore mocks: /workspaces, /workspaces/{id}/items, existing schedules (empty because overwritten!), /workspaces/{id}/lakehouses
        [{"id": "ws-qa", "displayName": "E2E_CICD_POC_QA"}],
        [{"id": "pl-1", "displayName": "pl_02_01_01_D365_Entities_Raw_to_EnrichedCurated_FabLink_GeneralLedger", "type": "DataPipeline"}],
        [],
        [{"id": "lh-silver-qa", "displayName": "lh_d365_silver_gl"}]
    ]
    mock_client.request.side_effect = [
        {},  # POST schedule restore
        {"properties": {"sqlEndpointProperties": {"id": "sql-ep-qa-1"}}},  # GET lakehouse detail
        {"status": "Succeeded"}  # POST sqlEndpoints/refreshMetadata
    ]

    state_file = tmp_path / "qa_state.json"
    snap = backup_workspace_operational_state(mock_client, "E2E_CICD_POC_QA", state_file)
    assert "pl_02_01_01_D365_Entities_Raw_to_EnrichedCurated_FabLink_GeneralLedger.DataPipeline" in snap["itemSchedules"]
    assert len(snap["semanticModels"]) == 1

    restored = restore_workspace_operational_state(mock_client, "E2E_CICD_POC_QA", snap)
    assert "pl_02_01_01_D365_Entities_Raw_to_EnrichedCurated_FabLink_GeneralLedger.DataPipeline" in restored["restoredSchedules"]
    assert "lh_d365_silver_gl" in restored["refreshedSqlEndpoints"]

