#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_DIR="$ROOT_DIR/deploy/aws"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
STACK_PREFIX="${STACK_PREFIX:-sopilot-plant-doctor}"
OWNER_TAG_VALUE="${OWNER_TAG_VALUE:-himalmangla@gmail.com}"
BUDGET_LIMIT_USD="${BUDGET_LIMIT_USD:-25}"
CREATE_BUDGET="${CREATE_BUDGET:-true}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is required." >&2
  exit 1
fi
if [ -z "${ELEVENLABS_API_KEY:-}" ]; then
  echo "ELEVENLABS_API_KEY is required." >&2
  exit 1
fi
if [ -z "${ELEVENLABS_PLANT_DOCTOR_AGENT_ID:-}" ]; then
  echo "ELEVENLABS_PLANT_DOCTOR_AGENT_ID is required." >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "$REGION")"
SUFFIX="${ACCOUNT_ID}-$(date +%Y%m%d)"
SITE_BUCKET="${SITE_BUCKET:-${STACK_PREFIX}-site-${SUFFIX}}"
STATIC_S3_PREFIX="${STATIC_S3_PREFIX:-}"
SKIP_BUCKET_SETUP="${SKIP_BUCKET_SETUP:-false}"
FUNCTION_NAME="${FUNCTION_NAME:-${STACK_PREFIX}-api}"
ROLE_NAME="${ROLE_NAME:-${STACK_PREFIX}-lambda-role}"
APP_TOKEN="${APP_TOKEN:-}"
TRIAL_CODE="${PLANT_DOCTOR_TRIAL_CODE:-$(openssl rand -hex 4)}"

TMP_DIR="$(mktemp -d)"
BUILD_DIR="$TMP_DIR/lambda"
mkdir -p "$BUILD_DIR"

echo "Deploying Plant Doctor"
echo "Region: $REGION"
echo "Site bucket: $SITE_BUCKET"
if [ -n "$STATIC_S3_PREFIX" ]; then
  echo "Static prefix: $STATIC_S3_PREFIX"
fi
echo "Lambda: $FUNCTION_NAME"
echo "Owner tag: $OWNER_TAG_VALUE"

if [ "$CREATE_BUDGET" = "true" ]; then
  cat > "$TMP_DIR/budget.json" <<JSON
{
  "BudgetName": "${STACK_PREFIX}-monthly-${BUDGET_LIMIT_USD}usd",
  "BudgetLimit": {"Amount": "$BUDGET_LIMIT_USD", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
JSON
  cat > "$TMP_DIR/budget-notifications.json" <<JSON
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "$OWNER_TAG_VALUE"}]
  }
]
JSON
  aws budgets create-budget \
    --account-id "$ACCOUNT_ID" \
    --budget "file://$TMP_DIR/budget.json" \
    --notifications-with-subscribers "file://$TMP_DIR/budget-notifications.json" >/dev/null 2>&1 || \
    echo "Warning: budget creation skipped; it may already exist or IAM may not allow budgets:CreateBudget."
fi

create_bucket() {
  local bucket="$1"
  if aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    return
  fi
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$bucket" >/dev/null
  else
    aws s3api create-bucket \
      --bucket "$bucket" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
}

