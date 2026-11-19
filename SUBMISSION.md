# QUEST precipitation explorer — submission checklist

## Live app

https://questlab-precipitation-explorer.onrender.com

Hosted as a Render Free Docker service. The public source repository includes the application and the selected processed forecast snapshots used by the image; raw GRIB/cache data are excluded.

## Reviewer summary

QUEST is a browser-based precipitation forecast explorer comparing ECMWF AIFS Single and IFS over a bounded 20° × 30° region. The user can move the regional window, choose a forecast step, switch between cumulative precipitation and six-hour increments, and click a cell to see the complete forecast fingerprint at that location for both models. This is a substantive front-end interaction because it links a point's time sequence to the surrounding spatial pattern: a static map can show where rain is forecast, but not how that clicked location evolves across forecast steps alongside its regional context. The interface also exposes source-run age, stale status, and interval clipping counts so the comparison remains inspectable.

## Verified

- Live deployment and HTTPS in Edge and Brave; same-origin `/api/*` calls worked without CORS configuration.
- Both regional forecast fields and the point profile rendered with the pinned 2026-11-18 18Z artifacts.
- Region changes, forecast-step/field selection, and click-to-select-cell interactions loaded new data.
- Freshness state: the forecast remained viewable with a visible stale banner beyond the 12-hour threshold.
- Clipping counts reconciled against the local container at step 24 h: India `bbox=62.5,3,92.5,23` returned AIFS 11 / IFS 678; southern Pacific `bbox=-170,-22.5,-140,-2.5` returned AIFS 0 / IFS 211. Both regions are 81 × 121 cells and the pairs describe different regions.
- Health and point responses returned data; unavailable step 48 returned the available-step error listing `[6,12,18,24]`.
- Local Docker outage behavior: stopping only Uvicorn left nginx `/` at 200 and proxied API health at 502. The separate local static preview displayed the API-unavailable UI when its API was down.
- Coarse cold/warm observations in Edge on 2026-11-19: Render's incoming-request marker was 21:53:43 IST; the QUEST shell was observed by 21:54:18, but its initial API request returned 502. Health returned available at 21:55:31. After manually navigating home, the fields and point profile were populated by 21:55:58, about 134 seconds after the initial request and about 7 seconds after the reload.
- The Codex session rollout file retains visible event history before its compaction markers. The Stage 0 no-compaction process rule was violated, but the raw JSONL event history was not truncated. Marker times, byte count, line count, and pre-marker ranges are documented in [DECISIONS.md](DECISIONS.md) and [SESSION_NOTES.md](SESSION_NOTES.md).

## Not verified / limitations

- Exact DevTools First Contentful Paint and Load-event metrics were not captured. The shell observation is not an FCP measurement. Coarse timestamps show a visible free-tier wake delay; the initial API 502 did not retry automatically, so a manual reload was needed. The observed data-ready time was about 134 seconds from the first cold request. A later warm navigation showed data within about 7 seconds.
- Render-host API-only failure was not tested. Render Free runs nginx and Uvicorn in one service/container and does not allow stopping Uvicorn independently while nginx remains available. API-only failure behavior on Render is inferred from local tests, not observed. A whole-service restart was not used because it would stop both frontend and API and would not test the app's API-unavailable UI.
- A Render restart or pause test was not performed; no closest-equivalent result is claimed.
- The forecast files are a fixed snapshot without scheduled ingest. The UI reports actual age and stale status; refreshing data requires a new available ECMWF run and redeployment. Render Free can sleep after inactivity.

## Session record

- Rollout file: `C:\Users\panji\.codex\sessions\2026\11\19\rollout-2026-11-19T10-07-26-01a1f218-5ff0-73b3-9394-e61118a92b59.jsonl`
- At the integrity inspection (2026-11-19 21:50 IST), size was 25,394,318 bytes and the file had 4,930 lines. Four compaction markers appeared at lines 1,518, 2,487, 3,830, and 4,756; prior visible event history was retained before each marker. The latest marker was at 13:54:59 IST. This was a context-management event, not log truncation. The log records visible messages and tool events, not private internal reasoning.
- Last source/verification commit before this checklist: `80f84197c974833cbc9080e8a62ab78f1160a10a` (Stage 5.5.4). The Stage 5.5.5 checklist commit is the final commit for this close-out; its hash is reported in the close-out message because a Git commit cannot contain its own hash without changing that hash.
