## Template Red Team Report

- **Generated**: 2026-03-26T12:38:28.148104+00:00
- **Mode**: api-probe (plugin.fetch_api_data → GTCollector)

## Summary

| Template | Samples | GT ok | Unique GT | Collapse | Baseline |
|---|---:|---:|---:|---:|---:|
| hackernews/hackernews_category_comparison | 1 | 0.0% | 0 | 0.0% | 100.0% |
| hackernews/hackernews_multi_condition_filter | 1 | 0.0% | 0 | 0.0% | 100.0% |
| hackernews/hackernews_extrema_comparison | 1 | 100.0% | 1 | 0.0% | 100.0% |
| hackernews/hackernews_news_summary | 1 | 100.0% | 1 | 0.0% | 100.0% |

## GT probe failures (capped)
- **hackernews/hackernews_category_comparison** seed=0 variant=None
  - Q: On Hacker News, does the top-2 Ask HN post or the top-2 Show HN post have more discussion?
  - Error: #2 story in Ask HN not found. Agent needs to visit Ask HN category page.
- **hackernews/hackernews_multi_condition_filter** seed=0 variant=None
  - Q: Among the top 20 stories on HN, how many have more than 50 comments but a score under 200?
  - Error: Only 19 stories have complete data (need 20). Available ranks: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20]. Agent may need to visit more story detail pages.

## Notes

- **Collapse**: computed as \(1 - \frac{\#distinct\_GT}{\#distinct\_validation\_signatures}\) over successful samples.
- **Baseline**: heuristic estimate (binary/2-option → 50%, else \(1/\#unique\_GT\)).
- **GT ok** depends on whether the probe URLs were sufficient to populate collected API data for the template.

