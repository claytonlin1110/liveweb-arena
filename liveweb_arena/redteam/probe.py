from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

from liveweb_arena.core.gt_collector import GTCollector, set_current_gt_collector
from liveweb_arena.core.task_manager import TaskManager
from liveweb_arena.core.validators.base import GeneratedQuestion, get_template
from liveweb_arena.plugins.base import SubTask


@dataclass(frozen=True)
class ProbeResult:
    template_name: str
    plugin_name: str
    seed: int
    variant: Optional[int]
    question_text: str
    validation_info: Dict[str, Any]
    probe_urls: List[str]
    gt_ok: bool
    gt_value: Optional[str]
    gt_error: Optional[str]


def _safe_json_dumps(x: Any) -> str:
    try:
        return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return json.dumps(str(x), ensure_ascii=False)


def _infer_probe_urls(plugin_name: str, question: GeneratedQuestion) -> List[str]:
    """
    Produce a minimal set of URLs likely sufficient for GT.

    This is intentionally conservative and template-agnostic.
    It first uses template-declared probe URLs (if provided), then falls back
    to compatibility heuristics based on common validation_info fields.
    """
    urls: List[str] = []
    if question.start_url:
        urls.append(question.start_url)

    template_cls = get_template(question.template_name)
    if template_cls is not None:
        try:
            template = template_cls()
            declared_urls = template.get_probe_urls(question.validation_info or {})
            if declared_urls:
                urls.extend(declared_urls)
        except Exception:
            # Keep probe resilient; fallback heuristics still apply.
            pass

    vi = question.validation_info or {}

    # Open Library templates often require collecting works for both queries.
    if plugin_name == "openlibrary":
        a = vi.get("book_a_query")
        b = vi.get("book_b_query")
        subject = vi.get("subject")
        if isinstance(a, str) and a.strip():
            urls.append(f"https://openlibrary.org/search?q={quote_plus(a)}")
        if isinstance(b, str) and b.strip():
            urls.append(f"https://openlibrary.org/search?q={quote_plus(b)}")
        if isinstance(subject, str) and subject.strip():
            urls.append(f"https://openlibrary.org/subjects/{quote_plus(subject)}")

    # ArXiv listing tasks commonly depend on category.
    if plugin_name == "arxiv":
        category = vi.get("category")
        if isinstance(category, str) and category.strip():
            urls.append(f"https://arxiv.org/list/{category}/recent")

    # Hacker News tasks generally depend on homepage.
    if plugin_name == "hackernews":
        if "news.ycombinator.com" not in " ".join(urls):
            urls.append("https://news.ycombinator.com/")

    # Stooq tasks generally depend on quote pages.
    if plugin_name == "stooq":
        symbol = vi.get("symbol") or vi.get("symbol_a") or vi.get("symbol_b")
        if isinstance(symbol, str) and symbol.strip():
            urls.append(f"https://stooq.com/q/?s={quote_plus(symbol)}")

    # De-duplicate while preserving order.
    seen = set()
    out = []
    for u in urls:
        if not isinstance(u, str) or not u.strip():
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


async def probe_task_ground_truth(
    *,
    task_manager: TaskManager,
    subtasks: Sequence[SubTask],
    questions: Sequence[GeneratedQuestion],
    plugin_names: Sequence[str],
    seed: int,
    variant: Optional[int],
) -> List[ProbeResult]:
    """
    Probe GT for subtasks without running the LLM agent/browser.

    Strategy:
    - Create a GTCollector for the subtasks
    - For each subtask, call plugin.fetch_api_data() for probe URLs
    - Feed that api_data into GTCollector.on_page_visit()
    - Call GTCollector.fetch_remaining_api_gt() for template.get_ground_truth()

    NOTE: This is a quick API-level supplement. It does NOT replace full
    eval.py runs or the mandatory CLAUDE.md red team review process.
    """
    gt_collector = GTCollector(subtasks=list(subtasks), task_manager=task_manager)
    set_current_gt_collector(gt_collector)
    try:
        # Collect page-bound api_data by calling plugins directly (API semantic probe).
        for st, q, plugin_name in zip(subtasks, questions, plugin_names):
            plugin = task_manager.get_plugin(plugin_name)
            probe_urls = _infer_probe_urls(plugin_name, q)
            for url in probe_urls:
                # Some navigation pages intentionally don't have api_data; respect plugin.
                if not plugin.needs_api_data(url):
                    continue
                api_data = await plugin.fetch_api_data(url)
                if not api_data:
                    raise RuntimeError(
                        f"Probe API returned empty data for {plugin_name} url={url}"
                    )
                # content isn't used for GT in this flow; keep empty.
                await gt_collector.on_page_visit(url, content="", api_data=api_data)

        await gt_collector.fetch_remaining_api_gt()

        results: List[ProbeResult] = []
        for st, q, plugin_name in zip(subtasks, questions, plugin_names):
            tag = st.answer_tag
            gt_value = gt_collector.get_gt_for_subtask(st)
            if gt_value is not None:
                results.append(
                    ProbeResult(
                        template_name=q.template_name,
                        plugin_name=plugin_name,
                        seed=seed,
                        variant=variant,
                        question_text=q.question_text,
                        validation_info=dict(q.validation_info),
                        probe_urls=_infer_probe_urls(plugin_name, q),
                        gt_ok=True,
                        gt_value=str(gt_value),
                        gt_error=None,
                    )
                )
            else:
                reason = gt_collector.get_failure_reason(st)
                results.append(
                    ProbeResult(
                        template_name=q.template_name,
                        plugin_name=plugin_name,
                        seed=seed,
                        variant=variant,
                        question_text=q.question_text,
                        validation_info=dict(q.validation_info),
                        probe_urls=_infer_probe_urls(plugin_name, q),
                        gt_ok=False,
                        gt_value=None,
                        gt_error=reason,
                    )
                )
        return results
    finally:
        set_current_gt_collector(None)
        gt_collector.cleanup()


def validation_info_signature(validation_info: Dict[str, Any]) -> str:
    """
    Canonical signature for collapse detection.

    Excludes volatile/non-semantic keys by convention.
    """
    if not isinstance(validation_info, dict):
        return _safe_json_dumps(validation_info)
    vi = dict(validation_info)
    for k in ("template_name", "_template_name"):
        vi.pop(k, None)
    return _safe_json_dumps(vi)

