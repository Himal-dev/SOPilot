# Plant Doctor AWS Architecture

## Current Deployment

Plant Doctor is hosted in AWS account `746486153317` in `ap-south-1`.
Credentials were used from environment variables only; do not write AWS,
OpenAI, ElevenLabs, or trial-code secrets into repo files.

Current public app URL:
<https://sopilot-plant-doctor-site-746486153317-20260531.s3.ap-south-1.amazonaws.com/index.html>

All supported AWS resources must carry the tag
`Owner=himalmangla@gmail.com`.

## Current Low-Cost Trial Stack

| Layer | AWS choice | Current behavior |
| --- | --- | --- |
| Web app | S3 HTTPS object URL | Static `app/web` bundle, no build step, phone-safe HTTPS for camera/mic permissions. |
| API | Lambda Function URL | FastAPI app packaged with Mangum, no API Gateway or always-on compute. |
| Runtime | Lambda Python 3.12 | 1024 MB, 120 second timeout, auto-finalizes the Plant Doctor report for trial use. |
| Secrets | Lambda environment variables | `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_PLANT_DOCTOR_AGENT_ID`, and `PLANT_DOCTOR_TRIAL_CODE`. Move to SSM/Secrets Manager before broader beta. |
| Trial auth | Invite code | Browser sends `x-trial-code`; backend compares it with `PLANT_DOCTOR_TRIAL_CODE`. The code is not embedded in static config. |
| CORS | Lambda Function URL CORS | Function URL owns CORS. Keep app-level `PLANT_DOCTOR_CORS_ORIGINS` empty in hosted Lambda to avoid duplicate `Access-Control-Allow-Origin` headers. |
| Logs | CloudWatch Logs | Structured JSON session events from `sopilot.session_logging`, with 7-day retention. |
| Cost guardrail | AWS Budget | Best-effort monthly budget named `sopilot-plant-doctor-monthly-10usd`. |

The deploy script writes local, ignored metadata:

- `deploy/aws/plant_doctor_last_deploy.json`: app/API URL and resource names.
- `deploy/aws/plant_doctor_trial_code.txt`: current invite code.

## Request Flow

1. Browser loads static HTML/CSS/JS from S3.
2. Browser loads `config.js`, which contains the API URL and whether auth is
   required. It intentionally does not contain the trial code.
3. User enters the invite code.
4. Browser calls `GET /api/auth/check` with `x-trial-code` and `x-session-id`.
5. API requests use the same `x-session-id`, so CloudWatch events can be traced
   session by session.
6. ElevenLabs conversation-token creation and OpenAI report generation happen
   server-side only.

## Deploy

Set credentials and provider keys in the shell, then run:

```bash
export AWS_DEFAULT_REGION=ap-south-1
export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...
export PLANT_DOCTOR_TRIAL_CODE="$(cat deploy/aws/plant_doctor_trial_code.txt)"
./deploy/aws/deploy_plant_doctor.sh
```

When rotating the invite code, set a new `PLANT_DOCTOR_TRIAL_CODE` before
deploying. When preserving the current code, export it from the ignored local
file as shown above.

## Verification

After deploy, verify:

- S3 app URL returns `200`.
- Lambda `/api/health` returns `{"ok": true}`.
- `/api/auth/check` returns `401` for a wrong code and `200` for the current
  `PLANT_DOCTOR_TRIAL_CODE`.
- Browser unlocks the UI with the current code.
- `GET /api/elevenlabs/session` returns `enabled: true` and `auth:
  private_webrtc` when provider keys are configured.
- CORS response has exactly one `Access-Control-Allow-Origin` header.
- CloudWatch log retention for `/aws/lambda/sopilot-plant-doctor-api` is 7 days.

## Next Architecture Step

The shipped trial intentionally avoids fixed spend: no NAT Gateway, ALB, RDS,
ECS service, OpenSearch, API Gateway, or always-on instance.

For a broader beta, add:

- CloudFront with a custom domain in front of S3 and Lambda Function URL.
- Cognito or signed short-lived sessions if testers are no longer invite-only.
- Durable session/report/photo storage in DynamoDB and private S3 with explicit
  user consent and lifecycle deletion.
- SSM Parameter Store or Secrets Manager for provider secrets and invite-code
  rotation.
- WAF/rate limits and CloudWatch alarms for provider failures, Lambda errors,
  and report-generation latency.

## Historical Note

The earlier hackathon AWS account `884692409757` was blocked by explicit
`HackathonExpiry` denies on S3, IAM, and Lambda operations. That account should
not be used for Plant Doctor unless the account administrator removes the deny
policy or provides a narrow deploy role.
