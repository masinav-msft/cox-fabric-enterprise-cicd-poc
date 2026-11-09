# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   }
# META }

# CELL ********************

# Cox Enterprises - D365 General Ledger Silver Layer Validation & Cross-Workspace Variable Library Resolution
from notebookutils import variableLibrary

vl = variableLibrary.getLibrary("Var_GlobalConfig")
env_name = vl.v_env_name
raw_ws_id = vl.v_raw_workspace_id
raw_lh_id = vl.v_raw_lakehouse_id
silver_ws_id = vl.v_silver_workspace_id
silver_lh_id = vl.v_silver_lakehouse_id

print(f"[Var_GlobalConfig] Active Environment: {env_name}")
print(f"[Var_GlobalConfig] Upstream Raw Lakehouse: ws={raw_ws_id}, lh={raw_lh_id}")
print(f"[Var_GlobalConfig] Target Silver Lakehouse: ws={silver_ws_id}, lh={silver_lh_id}")

raw_path = f"abfss://{raw_ws_id}@onelake.dfs.fabric.microsoft.com/{raw_lh_id}/Tables/GeneralLedgerAccountEntry"
df_raw = spark.read.format("delta").load(raw_path)
row_count = df_raw.count()
assert row_count > 0, "Expected > 0 rows in GeneralLedgerAccountEntry!"
print(f"[PASS] Verified {row_count} rows in Upstream Raw GeneralLedgerAccountEntry.")
