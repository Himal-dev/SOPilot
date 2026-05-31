# Plant Doctor AWS Deploy Status

## 2026-05-31 Current Status

Plant Doctor is live in AWS account `746486153317` using the new `ai-agent-dev`
deployment principal.

Validated:

- Hosted app:
  <https://sopilot-plant-doctor-site-746486153317-20260531.s3.ap-south-1.amazonaws.com/index.html>
- Backend API: Lambda Function URL recorded in the ignored local file
  `deploy/aws/plant_doctor_last_deploy.json`.
- Required resource tag `Owner=himalmangla@gmail.com` is present on the S3 site
  bucket and Lambda function.
- Lambda runtime is Python 3.12, 1024 MB, 120 second timeout.
- Lambda Function URL CORS allows `content-type`, `x-app-token`,
  `x-trial-code`, `x-session-id`, and `authorization`. `x-app-token` remains
  allowed for compatibility, but Plant Doctor leaves the token value empty.
- App-level CORS is disabled in hosted Lambda (`PLANT_DOCTOR_CORS_ORIGINS=""`)
  so browsers do not receive duplicate `Access-Control-Allow-Origin` headers.
- Invite code auth is enforced by `PLANT_DOCTOR_TRIAL_CODE`; the code is stored
  only in Lambda environment and the ignored local file
  `deploy/aws/plant_doctor_trial_code.txt`.
- `GET /api/auth/check` returns `401` for a wrong code and `200` for the current
  invite code.
- `GET /api/elevenlabs/session` returns `enabled: true` with
  `auth: private_webrtc` after unlock.
- CloudWatch structured session logs include `auth_check` and
  `voice_session_config` events keyed by `x-session-id`.
- CloudWatch log retention is set to 7 days.
- AWS Budget `sopilot-plant-doctor-monthly-10usd` exists.
- The temporary Lightsail fallback instance/key used during IAM debugging was
  deleted after Lambda deploy succeeded.
- Private GitHub repo is `https://github.com/Himal-dev/SOPilot`.

## Deployment Command

Use environment variables; do not store provider or AWS credentials in repo
files.

```bash
export AWS_DEFAULT_REGION=ap-south-1
export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
export ELEVENLABS_PLANT_DOCTOR_AGENT_ID=...
export PLANT_DOCTOR_TRIAL_CODE="$(cat deploy/aws/plant_doctor_trial_code.txt)"
./deploy/aws/deploy_plant_doctor.sh
```

The script preserves low fixed spend by using S3 HTTPS static hosting and a
Lambda Function URL. It writes ignored local metadata and does not commit the
trial code.

## Known Operational Notes

- If the browser says the valid code does not work, first hard refresh. If it
  still fails, check the auth response headers and confirm there is exactly one
  `Access-Control-Allow-Origin` header.
- Lambda Function URL owns hosted CORS. Do not set `PLANT_DOCTOR_CORS_ORIGINS`
  to `*` in the hosted Lambda env; that creates duplicate CORS headers.
- The app token is intentionally empty for Plant Doctor. It is public by nature
  in a static web app and is not useful as real auth. The invite code is the
  trial gate.
- Budget creation is best-effort in the deploy script. It may print a warning
  if the budget already exists.
- Current report/photo handling is request-scoped for the trial. Add durable S3
  evidence storage and deletion workflows before broader beta.

## Historical Blocker In Old AWS Account

The original hackathon account `884692409757` was reachable but blocked by an
explicit `HackathonExpiry` policy.

Observed denies included:

- `s3:CreateBucket`, `s3:ListAllMyBuckets`, `s3:GetBucketTagging`, `s3:HeadBucket`,
  and `s3:HeadObject`.
- `iam:CreateRole`, IAM policy inspection, and IAM simulation actions.
- `lambda:ListFunctions`, `lambda:GetFunction`, and
  `lambda:GetFunctionUrlConfig`.

Bypassing that policy is not a valid route. Use the new account, or ask the old
account administrator for a narrow deploy role scoped to Plant Doctor resources.
