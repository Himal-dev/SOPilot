# BoloBuddy AWS Deployment

This deployment turns the Kids Voice Assessment example into a small hosted
product:

- HTTPS static app and admin dashboard through S3 object HTTPS. CloudFront is
  optional and disabled by default because some hackathon AWS accounts deny
  distribution creation through Organizations SCPs.
- Public Lambda Function URL API with an app-token gate for assessment calls.
- Real ElevenLabs STT and Forced Alignment from the backend.
- Private S3 report/audio evidence bucket with server-side encryption.
- S3-backed session metadata for admin search by default. DynamoDB remains
  optional for accounts that allow table creation.
- CloudWatch Lambda logs with 30-day retention.
- Best-effort AWS Budget email alert at 80 USD/month.

## Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | Static HTML/CSS/JS on S3 HTTPS, optional CloudFront | No build step, HTTPS for microphone capture, low ops cost. |
| API | Python 3.12 Lambda Function URL | Serverless, low fixed cost, no API Gateway cost for MVP. |
| Voice AI | ElevenLabs Scribe v2 + Forced Alignment | Real provider path; no mock STT/alignment in production. |
| Storage | S3 private bucket | Full JSON reports, raw audio, optional isolated audio. |
| Metadata | S3 JSON session index by default, optional DynamoDB | Session list, status, review flags, report pointer without requiring DynamoDB permissions. |
| Logs | CloudWatch Logs | Request/provider/review events from Lambda. |
| App/API gate | Static app token injected at deploy time | Keeps casual anonymous traffic away from assessment/session endpoints. This is not a substitute for real user auth. |
| Admin auth | Static admin token | Good enough for hackathon MVP; replace with Cognito before production schools. |

## Budget Shape

For a pilot workload, the AWS part should stay well below an 80 USD/month AWS
budget. The largest variable cost is likely the external voice provider, not AWS.

Suggested starting assumptions:

- 500-2,000 assessments/month.
- 3 recordings per assessment.
- Lambda 512 MB, 30-90 seconds worst case while calling ElevenLabs.
- Raw audio retained 30 days.
- CloudWatch log retention 30 days.
- S3 session metadata by default; DynamoDB pay-per-request only if enabled.
- No NAT Gateway, ECS, RDS, OpenSearch, or always-on server.

Upgrade triggers:

- Add Cognito when real admins/teachers need accounts.
- Add CloudFront custom domain + ACM when brand domain is available.
- Add Step Functions only if assessments become long-running/retry-heavy.
- Add SQS if uploads spike and async processing is acceptable.
- Add WAF/rate limits before public launch.

## Deploy

Set AWS credentials for the target account and region. India-friendly default is
`ap-south-1`.

```bash
export AWS_DEFAULT_REGION=ap-south-1
export ELEVENLABS_API_KEY=...
export ELEVENLABS_STT_MODEL_ID=scribe_v2
export BUDGET_LIMIT_USD=80
export DATA_STORE=s3
export USE_CLOUDFRONT=false
./deploy/aws/deploy.sh
```

If `ELEVENLABS_API_KEY` is absent, the site still deploys, but assessment runs
return `provider_config_required` instead of using mock transcription. That is
intentional: production does not silently fall back to mock STT/alignment.

Budget creation is best-effort. If the IAM user cannot create AWS Budgets, the
deploy continues and prints a warning so the product is still reachable.

The default hosted URL is the S3 HTTPS object URL, not the `s3-website` HTTP
endpoint, so browser microphone capture can work in a secure context. Set
`USE_CLOUDFRONT=true` only in AWS accounts where CloudFront creation is allowed.

Some restricted AWS accounts enforce service-control policies that deny
DynamoDB table creation or CloudFront distribution creation. The default
`DATA_STORE=s3` and `USE_CLOUDFRONT=false` settings are the production-minded
fallback for that environment.

The script writes:

- `deploy/aws/last_deploy.json`: site URL, API URL, bucket/table names.
- `deploy/aws/admin_token.txt`: admin dashboard token.
- `deploy/aws/app_token.txt`: app token used by the hosted child UI.

The app token is embedded into the static page so browsers can create sessions
and run assessments. Treat it as an abuse-reduction gate, not a secret. The
admin token is never embedded in the page and is required for the admin session
list and full report inspection.

## Product Notes

Child mode:

- Ages 3-8 only.
- Age is collected at session start.
- Different batteries are selected for 3-4, 5-6, and 7-8.
- Child feedback is short, warm, and score-free.

Admin/parent report:

- Full report includes selected age battery, per-task evidence, domain scores,
  insights, exercises, uncertainty, and human review flags.
- Reports are educational observations, not IQ tests, clinical diagnosis, or
  intelligence labels.

## Production Hardening Backlog

- Replace admin token with Cognito user pools and role-based access.
- Replace the static app token with Cognito, signed short-lived session tokens,
  and per-school tenancy controls.
- Move ElevenLabs key to Secrets Manager and load at cold start.
- Add object-level retention policy and deletion workflow for child data.
- Add S3 Object Lock only if compliance requirements demand it.
- Add CloudFront WAF managed rules and rate limiting.
- Add CloudWatch metric alarms for provider errors and human-review spikes.
- Add a moderation/review workflow before releasing reports to parents.
- Add consent record exports and audit event viewer.
