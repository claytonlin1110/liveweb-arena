## Template Red Team Report

- **Generated**: 2026-03-26T12:33:24.775676+00:00
- **Mode**: api-probe (plugin.fetch_api_data → GTCollector)

## Summary

| Template | Samples | GT ok | Unique GT | Collapse | Baseline |
|---|---:|---:|---:|---:|---:|
| hackernews/hackernews_news_summary | 1 | 100.0% | 1 | 0.0% | 100.0% |

## Stability (repeat probe)

- **Comparable pairs**: 1/1
- **Stable GT**: 1 (stability=100.0%)

## Notes

- **Collapse**: computed as \(1 - \frac{\#distinct\_GT}{\#distinct\_validation\_signatures}\) over successful samples.
- **Baseline**: heuristic estimate (binary/2-option → 50%, else \(1/\#unique\_GT\)).
- **GT ok** depends on whether the probe URLs were sufficient to populate collected API data for the template.

