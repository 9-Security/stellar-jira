"""Optional Jira workflow Ticket Status ↔ Stellar (when names differ from 事件狀態)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT = _REPO / "config" / "stellar_jira_workflow_status_map.json"


@dataclass(frozen=True)
class WorkflowStatusMap:
    jira_workflow_to_stellar: dict[str, str]
    stellar_to_jira_workflow: dict[str, str]


def load_workflow_status_map(path: Path | None = None) -> WorkflowStatusMap:
    p = path or _DEFAULT
    if not p.is_file():
        return WorkflowStatusMap(jira_workflow_to_stellar={}, stellar_to_jira_workflow={})
    data = json.loads(p.read_text(encoding="utf-8"))
    j2s = data.get("jira_workflow_to_stellar") if isinstance(data.get("jira_workflow_to_stellar"), dict) else {}
    s2j = data.get("stellar_to_jira_workflow") if isinstance(data.get("stellar_to_jira_workflow"), dict) else {}
    return WorkflowStatusMap(
        jira_workflow_to_stellar={str(k): str(v) for k, v in j2s.items()},
        stellar_to_jira_workflow={str(k): str(v) for k, v in s2j.items()},
    )


def map_jira_workflow_to_stellar(workflow_name: str | None, wmap: WorkflowStatusMap) -> str | None:
    if not workflow_name or not str(workflow_name).strip():
        return None
    return wmap.jira_workflow_to_stellar.get(str(workflow_name).strip())


def map_stellar_to_jira_workflow(stellar_status: str | None, wmap: WorkflowStatusMap) -> str | None:
    if not stellar_status or not str(stellar_status).strip():
        return None
    return wmap.stellar_to_jira_workflow.get(str(stellar_status).strip())
