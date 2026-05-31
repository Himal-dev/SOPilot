# Scaffold Hardening Lessons From Plant Doctor

Plant Doctor exposed the parts of SOPilot that need to be generic for future
agents to become working apps with less custom glue.

## What Is Now General

- **App manifest:** `python -m sopilot manifest examples/<agent>` returns
  media requirements, provider readiness, review points, output fields, and
  runtime policy. UIs and voice agents can read this instead of hardcoding shot
  lists or interview questions.
- **Provider policy:** adapter config now supports `api_key_env`,
  `require_live`, and `stub_fallback`. Runtime config supports
  `require_live_adapters` and `allow_stub_fallback`, so production can fail
  closed while local demos remain deterministic.
- **Hosted auto-finalize:** `start_run(..., auto_finalize=True)` handles HITL
  approval in the runner itself. App servers no longer need to manually copy the
  interrupt/resume loop for trial deployments.
- **Reusable web security:** `sopilot.web_runtime.install_api_security(...)`
  adds optional CORS, public app-token gating, and server-side invite-code
  gating to FastAPI apps. Hosted Lambda Function URL deployments should let the
  Function URL own CORS and keep app-level CORS disabled to avoid duplicate
  browser CORS headers.
- **SOP-owned questions:** Plant Doctor's care routine questions now live in the
  SOP via `[ask: ...]`, so the scaffold can surface them consistently.
- **Media upload normalization:** `sopilot.media.build_media_map(...)` converts
  app-collected fields such as `whole_plant_photo` and `care_habits_audio` into
  adapter-ready `media[step_id]` payloads using the manifest.
- **Guided conversation contracts:** `sopilot.conversation` turns the manifest
  into state/capture/record/submit tool names, ElevenLabs client-tool configs,
  and prompt instructions. It infers record topics from `[ask: ...]`, includes
  retry guidance for weak media evidence, and still lets apps pass explicit
  `RecordTopic` values, structured interview fields, and product-specific
  tool-name overrides without forking the scaffold.
- **Report readiness:** `sopilot.reporting` derives report field requirements
  from the manifest, cleans collected outputs, detects missing/demo/failed or
  low-confidence evidence, and returns next-step/retry-media guidance. Domain
  apps can now keep only the expert report-writing layer local.
- **Report writing hook:** `sopilot.report_writer` centralizes the JSON report
  prompt shape and OpenAI client call. Apps provide the domain expert role,
  task, output contract, evidence policy, and style rules; product-specific
  normalization and UI view shaping stay local.
- **Report view skeleton:** `sopilot.report_view` builds common rich-report
  sections for subject summary, issue, root cause, recommendations, monitoring,
  escalation, evidence, confidence, warnings, and product aliases. Apps only
  add domain labels or extra fields.

## Still Worth Generalizing Next

- **Report renderer components:** Plant Doctor still has app-specific DOM
  rendering. A small shared browser renderer could consume `report_view.sections`
  across new apps.
- **Deployment templates:** `deploy/aws/deploy_plant_doctor.sh` is useful, but a
  generic `deploy/aws/deploy_agent.sh` should take an agent name, static app
  folder, API module, tags, resource prefix, invite-code policy, and CORS owner.
- **State stores:** local SQLite works for development, but serverless needs a
  durable store abstraction for interrupt/resume across Lambda invocations.
