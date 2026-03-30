from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

from liveweb_arena.core.cache import (
    CacheFatalError,
    CacheManager,
    PageRequirement,
    normalize_url,
)
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

    Prefer template-declared URLs via get_probe_urls(validation_info), then
    compatibility heuristics based on common validation_info fields.
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
            pass

    vi = question.validation_info or {}

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

    if plugin_name == "arxiv":
        category = vi.get("category")
        if isinstance(category, str) and category.strip():
            urls.append(f"https://arxiv.org/list/{category}/recent")

    if plugin_name == "hackernews":
        if "news.ycombinator.com" not in " ".join(urls):
            urls.append("https://news.ycombinator.com/")

    if plugin_name == "stooq":
        symbol = vi.get("symbol") or vi.get("symbol_a") or vi.get("symbol_b")
        if isinstance(symbol, str) and symbol.strip():
            urls.append(f"https://stooq.com/q/?s={quote_plus(symbol)}")

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
    cache_manager: CacheManager,
    subtasks: Sequence[SubTask],
    questions: Sequence[GeneratedQuestion],
    plugin_names: Sequence[str],
    seed: int,
    variant: Optional[int],
) -> List[ProbeResult]:
    """
    Probe GT without the LLM agent, using the same cache pipeline as evaluation.

    For each probe URL, ``CacheManager.ensure_cached`` loads (or reuses) an
    atomic page snapshot ``{html, api_data, accessibility_tree, fetched_at}``
    — the same path as production cache mode. Visits are then applied to
    ``GTCollector.on_page_visit`` with that snapshot's ``api_data`` and a11y
    tree, matching ``env._handle_observation_event`` in cache mode.

    This does **not** simulate agent navigation order or multi-hop trajectories;
    it only validates GT against cache-bound data. It supplements, but does not
    replace, full ``eval.py`` runs or CLAUDE.md red-team review.
    """
    gt_collector = GTCollector(subtasks=list(subtasks), task_manager=task_manager)
    set_current_gt_collector(gt_collector)
    prefetch_errors: Dict[str, str] = {}

    try:
        for st, q, plugin_name in zip(subtasks, questions, plugin_names):
            tag = st.answer_tag
            plugin = task_manager.get_plugin(plugin_name)
            probe_urls = _infer_probe_urls(plugin_name, q)
            pages: List[PageRequirement] = []
            for url in probe_urls:
                if not plugin.needs_api_data(url):
                    pages.append(PageRequirement.nav(url))
                else:
                    pages.append(PageRequirement.data(url))

            try:
                cached_map = await cache_manager.ensure_cached(pages, plugin)
            except CacheFatalError as e:
                prefetch_errors[tag] = f"Cache pipeline failed: {e}"
                continue
            except Exception as e:
                prefetch_errors[tag] = f"Cache pipeline error: {type(e).__name__}: {e}"
                continue

            # Build visit list first so we never partially merge into GT on a missing key.
            visits: List[Tuple[str, str, Any]] = []
            for url in probe_urls:
                norm = normalize_url(url)
                cached = cached_map.get(norm)
                if cached is None:
                    prefetch_errors[tag] = (
                        f"Cache map missing key after ensure_cached: {norm!r} (url={url!r})"
                    )
                    visits = []
                    break
                visits.append(
                    (cached.url, cached.accessibility_tree or "", cached.api_data),
                )

            if tag in prefetch_errors:
                continue

            for vurl, a11y, api_data in visits:
                await gt_collector.on_page_visit(
                    vurl,
                    content=a11y,
                    api_data=api_data,
                )

        await gt_collector.fetch_remaining_api_gt()

        results: List[ProbeResult] = []
        for st, q, plugin_name in zip(subtasks, questions, plugin_names):
            tag = st.answer_tag
            urls = _infer_probe_urls(plugin_name, q)

            if tag in prefetch_errors:
                results.append(
                    ProbeResult(
                        template_name=q.template_name,
                        plugin_name=plugin_name,
                        seed=seed,
                        variant=variant,
                        question_text=q.question_text,
                        validation_info=dict(q.validation_info),
                        probe_urls=urls,
                        gt_ok=False,
                        gt_value=None,
                        gt_error=prefetch_errors[tag],
                    )
                )
                continue

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
                        probe_urls=urls,
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
                        probe_urls=urls,
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