if [ "$SKIP_BUCKET_SETUP" != "true" ]; then
  create_bucket "$SITE_BUCKET"
  aws s3api put-bucket-tagging \
    --bucket "$SITE_BUCKET" \
    --tagging "TagSet=[{Key=Owner,Value=$OWNER_TAG_VALUE}]" >/dev/null
  aws s3api put-public-access-block \
    --bucket "$SITE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false >/dev/null
  cat > "$TMP_DIR/site-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadForTrialStaticApp",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$SITE_BUCKET/*"
    }
  ]
}
JSON
  aws s3api put-bucket-policy --bucket "$SITE_BUCKET" --policy "file://$TMP_DIR/site-policy.json" >/dev/null
fi

cat > "$TMP_DIR/trust.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TMP_DIR/trust.json" \
    --tags Key=Owner,Value="$OWNER_TAG_VALUE" >/dev/null
fi
aws iam tag-role --role-name "$ROLE_NAME" --tags Key=Owner,Value="$OWNER_TAG_VALUE" >/dev/null

cat > "$TMP_DIR/lambda-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:$REGION:$ACCOUNT_ID:*"
    }
  ]
}
JSON
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "${STACK_PREFIX}-lambda-policy" \
  --policy-document "file://$TMP_DIR/lambda-policy.json" >/dev/null
ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)"

cat > "$TMP_DIR/requirements.txt" <<'REQ'
fastapi>=0.115
python-multipart>=0.0.9
mangum>=0.19
langgraph>=1.2.2
langgraph-checkpoint-sqlite>=3.1.0
langchain-core>=1.4.0
pydantic>=2.13.4
PyYAML>=6.0.3
REQ

python3 -m pip install \
  --target "$BUILD_DIR" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 312 \
  --only-binary=:all: \
  --upgrade \
  -r "$TMP_DIR/requirements.txt" >/dev/null

cp -R "$ROOT_DIR/app" "$ROOT_DIR/core" "$ROOT_DIR/sopilot" "$ROOT_DIR/examples" "$BUILD_DIR/"
cp "$AWS_DIR/plant_doctor_lambda.py" "$BUILD_DIR/handler.py"
find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$BUILD_DIR" -name '*.pyc' -delete
(cd "$BUILD_DIR" && zip -q -r "$TMP_DIR/lambda.zip" .)

cat > "$TMP_DIR/lambda-env.json" <<JSON
{
  "Variables": {
    "OPENAI_API_KEY": "$OPENAI_API_KEY",
    "ELEVENLABS_API_KEY": "$ELEVENLABS_API_KEY",
    "ELEVENLABS_PLANT_DOCTOR_AGENT_ID": "$ELEVENLABS_PLANT_DOCTOR_AGENT_ID",
    "PLANT_DOCTOR_AUTO_APPROVE": "true",
    "PLANT_DOCTOR_SKIP_LOCAL_REPORT_WRITE": "true",
    "PLANT_DOCTOR_CORS_ORIGINS": "",
    "PLANT_DOCTOR_APP_TOKEN": "$APP_TOKEN",
    "PLANT_DOCTOR_TRIAL_CODE": "$TRIAL_CODE"
  }
}
JSON

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$TMP_DIR/lambda.zip" \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler handler.lambda_handler \
    --timeout 120 \
    --memory-size 1024 \
    --environment "file://$TMP_DIR/lambda-env.json" \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
else
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler handler.lambda_handler \
    --timeout 120 \
    --memory-size 1024 \
    --architectures x86_64 \
    --role "$ROLE_ARN" \
    --zip-file "fileb://$TMP_DIR/lambda.zip" \
    --environment "file://$TMP_DIR/lambda-env.json" \
    --tags Owner="$OWNER_TAG_VALUE" \
    --region "$REGION" >/dev/null
  aws lambda wait function-active --function-name "$FUNCTION_NAME" --region "$REGION"
fi

FUNCTION_ARN="$(aws lambda get-function \
  --function-name "$FUNCTION_NAME" \
  --query Configuration.FunctionArn \
  --output text \
  --region "$REGION")"
aws lambda tag-resource \
  --resource "$FUNCTION_ARN" \
  --tags Owner="$OWNER_TAG_VALUE" \
  --region "$REGION" >/dev/null
aws logs create-log-group \
  --log-group-name "/aws/lambda/$FUNCTION_NAME" \
  --tags Owner="$OWNER_TAG_VALUE" \
  --region "$REGION" >/dev/null 2>&1 || true
aws logs put-retention-policy \
  --log-group-name "/aws/lambda/$FUNCTION_NAME" \
  --retention-in-days 7 \
  --region "$REGION" >/dev/null 2>&1 || true

if ! aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda create-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors AllowOrigins='*',AllowMethods='GET,POST',AllowHeaders='content-type,x-app-token,x-trial-code,x-session-id,authorization',MaxAge=300 \
    --region "$REGION" >/dev/null
else
  aws lambda update-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors AllowOrigins='*',AllowMethods='GET,POST',AllowHeaders='content-type,x-app-token,x-trial-code,x-session-id,authorization',MaxAge=300 \
    --region "$REGION" >/dev/null
fi
aws lambda add-permission \
  --function-name "$FUNCTION_NAME" \
  --statement-id FunctionURLAllowPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region "$REGION" >/dev/null 2>&1 || true
aws lambda add-permission \
  --function-name "$FUNCTION_NAME" \
  --statement-id FunctionURLAllowPublicInvoke \
  --action lambda:InvokeFunction \
  --principal "*" \
  --invoked-via-function-url \
  --region "$REGION" >/dev/null 2>&1 || true

API_URL="$(aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --query FunctionUrl --output text --region "$REGION")"
API_URL="${API_URL%/}"

STATIC_DIR="$TMP_DIR/static"
mkdir -p "$STATIC_DIR"
sed \
  -e 's#href="/styles.css#href="styles.css#g' \
  -e 's#src="/config.js#src="config.js#g' \
  -e 's#src="/app.js#src="app.js#g' \
  "$ROOT_DIR/app/web/index.html" > "$STATIC_DIR/index.html"
cp "$ROOT_DIR/app/web/app.js" "$ROOT_DIR/app/web/styles.css" "$STATIC_DIR/"
cat > "$STATIC_DIR/config.js" <<JSON
window.PLANT_DOCTOR_API_URL = "$API_URL";
window.PLANT_DOCTOR_APP_TOKEN = "$APP_TOKEN";
window.PLANT_DOCTOR_AUTH_REQUIRED = true;
JSON

S3_DEST="s3://$SITE_BUCKET"
if [ -n "$STATIC_S3_PREFIX" ]; then
  S3_DEST="$S3_DEST/$STATIC_S3_PREFIX"
fi
aws s3 sync "$STATIC_DIR" "$S3_DEST" \
  --delete \
  --cache-control "public,max-age=60" >/dev/null

APP_URL="https://$SITE_BUCKET.s3.$REGION.amazonaws.com/index.html"
if [ -n "$STATIC_S3_PREFIX" ]; then
  APP_URL="https://$SITE_BUCKET.s3.$REGION.amazonaws.com/$STATIC_S3_PREFIX/index.html"
fi
cat > "$AWS_DIR/plant_doctor_last_deploy.json" <<JSON
{
  "region": "$REGION",
  "site_bucket": "$SITE_BUCKET",
  "lambda_function": "$FUNCTION_NAME",
  "api_url": "$API_URL",
  "app_url": "$APP_URL",
  "owner_tag": "$OWNER_TAG_VALUE",
  "trial_code_file": "$AWS_DIR/plant_doctor_trial_code.txt"
}
JSON
printf '%s' "$TRIAL_CODE" > "$AWS_DIR/plant_doctor_trial_code.txt"
chmod 600 "$AWS_DIR/plant_doctor_trial_code.txt"

echo ""
echo "Plant Doctor deployment complete."
echo "App URL: $APP_URL"
echo "API URL: $API_URL"
echo "Trial code saved to: $AWS_DIR/plant_doctor_trial_code.txt"
