"""Model Alert category/score statistics charts for Darktrace monthly report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from app.report.monthly_docx import C_AMBER, C_GRAY, C_PRIMARY, C_RED, setup_cjk_font

SCORE_BUCKET_ORDER = [
    "0-10",
    "11-20",
    "21-30",
    "31-40",
    "41-50",
    "51-60",
    "61-70",
    "71-80",
    "81-90",
    "91-100",
]

CATEGORY_ORDER = ("Critical", "Suspicious", "Informational")
CATEGORY_COLORS = {
    "Critical": C_RED,
    "Suspicious": C_AMBER,
    "Informational": "#E8C547",
}

MODEL_ALERT_STATS_FOOTNOTE = (
    "等級依 Stellar alert 的 event_score 近似對照 Darktrace Model Alert 類別："
    "Critical ≥ 75、Suspicious 50–74、Informational < 50。"
    "資料來源為 Stellar Cases API 內之 Darktrace alerts（非 Darktrace 全量 Model Alerts）。"
    "AI Incident 與 Investigation 正/負統計需 Darktrace API 或 Stellar Data Search，本期未納入。"
)


def score_to_bucket(score: int) -> str:
    if score <= 10:
        return "0-10"
    if score <= 20:
        return "11-20"
    if score <= 30:
        return "21-30"
    if score <= 40:
        return "31-40"
    if score <= 50:
        return "41-50"
    if score <= 60:
        return "51-60"
    if score <= 70:
        return "61-70"
    if score <= 80:
        return "71-80"
    if score <= 90:
        return "81-90"
    return "91-100"


def proxy_model_alert_category(score: int) -> str:
    if score >= 75:
        return "Critical"
    if score >= 50:
        return "Suspicious"
    return "Informational"


def _parse_event_score(row: dict[str, Any]) -> int:
    try:
        return int(row.get("event_score") or 0)
    except (TypeError, ValueError):
        return 0


def build_model_alert_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories = {name: 0 for name in CATEGORY_ORDER}
    by_score = {bucket: {name: 0 for name in CATEGORY_ORDER} for bucket in SCORE_BUCKET_ORDER}
    for row in rows:
        score = _parse_event_score(row)
        cat = proxy_model_alert_category(score)
        categories[cat] += 1
        by_score[score_to_bucket(score)][cat] += 1
    return {
        "total": len(rows),
        "categories": categories,
        "by_score": by_score,
        "footnote": MODEL_ALERT_STATS_FOOTNOTE,
    }


def make_model_alerts_stats_panel(stats: dict[str, Any], out_path: Path) -> None:
    """Two-panel figure: category donut + score-range grouped bars (Darktrace report style)."""
    setup_cjk_font()
    categories = stats.get("categories") or {}
    by_score = stats.get("by_score") or {}
    total = int(stats.get("total") or 0)

    fig, (ax_cat, ax_score) = plt.subplots(1, 2, figsize=(14.5, 5.2))
    fig.patch.set_facecolor("white")

    sizes = [categories.get(name, 0) for name in CATEGORY_ORDER]
    colors = [CATEGORY_COLORS[name] for name in CATEGORY_ORDER]
    labels = [
        f"{name} ({categories.get(name, 0):,})"
        for name in CATEGORY_ORDER
    ]

    if total > 0:
        wedges, _ = ax_cat.pie(
            sizes,
            colors=colors,
            startangle=90,
            counterclock=False,
            wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
        )
        ax_cat.legend(wedges, labels, loc="lower center", bbox_to_anchor=(0.5, -0.14), fontsize=9, frameon=False)
        ax_cat.text(0, 0.08, f"{total:,}", ha="center", va="center", fontsize=20, color=C_PRIMARY, weight="bold")
        ax_cat.text(0, -0.12, "Model Alerts", ha="center", va="center", fontsize=10, color=C_GRAY)
    else:
        ax_cat.axis("off")
        ax_cat.text(0.5, 0.5, "無資料", ha="center", va="center", fontsize=14, color=C_GRAY)

    ax_cat.set_title("Incidents by Category", fontsize=12, color=C_PRIMARY, weight="bold", pad=10)

    x = np.arange(len(SCORE_BUCKET_ORDER))
    width = 0.24
    offsets = [-width, 0.0, width]
    max_val = 0
    for bucket in SCORE_BUCKET_ORDER:
        for name in CATEGORY_ORDER:
            max_val = max(max_val, (by_score.get(bucket) or {}).get(name, 0))

    for idx, name in enumerate(CATEGORY_ORDER):
        vals = [(by_score.get(bucket) or {}).get(name, 0) for bucket in SCORE_BUCKET_ORDER]
        bars = ax_score.bar(x + offsets[idx], vals, width, label=name, color=CATEGORY_COLORS[name])
        for bar, val in zip(bars, vals):
            if val > 0:
                ax_score.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    str(val),
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color=C_PRIMARY,
                )

    ax_score.set_xticks(x)
    ax_score.set_xticklabels(SCORE_BUCKET_ORDER, fontsize=8)
    ax_score.set_xlabel("Threat Score", fontsize=10, color=C_PRIMARY)
    ax_score.set_ylabel("Number of Model Alerts", fontsize=10, color=C_PRIMARY)
    ax_score.set_title("Model Alerts by Score", fontsize=12, color=C_PRIMARY, weight="bold", pad=10)
    ax_score.legend(loc="upper right", fontsize=8, frameon=False)
    ymax = max(10, max_val * 1.15) if max_val else 10
    ax_score.set_ylim(0, ymax)
    ax_score.grid(axis="y", linestyle="--", alpha=0.25)
    ax_score.spines["top"].set_visible(False)
    ax_score.spines["right"].set_visible(False)

    fig.suptitle(
        "事件等級類別及事件分數統計",
        fontsize=14,
        color=C_PRIMARY,
        weight="bold",
        y=1.02,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
