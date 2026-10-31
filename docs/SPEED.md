# Document reading speed (classify + digitise), measured

`scripts/time_documents.py` times page classification + digitisation with real model calls and a fresh cache per run
(litellm imported before the clock starts, as in the running server). Ground truth: CLM-2026-0033 bill = 29 charge lines
= 76,024 = printed net payable; CLM-2026-0032 = two phone photos of the bill (19 lines = 75,417 = printed total).

| Path | CLM-2026-0033 (3 native PDF pages) | CLM-2026-0032 (2 photos) | Reads / reconciles | Cost (both) |
|---|---|---|---|---|
| Before: Kimi K2.5, every page as an image, 3-page classify batches, 4-page document batches | **44.44 s** | **26.12 s** | 29 = 76,024 yes / 19 = 75,417 yes | $0.144 |
| Kimi K2.5, images, every page in parallel | 30.81 s | 24.89 s | yes / yes | $0.159 |
| Sonnet 5, text layer, parallel (cold import) | 107.12 s | - | yes | $0.79 (one claim) |
| **After (default): Haiku 4.5, text layer for native PDF pages, every page in parallel** | **19.66 s** | **23.09 s** | 29 = 76,024 yes / 19 = 75,417 yes | $0.245 |

0033 is 2.3x faster (44.4 s -> 19.7 s). The photos gain less (26.1 s -> 23.1 s; run-to-run 19-23 s) because they still go as images.
Live portal trial (port 8022, temp store): submit answered 201 in 0.5 s; under review after 35 s, 29 lines read, reconciled.

Switches: `LEAKLENS_DOC_MODEL` (default `bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0`; Kimi
`bedrock/moonshotai.kimi-k2.5` is the fallback, and the old path is `LEAKLENS_DOC_MODEL=bedrock/moonshotai.kimi-k2.5
LEAKLENS_TEXT_LAYER=0`). A PDF page with >= 200 characters of text is sent as text rows; scans and photos as images.
