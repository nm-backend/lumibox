# lumibox — Project Journal

Persistence anchor for this workspace's agent memory. The agent maintains this file:
append notable decisions, changes, and session notes so they survive across chats and
sessions. Newest entries on top. `get_project_briefing` reads the sections below.

## About

LumiBox is a full-featured online cinema and media portal built with Django, featuring multi-source video playback (Vibix external player SDK, YouTube fallback player, and byte-range local video player), rich catalog filtering, ratings, user reviews, collections, and mobile-first responsive design.

## Recent Changes

- **Vibix Integration & Auto-Recovery**: Refreshed Vibix API bearer token authentication, implemented `login_vibix` automatic authentication fallback, sanitized `fetch_video_links` limit parameter (20, 50, 100), and added graceful fallback from 403 detail endpoints to `/videos/links` catalog lookup.
- **Sync Architecture Hardening**: Updated `sync_title` in `apps/catalog/video_service_sync.py` to extract `player_id` from `embed_code` and sync series seasons/episodes seamlessly.
- **Automated Verification**: Added comprehensive test suite `apps/catalog/tests/test_vibix_e2e.py` (all 770 Django tests passing) and Playwright browser E2E test `tests_e2e_playwright.js` verifying player gate button, SDK injection, and 6 mobile viewports (320px–1440px) with zero overflow.

## Session Memory

- Vibix API base URL: `https://api.vibix.org/api/v1`
- Publisher ID: `678503345` (User ID `1184`)
- Catalog size: 31,037 titles in `/publisher/videos/links`
- Rendex SDK URL: `https://graphicslab.io/sdk/v2/rendex-sdk.min.js`

