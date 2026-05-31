# Plant Doctor AWS Architecture

## Credential Status

AWS credentials were validated in-memory with `aws sts get-caller-identity` for
account `884692409757` and IAM user `himalmangla@gmail.com`. Do not write these
credentials into repo files; use environment variables, an AWS profile, or SSO
for deployment commands.

All AWS resources for this trial must include the tag
`Owner=himalmangla@gmail.com`.

## Goal

Host the Plant Doctor mobile trial over HTTPS with minimal fixed AWS spend while
preserving the live camera, microphone, ElevenLabs voice guide, OpenAI vision
analysis, and rich report UI. The architecture should be cheap at low traffic,
simple enough to operate during trials, and not require always-on compute.

## Recommended MVP Architecture

| Layer | AWS choice | Reason |
| --- | --- | --- |
| Web app | S3 private bucket + CloudFront | Low-cost static hosting, HTTPS for mobile camera/mic permissions, global caching. |
| API | Lambda Function URL behind CloudFront `/api/*` path | Serverless backend with no always-on instance, and no API Gateway cost for the MVP. |
| API framework | FastAPI packaged with Mangum | Reuses the current `app.server` shape with a thin ASGI-to-Lambda adapter. |
| Runtime state | DynamoDB on-demand table | Replaces local `/tmp/*.sqlite` checkpointers with durable per-session state for Lambda. |
| Photos/reports | Private S3 evidence bucket | Stores compressed plant photos and generated reports with short lifecycle retention. |
| Secrets | Lambda encrypted environment for hackathon deploy; SSM SecureString next | Keeps the first trial simple and low-cost; move to SSM before a broader beta. |
| Logs | CloudWatch Logs, 7-day retention | Enough to debug trial sessions without building a data lake. |
| Abuse controls | CloudFront origin header + small app token | Keeps casual direct traffic away from the Lambda URL. Add WAF only before broader launch. |
| Cost guardrail | AWS Budget alert | Alerts before trial traffic or provider retries consume credits unexpectedly. |

CloudFront should use two origins:

- Default origin: private S3 bucket serving `app/web`.
- `/api/*` origin: Lambda Function URL. CloudFront adds an origin-only header, and Lambda rejects requests missing it.

This keeps trial users on one HTTPS domain, which is cleaner for mobile browser
permissions and avoids mixed-origin surprises.

## Required App Changes Before Serverless Deploy

1. Replace the current temp SQLite checkpointer path in `/api/run` and
   `/api/decision`. Lambda `/tmp` is not durable across invocations, so approval
   resume cannot rely on `db_path`.
2. Store session state in DynamoDB keyed by `session_id` or `thread_id`, including
   captured care answers, report state, and review status.
3. Store uploaded photos in S3 instead of keeping only in request memory. The
   browser should resize/compress photos before upload to keep Lambda payloads
   small.
4. Package FastAPI for Lambda with `mangum` and keep static assets outside the
   Lambda bundle.
5. For the first hackathon deploy, pass `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`,
   and `ELEVENLABS_PLANT_DOCTOR_AGENT_ID` as Lambda environment variables. Move
   them to SSM SecureString before a broader beta.
6. Add production CORS and an app-token/origin-header gate to `/api/*`.
7. Set CloudWatch log retention and S3 lifecycle rules during deploy.
8. Apply the `Owner=himalmangla@gmail.com` tag to every supported resource.

## Deployment Phases

### Phase 1: Low-Cost Trial

- S3 + CloudFront frontend.
- Lambda Function URL backend.
- DynamoDB on-demand session table.
- S3 private evidence bucket with 7-30 day lifecycle expiration.
- Lambda environment secrets for the hackathon deploy, then SSM SecureString for beta.
- One AWS Budget alert.

This is the best default for scarce AWS credits because there is no NAT Gateway,
ALB, RDS, ECS service, OpenSearch, or always-on server.

### Phase 2: Safer Public Beta

- Add Cognito or signed session tokens if users are not invite-only.
- Add WAF managed rules and rate limiting on CloudFront.
- Add CloudWatch metric alarms for provider failures, Lambda errors, and report
  generation latency.
- Add consent capture and a deletion endpoint for photos/reports.

### Phase 3: Scale/Workflow

- Add SQS if uploads spike and reports can be generated asynchronously.
- Add Step Functions only if report generation becomes multi-step with retries,
  human review queues, or long-running provider calls.
- Move secrets to Secrets Manager if rotation and audit workflows become
  important.

## Fastest Possible Hosting Alternative

If the priority is a live URL today with minimal refactor, use one tiny
Lightsail/EC2 instance with Caddy HTTPS and run Uvicorn as a service. It can
reuse the current temp SQLite behavior more directly, but it creates an
always-on server to patch, monitor, and pay for. I would use this only for a
short demo window, not as the recommended trial architecture.

## Notes On The Existing AWS Folder

`deploy/aws/` currently targets the BoloBuddy/Kids Voice Assessment flow, not
Plant Doctor. It should not be reused as-is for this app because the backend
contracts, static assets, provider calls, and report storage model differ.

Plant Doctor now has a separate deployment script:
`deploy/aws/deploy_plant_doctor.sh`.

## Mobile Trial Checklist

- Use HTTPS on the final domain before phone testing.
- Test iOS Safari and Android Chrome for camera permission, microphone
  permission, WebRTC voice, background/lock behavior, and slow network recovery.
- Keep the UI voice-first: one `Start guide` action, guided photo capture, and
  report shown automatically.
- Log only session events needed for debugging. Treat plant photos as private
  home-context data and expire them quickly.
- Keep OpenAI and ElevenLabs keys server-side only.
