## Template Red Team Report

- **Generated**: 2026-03-26T12:34:03.774704+00:00
- **Mode**: api-probe (plugin.fetch_api_data → GTCollector)

## Summary

| Template | Samples | GT ok | Unique GT | Collapse | Baseline |
|---|---:|---:|---:|---:|---:|
| hackernews/hackernews_news_summary | 1 | 100.0% | 1 | 0.0% | 100.0% |

## Stability (repeat probe)

- **Comparable pairs**: 1/1
- **Stable GT**: 0 (stability=0.0%)

### Examples of changed GT (capped)
- **hackernews/hackernews_news_summary** seed=0 variant=None
  - Q: Summarize the top 3 stories on Hacker News in one sentence each.
  - GT-A: {"stories": [{"rank": 1, "title": "Personal Encyclopedias", "score": 348, "comments": 69, "author": "jrmyphlmn", "url": "https://whoami.wiki/blog/personal-encyclopedias"}, {"rank": 2, "title": "Swift 6.3", "score": 127, "comments": 60, "author": "ingve", "url": "https://www.swift.org/blog/swift-6.3-released/"}, {"rank": 3, "title": "From zero to a RAG system: successes and failures", "score": 62, "comments": 11, "author": "andros", "url": "https://en.andros.dev/blog/aa31d744/from-zero-to-a-rag-system-successes-and-failures/"}], "story_count": 3, "summary_type": "brief"}
  - GT-B: {"stories": [{"rank": 1, "title": "Personal Encyclopedias", "score": 348, "comments": 69, "author": "jrmyphlmn", "url": "https://whoami.wiki/blog/personal-encyclopedias"}, {"rank": 2, "title": "Swift 6.3", "score": 127, "comments": 60, "author": "ingve", "url": "https://www.swift.org/blog/swift-6.3-released/"}, {"rank": 3, "title": "From zero to a RAG system: successes and failures", "score": 63, "comments": 11, "author": "andros", "url": "https://en.andros.dev/blog/aa31d744/from-zero-to-a-rag-system-successes-and-failures/"}], "story_count": 3, "summary_type": "brief"}

## Notes

- **Collapse**: computed as \(1 - \frac{\#distinct\_GT}{\#distinct\_validation\_signatures}\) over successful samples.
- **Baseline**: heuristic estimate (binary/2-option → 50%, else \(1/\#unique\_GT\)).
- **GT ok** depends on whether the probe URLs were sufficient to populate collected API data for the template.

