# Plant Doctor AWS Deploy Status

## 2026-05-31

The app is ready for a low-cost AWS trial deploy, but the current IAM user is
blocked by an explicit `HackathonExpiry` policy.

Validated:

- AWS account `884692409757` is reachable with the provided IAM user.
- Required resource tag is `Owner=himalmangla@gmail.com`.
- Local app tests pass.
- A Plant Doctor-specific deploy script exists at
  `deploy/aws/deploy_plant_doctor.sh`.

Deployment blockers observed:

- `iam:ListAttachedUserPolicies`, `iam:ListUserPolicies`, `iam:GetPolicy`,
  `iam:ListPolicyVersions`, and `iam:SimulatePrincipalPolicy` are explicitly
  denied, so this user cannot inspect or simulate its own policy boundary.
- `s3:CreateBucket` is explicitly denied.
- `s3:ListAllMyBuckets` is explicitly denied.
- `s3:GetBucketTagging` is explicitly denied, including on known buckets.
- `s3:HeadBucket` and `s3:HeadObject` return `403` for known buckets, so even
  existing static-site buckets cannot be safely reused by this principal.
- `iam:CreateRole` is explicitly denied.
- `lambda:ListFunctions` is explicitly denied.
- `lambda:GetFunction` and `lambda:GetFunctionUrlConfig` are explicitly denied,
  including on known functions.

The deploy script was adjusted to support reusing an existing S3 bucket under a
prefix, but Lambda/IAM access is still required for the backend API.

Needed to deploy:

- A deploy IAM principal that can create/update one Lambda function, configure a
  Lambda Function URL, write static files to an S3 bucket or prefix, and tag
  resources with `Owner=himalmangla@gmail.com`; or
- Removal/relaxation of the explicit `HackathonExpiry` denies for the existing
  IAM user.

Bypassing the policy is not a valid or reliable route. The clean path is to ask
the account administrator to either extend/remove `HackathonExpiry` for this
user, or provide a narrow deploy role scoped to Plant Doctor resources.

Minimum useful scope:

- `s3:PutObject`, `s3:DeleteObject`, `s3:GetObject`, and `s3:ListBucket` on one
  static-site bucket/prefix.
- `lambda:CreateFunction`, `lambda:UpdateFunctionCode`,
  `lambda:UpdateFunctionConfiguration`, `lambda:GetFunction`,
  `lambda:CreateFunctionUrlConfig`, `lambda:UpdateFunctionUrlConfig`,
  `lambda:GetFunctionUrlConfig`, `lambda:AddPermission`, `lambda:TagResource`,
  and `lambda:InvokeFunctionUrl` for `sopilot-plant-doctor-*`.
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`, `iam:GetRole`, and
  `iam:TagRole` for one Lambda execution role, or provide a pre-created role
  ARN and only allow `iam:PassRole` on that role.
- `logs:PutRetentionPolicy` for `/aws/lambda/sopilot-plant-doctor-*`.
- Optional `budgets:CreateBudget` for the low-credit guardrail.
