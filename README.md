# Cox Enterprises — Microsoft Fabric + GitHub Enterprise 1:N:1 CI/CD Production-Scale POC

**Live Primary Fabric Workspace (`E2E_CICD_POC`):**  
`https://app.fabric.microsoft.com/groups/fc4bfa70-b734-4ac6-84bd-85b0b6ec0bcf/list?experience=fabric-developer`

**GitHub Repository:**  
`https://github.com/masinavorg/cox-fabric-enterprise-cicd-poc`

---

## 1. Executive Summary & Live Environment Inventory

This repository and live sandbox environment (`admin@MngEnvMCAP927255.onmicrosoft.com`, Tenant `afa6899d-aa46-4992-a3eb-5c8015aa5d1f`, Capacity `fabric444` F64 `3b977fbd-65a4-4186-8a77-2ee2dad13e31`) implement the **100% Enterprise Production-Scale CI/CD Architecture** addressing all **21 Cox Enterprises issues**, **7 Requirements (`REQ-01` – `REQ-07`)**, **15 Test Cases (`TC-01` – `TC-15`)**, and **10 Governance Sign-Off Gates (`GATE-01` – `GATE-10`)**.

### Live 3-Stage 1:N:1 Workspace Topology Provisioned in Fabric

| Stage / Role | Environment | Workspace Name | Workspace GUID | Active ValueSet | Key Deployed Artifacts |
|---|---|---|---|---|---|
| **Stage 1: Upstream Common Raw (1:N Source)** | **DEV** | `E2E_CICD_POC_Common_Raw_DEV` | `2899319d-a7f4-42b0-b782-239a666d6fec` | N/A | `lh_d365_raw` (`GeneralLedgerAccountEntry`), `lh_fleet_raw` (`FleetWaveTelemetryRaw`) |
| **Stage 1: Upstream Common Raw (1:N Source)** | **QA** | `E2E_CICD_POC_Common_Raw_QA` | `64b9541b-5e56-4e01-b33a-6f26e894ca6b` | N/A | `lh_d365_raw` (`GeneralLedgerAccountEntry`), `lh_fleet_raw` (`FleetWaveTelemetryRaw`) |
| **Stage 1: Upstream Common Raw (1:N Source)** | **PROD** | `E2E_CICD_POC_Common_Raw_PROD` | `59ff2cff-26fe-43b5-9aac-5a7ef8c50a58` | N/A | `lh_d365_raw` (`GeneralLedgerAccountEntry`), `lh_fleet_raw` (`FleetWaveTelemetryRaw`) |
| **Stage 2A: D365 Finance & Accounting (Primary POC)** | **DEV** | **`E2E_CICD_POC`** | **`fc4bfa70-b734-4ac6-84bd-85b0b6ec0bcf`** | `Default (DEV)` | `Var_GlobalConfig`, `lh_d365_silver_gl`, `pl_00_Common_SendEmail_GraphWeb`, `pl_02_01_01_D365_Entities_Raw_to_EnrichedCurated_FabLink_GeneralLedger`, `cj_02_01_03_D365_Raw_to_Silver_CopyJob`, `nb_02_01_02_D365_Tests_Silver_FabLink_GL` |
| **Stage 2A: D365 Finance & Accounting** | **QA** | `E2E_CICD_POC_QA` | `e03888cb-cc2c-4de7-9153-8c06509c46ec` | **`QA`** | Identical promoted items dynamically bound to `QA` Upstream Raw & Silver |
| **Stage 2A: D365 Finance & Accounting** | **PROD** | `E2E_CICD_POC_PROD` | `96df3a93-b1e4-4cd6-8244-47580224104e` | **`PROD`** | Identical promoted items dynamically bound to `PROD` Upstream Raw & Silver |
| **Stage 2B: FleetWave Domain** | **DEV** | `E2E_CICD_POC_FleetWave_DEV` | `5d70998e-407a-42b9-b7bd-d82943d9614a` | `Default (DEV)` | `Var_GlobalConfig`, `lh_fleet_silver`, `pl_00_Common_SendEmail_GraphWeb`, `pl_01_FleetWave_Raw_to_Silver` |
| **Stage 2B: FleetWave Domain** | **QA** | `E2E_CICD_POC_FleetWave_QA` | `74a49ab1-1117-4747-90bd-589b1f418be5` | **`QA`** | Identical promoted items dynamically bound to `QA` Upstream Raw & Silver |
| **Stage 2B: FleetWave Domain** | **PROD** | `E2E_CICD_POC_FleetWave_PROD` | `569a3b7a-2d1d-43da-80a4-7f15b83ac219` | **`PROD`** | Identical promoted items dynamically bound to `PROD` Upstream Raw & Silver |
| **Stage 3: Enterprise Gold (N:1 Fan-In)** | **DEV** | `E2E_CICD_POC_Enterprise_Gold_DEV` | `822e76d2-52f1-4562-bd87-2d49f982e31e` | `Default (DEV)` | `Var_GlobalConfig`, `lh_enterprise_gold`, `pl_00_Common_SendEmail_GraphWeb`, `pl_03_Enterprise_Gold_Curated_GL` |
| **Stage 3: Enterprise Gold (N:1 Fan-In)** | **QA** | `E2E_CICD_POC_Enterprise_Gold_QA` | `70fb5a46-580d-418e-8dda-f6b4e5c3882f` | **`QA`** | Identical promoted items dynamically bound to `QA` Silver & Gold |
| **Stage 3: Enterprise Gold (N:1 Fan-In)** | **PROD** | `E2E_CICD_POC_Enterprise_Gold_PROD` | `410be7f0-78e2-413f-91d9-4779326b0f91` | **`PROD`** | Identical promoted items dynamically bound to `PROD` Silver & Gold |

