"""Extract alert field values from Stellar case bundles (notify / Jira mapping)."""

from __future__ import annotations

from typing import Any

_TOP_PATH_KEYS = (
    "file_path",
    "filepath",
    "process_path",
    "path",
    "file_name",
    "filename",
    "target_file",
    "action_file_path",
    "action_file_name",
)

_PAN_PATH_KEYS = (
    "action_file_path",
    "action_file_name",
    "file_path",
    "file_name",
    "actor_process_image_path",
    "action_process_image_path",
    "causality_actor_process_image_path",
    "os_actor_process_image_path",
)

_PAN_EVENT_PATH_KEYS = (
    "actor_process_image_path",
    "action_process_image_path",
    "causality_actor_process_image_path",
    "os_actor_process_image_path",
    "action_file_path",
    "action_file_name",
)

_PROCESS_NODE_KEYS = ("parent", "child", "process", "target")

_SYSTEM32_MARKERS = ("\\windows\\system32\\", "\\windows\\syswow64\\")
_USERLAND_MARKERS = ("\\users\\", "\\appdata\\", "\\downloads\\", "\\temp\\", "\\tmp\\")
_LOW_VALUE_EXECUTABLES = frozenset(
    {
        "explorer.exe",
        "dllhost.exe",
        "svchost.exe",
        "runtimebroker.exe",
        "sihost.exe",
        "taskhostw.exe",
        "mrt.exe",
        "rundll32.exe",
    }
)


def _alert_docs(bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    alerts_payload = (bundle or {}).get("alerts")
    if not isinstance(alerts_payload, dict):
        return []
    data = alerts_payload.get("data")
    docs: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("docs"), list):
        docs = data["docs"]
    elif isinstance(data, list):
        docs = data
    out: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        src = doc.get("_source") if isinstance(doc.get("_source"), dict) else doc
        if isinstance(src, dict):
            out.append(src)
    return out


def _path_location_adjustment(path: str) -> int:
    """Tune ranking: prefer userland paths; deprioritize common Windows system binaries."""
    low = str(path or "").strip().replace("/", "\\").lower()
    if not low:
        return 0
    adj = 0
    if any(marker in low for marker in _SYSTEM32_MARKERS):
        adj -= 12
    elif "\\windows\\" in low and "\\program files" not in low:
        adj -= 4
    if any(marker in low for marker in _USERLAND_MARKERS):
        adj += 6
    base_name = low.rsplit("\\", 1)[-1]
    if base_name in _LOW_VALUE_EXECUTABLES:
        adj -= 8
    return adj


def _path_score(path: str, *, malware_hint: bool) -> int:
    text = str(path or "").strip()
    if not text:
        return 0
    score = 1
    if "\\" in text or "/" in text:
        score += 4
    if len(text) > 12:
        score += 1
    if malware_hint:
        score += 8
    score += _path_location_adjustment(text)
    return max(score, 0)


def _malware_hint(src: dict[str, Any]) -> bool:
    pan = src.get("palo_alto_networks")
    if isinstance(pan, dict):
        if str(pan.get("category") or "").strip().lower() == "malware":
            return True
        name = str(pan.get("name") or "").lower()
        if "wildfire" in name or "malware" in name:
            return True
    xdr = src.get("xdr_event")
    if isinstance(xdr, dict):
        desc = str(xdr.get("description") or "").lower()
        if "wildfire" in desc or "malware" in desc:
            return True
    return False


def _scalar_path(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, dict):
        for key in ("path", "value", "name", "executable", "command_line"):
            nested = val.get(key)
            if nested is not None and str(nested).strip():
                return str(nested).strip()
        return ""
    return str(val).strip()


def _paths_from_process_list(process_list: Any) -> list[str]:
    if not isinstance(process_list, list):
        return []
    paths: list[str] = []
    for item in process_list:
        if not isinstance(item, dict):
            continue
        for node_key in _PROCESS_NODE_KEYS:
            node = item.get(node_key)
            if not isinstance(node, dict):
                continue
            for key in ("executable", "command_line", "image_path", "path"):
                val = _scalar_path(node.get(key))
                if val:
                    paths.append(val)
        name = _scalar_path(item.get("name"))
        if name:
            paths.append(name)
    return paths


def _paths_from_alert_source(src: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in _TOP_PATH_KEYS:
        val = _scalar_path(src.get(key))
        if val:
            paths.append(val)

    pan = src.get("palo_alto_networks")
    if isinstance(pan, dict):
        for key in _PAN_PATH_KEYS:
            val = _scalar_path(pan.get(key))
            if val:
                paths.append(val)
        events = pan.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                for key in _PAN_EVENT_PATH_KEYS:
                    val = _scalar_path(event.get(key))
                    if val:
                        paths.append(val)

    paths.extend(_paths_from_process_list(src.get("process_list")))
    return paths


def stellar_primary_file_path(bundle: dict[str, Any] | None) -> str:
    """Best file/process path for notify body (Cortex XDR paths live under ``palo_alto_networks`` / ``process_list``)."""
    best = ""
    best_score = 0
    for src in _alert_docs(bundle):
        hint = _malware_hint(src)
        for path in _paths_from_alert_source(src):
            score = _path_score(path, malware_hint=hint)
            if score > best_score:
                best = path
                best_score = score
    return best
