#!/usr/bin/env python3
"""
cicd/lint_fabric_artifacts.py
Pre-Deploy Static Gate (Addresses REQ-04, REQ-06, Issue 1-3, Issue 11, Issue 18-19):
  1. Blocks PRs containing raw hardcoded GUIDs in DataPipeline or CopyJob definitions
  2. Blocks Office365Outlook or Teams activities (UAT #796904 personal OAuth blocker)
  3. Verifies Variable Libraries contain variables.json, valueSets/QA.json, and valueSets/PROD.json
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, List

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
FORBIDDEN_KEYS = {"workspaceId", "artifactId", "connection"}
FORBIDDEN_TYPES = {"Office365Outlook", "Teams", "MicrosoftTeams"}


def scan_node(node: Any, path: str, errors: List[str], fpath: Path) -> None:
    if isinstance(node, dict):
        act_type = node.get("type")
        if act_type in FORBIDDEN_TYPES:
            errors.append(
                f"[FORBIDDEN ACTIVITY] {fpath} at {path}: '{act_type}' breaks SPN CI/CD (UAT #796904). "
                f"Use pl_00_Common_SendEmail_GraphWeb."
            )
        for k, v in node.items():
            if k in FORBIDDEN_KEYS and isinstance(v, str) and UUID_RE.match(v.strip()):
                errors.append(
                    f"[HARDCODED GUID] {fpath} at {path}.{k}: '{v}'. "
                    f"Bind to @pipeline().libraryVariables.Var_GlobalConfig_*."
                )
            else:
                scan_node(v, f"{path}.{k}", errors, fpath)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            scan_node(item, f"{path}[{idx}]", errors, fpath)


def lint_workspace_tree(root: Path) -> List[str]:
    errs: List[str] = []
    for pfile in root.rglob("*.DataPipeline/pipeline-content.json"):
        scan_node(json.loads(pfile.read_text(encoding="utf-8")), "root", errs, pfile)
    for cfile in root.rglob("*.CopyJob/copyjob-content.json"):
        scan_node(json.loads(cfile.read_text(encoding="utf-8")), "root", errs, cfile)
    for vdir in root.rglob("*.VariableLibrary"):
        for req in ["variables.json", "valueSets/QA.json", "valueSets/PROD.json"]:
            if not (vdir / req).exists():
                errs.append(f"[MISSING VALUESET] {vdir.name} ({vdir}) is missing {req}")
    return errs


if __name__ == "__main__":
    root_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "workspace")
    errors = lint_workspace_tree(root_dir)
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print("[PASS] All Fabric artifacts passed static linting (0 raw GUIDs, 0 personal OAuth activities, 100% ValueSets present).")
