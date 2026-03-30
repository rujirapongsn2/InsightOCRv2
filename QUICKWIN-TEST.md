# QUICKWIN TEST

Date: 2026-03-30

## Manual Verification

1. Static checks
   - Ran `python -m py_compile` on updated backend modules including `external.py`, `permissions.py`, `api.py`, `documents.py`, `jobs.py`, and schemas.
   - Ran `git diff --check`.
   - Ran `bash -n scripts/services.sh`.

2. Rebuild and runtime
   - Ran `./scripts/services.sh rebuild all`.
   - Confirmed `backend`, `frontend`, and `nginx` return to healthy/running state.
   - Confirmed `https://127.0.0.1/health` returns `200 {"status":"ok"}`.

3. External API
   - Confirmed `GET /api/v1/external/jobs` returns `200` with job list using a personal access token.
   - Confirmed `GET /api/v1/external/schemas` returns `200` with schema list using a personal access token.
   - Confirmed `GET /api/v1/external/integrations` returns `200` with active integrations using a personal access token.
   - Confirmed `/api/v1/openapi.json` includes the `/api/v1/external/...` routes and schemas.

4. Profile page
   - Confirmed `https://127.0.0.1/profile` contains the new `API Workflow Docs` section and endpoint examples.

5. End-to-end agent workflow
   - Used a personal access token against the `Comply TOR` job flow.
   - Confirmed `GET /api/v1/external/jobs` returned the `Comply TOR` job and `GET /api/v1/external/integrations` returned the `Comply TOR` integration.
   - Confirmed `GET /api/v1/external/jobs/{job_id}/documents` returned the expected two reviewed documents.
   - Confirmed both documents through `POST /api/v1/external/documents/{document_id}/decision` with `decision=confirm`.
   - Sent the confirmed job through `POST /api/v1/external/jobs/{job_id}/send-integration` with `integration_name=Comply TOR`.
   - Verified the send call returned `200` and a new success result was recorded in `GET /api/v1/integrations/results`.

## Notes

- `scripts/services.sh rebuild all` now restarts `nginx` and waits for health checks, preventing stale upstream IPs from causing `502 Bad Gateway` after container recreation.
- Local HTTPS still uses a self-signed certificate, so local `curl` verification used `-k`.
- Long-running integration calls initially hit the default `nginx` `proxy_read_timeout` of 60 seconds and surfaced as `504 Gateway Timeout` even though the backend job completed successfully. Added longer `nginx` timeouts for integration send routes and re-verified the full `Comply TOR` flow successfully.
