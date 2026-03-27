from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from liveweb_arena.core.task_manager import TaskManager
from liveweb_arena.plugins import get_all_plugins
from liveweb_arena.core.validators.base import get_registered_templates
from liveweb_arena.redteam.metrics import compare_repeated_runs, compute_template_metrics
from liveweb_arena.redteam.probe import ProbeResult, probe_task_ground_truth
from liveweb_arena.redteam.report import build_report, write_report_files


def _parse_templates(template_strs: Optional[List[str]]) -> Optional[List[Tuple[str, str, Optional[int]]]]:
    if not template_strs:
        return None
    result: List[Tuple[str, str, Optional[int]]] = []
    for t in template_strs:
        parts = t.split("/")
        if len(parts) == 2:
            result.append((parts[0], parts[1], None))
        elif len(parts) == 3:
            result.append((parts[0], parts[1], int(parts[2])))
        else:
            raise ValueError(f"Invalid template format: {t}. Use plugin/template[/variant]")
    return result


def _parse_seeds(s: str) -> List[int]:
    """
    Parse seeds:
    - "0:10" -> 0..9
    - "0:10:2" -> 0,2,4,6,8
    - "1,5,9" -> explicit list
    """
    s = (s or "").strip()
    if not s:
        raise ValueError("Empty seeds")
    if "," in s:
        return [int(x.strip()) for x in s.split(",") if x.strip()]
    if ":" in s:
        parts = [p.strip() for p in s.split(":")]
        if len(parts) == 2:
            start, end = int(parts[0]), int(parts[1])
            step = 1
        elif len(parts) == 3:
            start, end, step = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            raise ValueError("Invalid seed range format")
        if step <= 0:
            raise ValueError("Seed step must be > 0")
        return list(range(start, end, step))
    return [int(s)]

def _resolve_all_templates(
    *,
    plugins_filter: Optional[List[str]] = None,
    include_variants: bool = False,
) -> List[Tuple[str, str, Optional[int]]]:
    """
    Return (plugin, template_name, variant) for all registered templates that
    have an identifiable cache source/plugin.
    """
    resolved: List[Tuple[str, str, Optional[int]]] = []
    registry = get_registered_templates()
    for registered_name, cls in registry.items():
        try:
            plugin = cls.get_cache_source()
        except Exception:
            plugin = None
        if not plugin:
            continue
        if plugins_filter and plugin not in plugins_filter:
            continue
        # Use the registry name for template lookup (BasePlugin.generate_task supports it).
        resolved.append((plugin, registered_name, None))
    # stable order for CI
    resolved.sort(key=lambda t: (t[0], t[1], t[2] if t[2] is not None else -1))
    return resolved


