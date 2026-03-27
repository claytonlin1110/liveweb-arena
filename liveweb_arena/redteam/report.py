from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from liveweb_arena.redteam.metrics import TemplateMetrics
from liveweb_arena.redteam.probe import ProbeResult


def build_report(
    *,
    templates: Sequence[TemplateMetrics],
    samples: Sequence[ProbeResult],
    stability: Optional[Dict[str, Any]],
    violations: Optional[List[Dict[str, Any]]] = None,
    args: Dict[str, Any],
) -> Dict[str, Any]:
    by_template: Dict[str, List[ProbeResult]] = {}
    for r in samples:
        key = f"{r.plugin_name}/{r.template_name}"
        by_template.setdefault(key, []).append(r)

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tool": "liveweb_arena.redteam",
            "args": args,
        },
        "templates": [asdict(t) for t in templates],
        "stability": stability,
        "violations": violations or [],
        "failures": [
            {
                "plugin_name": r.plugin_name,
                "template_name": r.template_name,
                "seed": r.seed,
                "variant": r.variant,
                "question": r.question_text,
                "validation_info": r.validation_info,
                "probe_urls": r.probe_urls,
                "error": r.gt_error,
            }
            for r in samples
            if not r.gt_ok
        ][:100],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    tmpl = report.get("templates", [])
    tmpl_sorted = sorted(
        tmpl,
        key=lambda t: (
            -(t.get("collapse_rate") or 0.0),
            (t.get("gt_success_rate") or 0.0),
            t.get("template_name") or "",
        ),
    )

    lines: List[str] = []
    lines.append("## Template Red Team Report")
    lines.append("")
    lines.append(f"- **Generated**: {report['meta']['generated_at']}")
    lines.append(f"- **Mode**: api-probe (plugin.fetch_api_data → GTCollector)")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Template | Samples | GT ok | Unique GT | Collapse | Baseline |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for t in tmpl_sorted:
        name = f"{t.get('plugin_name')}/{t.get('template_name')}"
        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    str(t.get("samples", 0)),
                    f"{(t.get('gt_success_rate', 0.0) * 100):.1f}%",
                    str(t.get("unique_gt_values", 0)),
                    f"{(t.get('collapse_rate', 0.0) * 100):.1f}%",
                    f"{(t.get('baseline_guess_rate', 0.0) * 100):.1f}%",
                ]
            )
            + " |"
        )

    violations = report.get("violations", []) or []
    if violations:
        lines.append("")
        lines.append("## Threshold violations")
        lines.append("")
        for v in violations[:50]:
            scope = v.get("scope", "global")
            name = v.get("template", "")
            metric = v.get("metric", "")
            actual = v.get("actual")
            limit = v.get("limit")
            lines.append(f"- **{scope}** {name} `{metric}` actual={actual} limit={limit}")

    stability = report.get("stability")
    if stability and stability.get("stability_rate") is not None:
        lines.append("")
        lines.append("## Stability (repeat probe)")
        lines.append("")
        lines.append(
            f"- **Comparable pairs**: {stability.get('comparable_pairs')}/{stability.get('total_pairs')}"
        )
        lines.append(
            f"- **Stable GT**: {stability.get('stable_pairs')} "
            f"(stability={(stability.get('stability_rate') * 100):.1f}%)"
        )
        if stability.get("changes"):
            lines.append("")
            lines.append("### Examples of changed GT (capped)")
            for ch in stability["changes"][:10]:
                lines.append(f"- **{ch['plugin_name']}/{ch['template_name']}** seed={ch['seed']} variant={ch['variant']}")
                lines.append(f"  - Q: {ch['question']}")
                lines.append(f"  - GT-A: {ch['gt_a']}")
                lines.append(f"  - GT-B: {ch['gt_b']}")

    failures = report.get("failures", [])
    if failures:
        lines.append("")
        lines.append("## GT probe failures (capped)")
        for f in failures[:20]:
            lines.append(f"- **{f['plugin_name']}/{f['template_name']}** seed={f['seed']} variant={f['variant']}")
            lines.append(f"  - Q: {f['question']}")
            lines.append(f"  - Error: {f['error']}")

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- **Scope**: this dashboard is a quick automated supplement; it does NOT replace CLAUDE.md mandatory red team review or eval.py template testing."
    )
    lines.append(
        "- **Collapse**: computed as \\(1 - \\frac{\\#distinct\\_GT}{\\#distinct\\_validation\\_signatures}\\) over successful samples."
    )
    lines.append(
        "- **Baseline**: heuristic estimate (binary/2-option → 50%, else \\(1/\\#unique\\_GT\\))."
    )
    lines.append(
        "- **GT ok** depends on whether the probe URLs were sufficient to populate collected API data for the template."
    )
    lines.append("")
    return "\n".join(lines)


def write_report_files(output_dir: Path, report: Dict[str, Any]) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"

    tmp_json = json_path.with_suffix(".json.tmp")
    tmp_md = md_path.with_suffix(".md.tmp")

    tmp_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_md.write_text(render_markdown(report) + "\n", encoding="utf-8")

    tmp_json.replace(json_path)
    tmp_md.replace(md_path)

    return {"json": str(json_path), "md": str(md_path)}