---

## 2. How All 21 Customer Issues Are Resolved (Complete Traceability)

| Issue # | Customer Problem Statement | Production-Scale Fix Implemented in This POC | Code / Artifact Reference |
|---|---|---|---|
| **Issue 1** | Office 365 Outlook activity fails on SPN promotion (`User does not have access to the connection`) | Replaced personal OAuth `Office365Outlook` activity with `WebActivity` calling Microsoft Graph `sendMail` via Shareable Cloud Connection (`CONN_GRAPH_PIPELINE_WEB`) | `workspace/*/pl_00_Common_SendEmail_GraphWeb.DataPipeline/pipeline-content.json` |
| **Issue 2** | Outlook connection cannot be shared with Service Principal (`Sharing this connection type is prohibited`) | Uses `WebForPipeline` Shareable Cloud Connections (`CONN_KEYVAULT_PIPELINE_WEB` & `CONN_GRAPH_PIPELINE_WEB`) with SPN `Owner` role assignment | `cicd/preflight_rbac_validator.py` |
| **Issue 3** | Child email pipeline (`pl_SendEmail`) still failed on promotion | `pl_00_Common_SendEmail_GraphWeb` binds all connection IDs to `@pipeline().libraryVariables.Var_GlobalConfig_*` and contains zero personal OAuth connectors | `workspace/DP_FinanceAndAccounting/pl_00_Common_SendEmail_GraphWeb.DataPipeline` |
| **Issue 4** | Mixed identities across stages (Dev human credentials vs QA/Prod service account) | Standardized on `WorkspaceIdentity` + `FabricCICD-ServicePrincipal` (`2f48b80c-c2fa-4b4e-831d-2c0e0859b15c`) across DEV, QA, and PROD | `config/enterprise-topology.json` |
| **Issue 5** | Graph `sendMail` security scoping & dynamic parameter passing unproven | Verified live execution passing `@pipeline().Pipeline`, `@pipeline().RunId`, and `@string(activity(...).error.message)` + Exchange `New-ApplicationAccessPolicy` script | `cicd/setup_exchange_rbac.ps1` |
| **Issue 6** | Promoted pipelines keep Dev connections and credentials | Connection GUIDs (`v_raw_sql_connection_id`, `v_kv_web_connection_id`, `v_graph_web_connection_id`) are parameterized per environment in `Var_GlobalConfig` | `workspace/*/Var_GlobalConfig.VariableLibrary/valueSets/{QA,PROD}.json` |
| **Issue 7** | Lakehouse SQL Endpoint connection in Copy activity breaks on promotion | Both the `DataPipeline` SQL Endpoint query (`pl_02_01_01_...`) and native `CopyJob` (`cj_02_01_03_...`) bind dynamically to `Var_GlobalConfig` | `workspace/DP_FinanceAndAccounting/cj_02_01_03_D365_Raw_to_Silver_CopyJob.CopyJob` |
| **Issue 8** | `v_env_name` in `Var_GlobalConfig` had only DEV values and was changed manually | `valueSets/QA.json` and `valueSets/PROD.json` are committed to Git and activated automatically via `PATCH /v1/workspaces/{wsId}/variableLibraries/{vlId}` | `cicd/deploy_workspace.py` |
| **Issue 9** | 35–40 manual GUIDs in YAML replacement file do not scale | `cicd/sync_variable_library.py` queries Fabric REST APIs by Display Name with full pagination and generates all 59+ GUIDs/endpoints across DEV, QA, and PROD automatically | `cicd/sync_variable_library.py` |
| **Issue 10** | Prod workspaces/items created after development start require manual retrofitting | Config-driven resolver discovers newly created QA/PROD workspaces and Lakehouses by Display Name at deployment time | `config/enterprise-topology.json` |
| **Issue 11** | Stability & governance concern around hardcoded hex GUIDs | Zero hardcoded GUIDs in any pipeline/copyjob JSON; enforced by pre-deploy static linter `cicd/lint_fabric_artifacts.py` | `cicd/lint_fabric_artifacts.py` |
| **Issue 12** | Cross-workspace references (1:N & N:1) do not auto-rebind | Solved via `Var_GlobalConfig` cross-workspace variables (`v_raw_workspace_id`, `v_raw_lakehouse_id`, `v_raw_sql_endpoint_server`) | `workspace/DP_FinanceAndAccounting/Var_GlobalConfig.VariableLibrary` |
| **Issue 13** | Native Fabric Deployment Pipelines are scoped to 1 workspace per stage | Replaced single-workspace manual promotion with 3-Stage GitHub Actions DAG (`Stage 1 Raw -> Stage 2 Domain Matrix -> Stage 3 Gold`) | `.github/workflows/reusable-fabric-enterprise-cicd.yml` |
| **Issue 14** | Hidden cross-workspace dependencies & unshared connections discovered late | `cicd/preflight_rbac_validator.py` verifies SPN access to target workspaces and every referenced Connection GUID before deploying | `cicd/preflight_rbac_validator.py` |
| **Issue 15** | No deployment ordering across upstream and downstream workspaces | GitHub Actions `needs:` DAG guarantees Stage 1 (`Common_Raw`) completes before Stage 2 (`DP_FinanceAndAccounting`, `DP_FleetWave`), which completes before Stage 3 (`Enterprise_Gold`) | `.github/workflows/reusable-fabric-enterprise-cicd.yml` |
| **Issue 16** | No clear standard deployment tool | Standardized on GitHub Actions + `fabric-cicd` / Fabric Control-Plane REST APIs (`FabricEnterpriseClient`) | `cicd/fabric_enterprise_client.py` |
| **Issue 17** | No standard global configuration template for `Var_GlobalConfig` | Standardized 19-variable schema in `Var_GlobalConfig.VariableLibrary/variables.json` + `valueSets/{QA,PROD}.json` | `workspace/DP_FinanceAndAccounting/Var_GlobalConfig.VariableLibrary/variables.json` |
| **Issue 18** | Inconsistent parameterization across pipelines | Enforced via automated PR gate (`lint_fabric_artifacts.py` fails any PR containing raw `workspaceId`, `artifactId`, or `connection` GUIDs) | `cicd/lint_fabric_artifacts.py` |
| **Issue 19** | Different developer design patterns cause promotion failures | Standardized parent-to-child error handling (`Invoke_Central_Fail_Alert_Silver` -> `pl_00_Common_SendEmail_GraphWeb`) and automated PR static + canary checks | `tests/test_cox_enterprise_cicd_poc.py` |
| **Issue 20** | No safe way to test CI/CD changes without risking QA/Prod | `cicd/provision_ephemeral_canary.py` + `.github/workflows/pr-ephemeral-canary.yml` spin up `FAB_CANARY_PR{N}_RAW` & `_FIN`, test deployment, and auto-delete in `always()` | `cicd/provision_ephemeral_canary.py` |
| **Issue 21** | No enterprise-wide reusable CI/CD operating model | Declarative `config/enterprise-topology.json` + reusable workflow `.github/workflows/reusable-fabric-enterprise-cicd.yml` onboard new domains with zero code changes | `config/enterprise-topology.json` |