async def _run_probe_once(
    *,
    templates: List[Tuple[str, str, Optional[int]]],
    seeds: List[int],
) -> List[ProbeResult]:
    task_manager = TaskManager(get_all_plugins())
    all_results: List[ProbeResult] = []

    for seed in seeds:
        # For deterministic coverage: 1 subtask per template spec.
        for plugin, template_name, variant in templates:
            task = await task_manager.generate_composite_task(
                seed=seed,
                num_subtasks=1,
                templates=[(plugin, template_name, variant)],
            )
            st = task.subtasks[0]
            if st.question is None:
                raise RuntimeError("Subtask missing GeneratedQuestion")
            q = st.question
            results = await probe_task_ground_truth(
                task_manager=task_manager,
                subtasks=[st],
                questions=[q],
                plugin_names=[plugin],
                seed=seed,
                variant=variant,
            )
            all_results.extend(results)

    return all_results


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "LiveWeb Arena - Template Red Team Dashboard "
            "(supplementary API probe, not a replacement for CLAUDE.md red team review or eval.py)."
        )
    )
    parser.add_argument(
        "--templates",
        type=str,
        nargs="+",
        required=False,
        help='Templates to probe: "plugin/template[/variant]"',
    )
    parser.add_argument(
        "--all-templates",
        action="store_true",
        help="Probe all registered templates with known plugin source.",
    )
    parser.add_argument(
        "--plugins",
        type=str,
        nargs="+",
        default=None,
        help='Optional filter for --all-templates (e.g., "coingecko stooq")',
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List resolved templates (no probing) and exit.",
    )
    parser.add_argument(
        "--seeds",
        type=str,
        default="0:25",
        help='Seed schedule: "0:25", "0:100:2", or "1,2,3"',
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of probe repeats (>=1). If 2, stability is reported.",
    )
    parser.add_argument(
        "--repeat-delay-s",
        type=float,
        default=0.0,
        help="Delay between repeats (seconds).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write report.{json,md} (default: ./redteam/<timestamp>/)",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="Exit non-zero if any threshold is violated (CI mode).",
    )
    parser.add_argument(
        "--min-gt-success",
        type=float,
        default=None,
        help="Minimum GT success rate (0..1).",
    )
    parser.add_argument(
        "--max-collapse",
        type=float,
        default=None,
        help="Maximum allowed collapse rate (0..1).",
    )
    parser.add_argument(
        "--max-baseline",
        type=float,
        default=None,
        help="Maximum allowed baseline guess rate (0..1).",
    )
    parser.add_argument(
        "--min-stability",
        type=float,
        default=None,
        help="Minimum allowed stability rate (0..1). Requires --repeat >= 2.",
    )

    args = parser.parse_args()

    # Ensure plugins/templates are loaded before resolving templates.
    get_all_plugins()

    if args.all_templates:
        templates = _resolve_all_templates(plugins_filter=args.plugins)
        if not templates:
            raise ValueError("No templates resolved via --all-templates")
    else:
        templates = _parse_templates(args.templates)
        if not templates:
            raise ValueError("No templates provided (use --templates or --all-templates)")

    if args.list_templates:
        # Print in a stable order for scripting/CI.
        for plugin, template_name, variant in templates:
            if variant is None:
                print(f"{plugin}/{template_name}")
            else:
                print(f"{plugin}/{template_name}/{variant}")
        return 0

    seeds = _parse_seeds(args.seeds)
    if args.repeat < 1:
        raise ValueError("--repeat must be >= 1")

    repeats: List[List[ProbeResult]] = []
    for i in range(args.repeat):
        runs = await _run_probe_once(templates=templates, seeds=seeds)
        repeats.append(runs)
        if i + 1 < args.repeat and args.repeat_delay_s > 0:
            await asyncio.sleep(args.repeat_delay_s)

    samples = repeats[0]

    # Group by template for metrics.
    by_key: Dict[str, List[ProbeResult]] = {}
    for r in samples:
        key = f"{r.plugin_name}/{r.template_name}"
        by_key.setdefault(key, []).append(r)

    template_metrics = [compute_template_metrics(v) for v in by_key.values()]

    stability = None
    if len(repeats) >= 2:
        # Compare first two repeats, same ordering by construction.
        stability = compare_repeated_runs(repeats[0], repeats[1])

    violations: List[Dict[str, Any]] = []
    def _add_violation(*, scope: str, template: str, metric: str, actual: Any, limit: Any):
        violations.append(
            {
                "scope": scope,
                "template": template,
                "metric": metric,
                "actual": actual,
                "limit": limit,
            }
        )

    # Per-template thresholds.
    for tm in template_metrics:
        name = f"{tm.plugin_name}/{tm.template_name}"
        if args.min_gt_success is not None and tm.gt_success_rate < args.min_gt_success:
            _add_violation(
                scope="template",
                template=name,
                metric="gt_success_rate",
                actual=tm.gt_success_rate,
                limit=args.min_gt_success,
            )
        if args.max_collapse is not None and tm.collapse_rate > args.max_collapse:
            _add_violation(
                scope="template",
                template=name,
                metric="collapse_rate",
                actual=tm.collapse_rate,
                limit=args.max_collapse,
            )
        if args.max_baseline is not None and tm.baseline_guess_rate > args.max_baseline:
            _add_violation(
                scope="template",
                template=name,
                metric="baseline_guess_rate",
                actual=tm.baseline_guess_rate,
                limit=args.max_baseline,
            )

    # Global stability threshold (repeat probe).
    if args.min_stability is not None:
        if args.repeat < 2:
            _add_violation(
                scope="global",
                template="",
                metric="stability_rate",
                actual=None,
                limit=args.min_stability,
            )
        else:
            sr = (stability or {}).get("stability_rate")
            if sr is None or sr < args.min_stability:
                _add_violation(
                    scope="global",
                    template="",
                    metric="stability_rate",
                    actual=sr,
                    limit=args.min_stability,
                )

    # Output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        import datetime as _dt

        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = Path.cwd() / "redteam" / ts

    report = build_report(
        templates=template_metrics,
        samples=samples,
        stability=stability,
        violations=violations,
        args={
            "templates": args.templates,
            "all_templates": args.all_templates,
            "plugins": args.plugins,
            "seeds": args.seeds,
            "repeat": args.repeat,
            "repeat_delay_s": args.repeat_delay_s,
            "fail_on_violation": args.fail_on_violation,
            "min_gt_success": args.min_gt_success,
            "max_collapse": args.max_collapse,
            "max_baseline": args.max_baseline,
            "min_stability": args.min_stability,
        },
    )
    paths = write_report_files(out_dir, report)

    print(paths["md"])
    print(paths["json"])
    if args.fail_on_violation and violations:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

