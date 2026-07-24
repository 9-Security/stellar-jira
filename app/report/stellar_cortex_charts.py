"""Severity and detection-category charts for Cortex XDR monthly report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from app.report.monthly_docx import C_AMBER, C_GRAY, C_GREEN, C_PRIMARY, C_RED, setup_cjk_font
from app.report.stellar_darktrace_summary import stellar_case_severity_tier

SEVERITY_ORDER = ("高", "中", "低")
SEVERITY_COLORS = {"高": C_RED, "中": C_AMBER, "低": C_GREEN}

CORTEX_ALERT_STATS_FOOTNOTE = (
    "嚴重度依 Stellar Case severity（Critical/High→高、Medium→中、其餘→低）。"
    "偵測類別取自 alert 的 palo_alto_networks.category。"
    "資料來源為 Stellar Cases API 內之 Cortex XDR alerts。"
)


def _severity_bucket(row: dict[str, Any]) -> str:
    return stellar_case_severity_tier(row.get("case_severity"))


def _category_label(row: dict[str, Any]) -> str:
    cat = str(row.get("alert_category") or "").strip()
    if cat:
        return cat
    name = str(row.get("alert_name") or row.get("case_name") or "").lower()
    if any(k in name for k in ("identity", "login", "oauth")):
        return "Identity"
    if any(k in name for k in ("network", "c2", "firewall")):
        return "Network"
    return "Endpoint"


def build_cortex_alert_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    severities = {name: 0 for name in SEVERITY_ORDER}
    categories: dict[str, int] = {}
    for row in rows:
        sev = _severity_bucket(row)
        severities[sev] = severities.get(sev, 0) + 1
        cat = _category_label(row)
        categories[cat] = categories.get(cat, 0) + 1
    cat_order = sorted(categories.keys(), key=lambda k: (-categories[k], k))
    return {
        "total": len(rows),
        "severities": severities,
        "categories": categories,
        "category_order": cat_order,
        "footnote": CORTEX_ALERT_STATS_FOOTNOTE,
    }


def make_cortex_alert_stats_panel(stats: dict[str, Any], out_path: Path) -> None:
    """Two-panel figure: severity donut + detection category bars."""
    setup_cjk_font()
    severities = stats.get("severities") or {}
    categories = stats.get("categories") or {}
    cat_order = stats.get("category_order") or sorted(categories.keys())
    total = int(stats.get("total") or 0)

    fig, (ax_sev, ax_cat) = plt.subplots(1, 2, figsize=(14.5, 5.2))
    fig.patch.set_facecolor("white")

    sizes = [severities.get(name, 0) for name in SEVERITY_ORDER]
    colors = [SEVERITY_COLORS[name] for name in SEVERITY_ORDER]
    labels = [f"{name} ({severities.get(name, 0):,})" for name in SEVERITY_ORDER]

    if total > 0:
        wedges, _ = ax_sev.pie(
            sizes,
            colors=colors,
            startangle=90,
            counterclock=False,
            wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
        )
        ax_sev.legend(wedges, labels, loc="lower center", bbox_to_anchor=(0.5, -0.14), fontsize=9, frameon=False)
        ax_sev.text(0, 0.08, f"{total:,}", ha="center", va="center", fontsize=20, color=C_PRIMARY, weight="bold")
        ax_sev.text(0, -0.12, "Alerts", ha="center", va="center", fontsize=10, color=C_GRAY)
    else:
        ax_sev.axis("off")
        ax_sev.text(0.5, 0.5, "無資料", ha="center", va="center", fontsize=14, color=C_GRAY)

    ax_sev.set_title("Alerts by Severity", fontsize=12, color=C_PRIMARY, weight="bold", pad=10)

    if cat_order:
        x = np.arange(len(cat_order))
        vals = [categories.get(c, 0) for c in cat_order]
        bars = ax_cat.bar(x, vals, color=C_PRIMARY, alpha=0.85)
        for bar, val in zip(bars, vals):
            if val > 0:
                ax_cat.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    str(val),
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color=C_PRIMARY,
                )
        ax_cat.set_xticks(x)
        ax_cat.set_xticklabels(cat_order, fontsize=8, rotation=25, ha="right")
    else:
        ax_cat.axis("off")
        ax_cat.text(0.5, 0.5, "無資料", ha="center", va="center", fontsize=14, color=C_GRAY)

    ax_cat.set_ylabel("Number of Alerts", fontsize=10, color=C_PRIMARY)
    ax_cat.set_title("Alerts by Detection Category", fontsize=12, color=C_PRIMARY, weight="bold", pad=10)
    ax_cat.grid(axis="y", linestyle="--", alpha=0.25)
    ax_cat.spines["top"].set_visible(False)
    ax_cat.spines["right"].set_visible(False)

    fig.suptitle(
        "告警嚴重度與偵測類別統計",
        fontsize=14,
        color=C_PRIMARY,
        weight="bold",
        y=1.02,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