---

## 3. Quick Commands for Customer Screen-Share Demo

```powershell
# 1. Run Pre-Deploy Static Linter (Verifies 0 raw GUIDs, 0 Outlook/Teams activities, 100% ValueSets)
python cicd/lint_fabric_artifacts.py workspace

# 2. Auto-Resolve All 59+ Cross-Workspace GUIDs & SQL Endpoints Across DEV, QA, and PROD
python cicd/sync_variable_library.py --topology config/enterprise-topology.json --envs QA PROD --update-dev-defaults

# 3. Run Pre-Flight Connection & Workspace RBAC Validator
python cicd/preflight_rbac_validator.py --workspace-dir workspace/DP_FinanceAndAccounting --target-workspace-name E2E_CICD_POC_QA --environment QA --spn-object-id be407c63-71c7-48a5-98f0-b99698d7971d

# 4. Deploy Workspace Artifacts & Activate Target ValueSet (QA or PROD)
python cicd/deploy_workspace.py --workspace-dir workspace/DP_FinanceAndAccounting --target-workspace-name E2E_CICD_POC_QA --environment QA --rest-only

# 5. Execute Live End-to-End Pipeline Smoke Test
python cicd/run_smoke_test.py --workspace-name E2E_CICD_POC --pipeline pl_02_01_01_D365_Entities_Raw_to_EnrichedCurated_FabLink_GeneralLedger

# 6. Run All 15 Automated Unit & Enterprise Scale Tests (TC-01 to TC-15)
python -m pytest tests/test_cox_enterprise_cicd_poc.py -v
```
