from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from liveweb_arena.redteam.probe import ProbeResult, validation_info_signature


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


def _looks_boolean(v: str) -> bool:
    t = _normalize_text(v)
    return t in {"yes", "no", "true", "false"}


def _extract_quoted_options(question_text: str) -> Optional[List[str]]:
    # Common pattern in OL comparisons: "A" or "B"
    opts = re.findall(r"\"([^\"]{1,200})\"", question_text or "")
    opts = [o.strip() for o in opts if o.strip()]
    if len(opts) >= 2:
        return opts[:2]
    return None


def estimate_random_baseline(sample: Sequence[ProbeResult]) -> float:
    """
    Estimate random baseline guessability for a template's answer format.

    Heuristic (documented in report):
    - If binary/boolean: 0.5
    - If question appears to be choosing between 2 quoted options: 0.5
    - Else: 1 / (# unique GT values in sample) with floor to avoid division by zero
    """
    if not sample:
        return 1.0

    # Boolean / 2-option detection
    for r in sample:
        if r.gt_ok and r.gt_value is not None and _looks_boolean(r.gt_value):
            return 0.5
        opts = _extract_quoted_options(r.question_text)
        if opts is not None and " or " in (r.question_text or "").lower():
            return 0.5

    gts = sorted({_normalize_text(r.gt_value or "") for r in sample if r.gt_ok and r.gt_value is not None})
    if not gts:
        return 1.0
    return 1.0 / max(1, len(gts))


@dataclass(frozen=True)
class TemplateMetrics:
    template_name: str
    plugin_name: str
    samples: int
    gt_success_rate: float
    unique_questions: int
    unique_gt_values: int
    collapse_rate: float
    baseline_guess_rate: float


def compute_template_metrics(sample: Sequence[ProbeResult]) -> TemplateMetrics:
    if not sample:
        raise ValueError("No samples")

    template_name = sample[0].template_name
    plugin_name = sample[0].plugin_name

    samples_n = len(sample)
    ok = [r for r in sample if r.gt_ok and r.gt_value is not None]
    gt_success_rate = len(ok) / samples_n if samples_n else 0.0

    uniq_q = len({_normalize_text(r.question_text) for r in sample})
    uniq_gt = len({_normalize_text(r.gt_value or "") for r in ok})

    # Cross-parameter collapse: distinct validation_info signatures mapping to distinct GT values.
    sig_to_gt: Dict[str, str] = {}
    sigs = set()
    for r in ok:
        sig = validation_info_signature(r.validation_info)
        sigs.add(sig)
        sig_to_gt.setdefault(sig, _normalize_text(r.gt_value or ""))

    distinct_param_sets = len(sigs)
    distinct_outputs = len(set(sig_to_gt.values()))
    if distinct_param_sets <= 1:
        collapse_rate = 0.0
    else:
        # collapse = 1 - (distinct outputs / distinct param sets)
        collapse_rate = 1.0 - (distinct_outputs / distinct_param_sets)

    baseline = estimate_random_baseline(sample)

    return TemplateMetrics(
        template_name=template_name,
        plugin_name=plugin_name,
        samples=samples_n,
        gt_success_rate=gt_success_rate,
        unique_questions=uniq_q,
        unique_gt_values=uniq_gt,
        collapse_rate=collapse_rate,
        baseline_guess_rate=baseline,
    )


def compare_repeated_runs(
    run_a: Sequence[ProbeResult],
    run_b: Sequence[ProbeResult],
) -> Dict[str, Any]:
    """
    Compare GT stability across two probes for the same (seed, variant) schedule.
    """
    if len(run_a) != len(run_b):
        raise ValueError("Run sizes differ; cannot compare")

    total = len(run_a)
    comparable = 0
    same = 0
    changes: List[Dict[str, Any]] = []

    for a, b in zip(run_a, run_b):
        if not (a.gt_ok and b.gt_ok and a.gt_value is not None and b.gt_value is not None):
            continue
        comparable += 1
        if _normalize_text(a.gt_value) == _normalize_text(b.gt_value):
            same += 1
        else:
            changes.append(
                {
                    "template_name": a.template_name,
                    "plugin_name": a.plugin_name,
                    "seed": a.seed,
                    "variant": a.variant,
                    "question": a.question_text,
                    "gt_a": a.gt_value,
                    "gt_b": b.gt_value,
                }
            )

    return {
        "total_pairs": total,
        "comparable_pairs": comparable,
        "stable_pairs": same,
        "stability_rate": (same / comparable) if comparable else None,
        "changes": changes[:50],  # cap
    }

