#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_DIR="$ROOT_DIR/deploy/aws"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
STACK_PREFIX="${STACK_PREFIX:-bolobuddy-voice-assessment}"
RAW_AUDIO_RETENTION_DAYS="${RAW_AUDIO_RETENTION_DAYS:-30}"
OWNER_TAG_VALUE="${OWNER_TAG_VALUE:-himalmangla@gmail.com}"
BUDGET_LIMIT_USD="${BUDGET_LIMIT_USD:-80}"
BUDGET_EMAIL="${BUDGET_EMAIL:-$OWNER_TAG_VALUE}"
CREATE_BUDGET="${CREATE_BUDGET:-true}"
DATA_STORE="${DATA_STORE:-s3}"
USE_CLOUDFRONT="${USE_CLOUDFRONT:-false}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
SUFFIX="${ACCOUNT_ID}-$(date +%Y%m%d)"
SITE_BUCKET="${SITE_BUCKET:-${STACK_PREFIX}-site-${SUFFIX}}"
REPORT_BUCKET="${REPORT_BUCKET:-${STACK_PREFIX}-reports-${SUFFIX}}"
SESSION_TABLE="${SESSION_TABLE:-${STACK_PREFIX}-sessions}"
FUNCTION_NAME="${FUNCTION_NAME:-${STACK_PREFIX}-api}"
ROLE_NAME="${ROLE_NAME:-${STACK_PREFIX}-lambda-role}"
ADMIN_TOKEN="${ADMIN_TOKEN:-$(openssl rand -hex 18)}"
APP_TOKEN="${APP_TOKEN:-$(openssl rand -hex 18)}"
COMMENT="BoloBuddy Voice Assessment ${SITE_BUCKET}"

TMP_DIR="$(mktemp -d)"
BUILD_DIR="$TMP_DIR/lambda"
mkdir -p "$BUILD_DIR"

echo "Deploying BoloBuddy to AWS"
echo "Region: $REGION"
echo "Site bucket: $SITE_BUCKET"
echo "Report bucket: $REPORT_BUCKET"
echo "Data store: $DATA_STORE"
if [ "$DATA_STORE" = "dynamodb" ]; then
  echo "DynamoDB table: $SESSION_TABLE"
fi
echo "Lambda: $FUNCTION_NAME"
echo "Owner tag: $OWNER_TAG_VALUE"
echo "Monthly budget alert: $CREATE_BUDGET at ${BUDGET_LIMIT_USD} USD"
echo "CloudFront: $USE_CLOUDFRONT"

if [ "$CREATE_BUDGET" = "true" ]; then
  cat > "$TMP_DIR/budget.json" <<JSON
{
  "BudgetName": "${STACK_PREFIX}-monthly-${BUDGET_LIMIT_USD}usd",
  "BudgetLimit": {
    "Amount": "$BUDGET_LIMIT_USD",
    "Unit": "USD"
  },
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
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "$BUDGET_EMAIL"
      }
    ]
  },
  {
    "Notification": {
      "NotificationType": "FORECASTED",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "$BUDGET_EMAIL"
      }
    ]
  }
]
JSON
  aws budgets create-budget \
    --account-id "$ACCOUNT_ID" \
    --budget "file://$TMP_DIR/budget.json" \
    --notifications-with-subscribers "file://$TMP_DIR/budget-notifications.json" >/dev/null 2>&1 || \
    echo "Warning: budget creation skipped; it may already exist or this IAM user lacks budgets:CreateBudget."
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

create_bucket "$REPORT_BUCKET"
aws s3api put-bucket-tagging \
  --bucket "$REPORT_BUCKET" \
  --tagging "TagSet=[{Key=Owner,Value=$OWNER_TAG_VALUE}]" >/dev/null
aws s3api put-bucket-encryption \
  --bucket "$REPORT_BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
aws s3api put-public-access-block \
  --bucket "$REPORT_BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true >/dev/null
cat > "$TMP_DIR/report-lifecycle.json" <<JSON
{
  "Rules": [
    {
      "ID": "expire-raw-audio",
      "Status": "Enabled",
      "Filter": {"Prefix": "sessions/"},
      "Expiration": {"Days": $RAW_AUDIO_RETENTION_DAYS}
    }
  ]
}
JSON
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$REPORT_BUCKET" \
  --lifecycle-configuration "file://$TMP_DIR/report-lifecycle.json" >/dev/null

create_bucket "$SITE_BUCKET"
aws s3api put-bucket-tagging \
  --bucket "$SITE_BUCKET" \
  --tagging "TagSet=[{Key=Owner,Value=$OWNER_TAG_VALUE}]" >/dev/null
aws s3api put-public-access-block \
  --bucket "$SITE_BUCKET" \
  --public-access-block-configuration BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false >/dev/null
aws s3api put-bucket-website \
  --bucket "$SITE_BUCKET" \
  --website-configuration '{"IndexDocument":{"Suffix":"index.html"},"ErrorDocument":{"Key":"index.html"}}' >/dev/null
cat > "$TMP_DIR/site-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadForWebsite",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$SITE_BUCKET/*"
    }
  ]
}
JSON
aws s3api put-bucket-policy --bucket "$SITE_BUCKET" --policy "file://$TMP_DIR/site-policy.json" >/dev/null

SESSION_TABLE_ARN=""
if [ "$DATA_STORE" = "dynamodb" ]; then
  if ! aws dynamodb describe-table --table-name "$SESSION_TABLE" --region "$REGION" >/dev/null 2>&1; then
    aws dynamodb create-table \
      --table-name "$SESSION_TABLE" \
      --attribute-definitions AttributeName=session_id,AttributeType=S \
      --key-schema AttributeName=session_id,KeyType=HASH \
      --billing-mode PAY_PER_REQUEST \
      --tags Key=Owner,Value="$OWNER_TAG_VALUE" \
      --region "$REGION" >/dev/null
    aws dynamodb wait table-exists --table-name "$SESSION_TABLE" --region "$REGION"
  fi
  SESSION_TABLE_ARN="$(aws dynamodb describe-table \
    --table-name "$SESSION_TABLE" \
    --query Table.TableArn \
    --output text \
    --region "$REGION")"
  aws dynamodb tag-resource \
    --resource-arn "$SESSION_TABLE_ARN" \
    --tags Key=Owner,Value="$OWNER_TAG_VALUE" \
    --region "$REGION" >/dev/null
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
aws iam tag-role \
  --role-name "$ROLE_NAME" \
  --tags Key=Owner,Value="$OWNER_TAG_VALUE" >/dev/null

cat > "$TMP_DIR/lambda-policy.json" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:$REGION:$ACCOUNT_ID:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::$REPORT_BUCKET",
        "arn:aws:s3:::$REPORT_BUCKET/*"
      ]
    }
$(if [ "$DATA_STORE" = "dynamodb" ]; then cat <<JSON_FRAGMENT
    ,
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Scan"
      ],
      "Resource": "arn:aws:dynamodb:$REGION:$ACCOUNT_ID:table/$SESSION_TABLE"
    }
JSON_FRAGMENT
fi)
  ]
}
JSON
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "${STACK_PREFIX}-lambda-policy" \
  --policy-document "file://$TMP_DIR/lambda-policy.json" >/dev/null
ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)"

cp "$AWS_DIR/lambda/handler.py" "$BUILD_DIR/handler.py"
(cd "$BUILD_DIR" && zip -q -r "$TMP_DIR/lambda.zip" .)

cat > "$TMP_DIR/lambda-env.json" <<JSON
{
  "Variables": {
    "REPORT_BUCKET": "$REPORT_BUCKET",
    "DATA_STORE": "$DATA_STORE",
    "SESSION_TABLE": "$SESSION_TABLE",
    "ADMIN_TOKEN": "$ADMIN_TOKEN",
    "APP_TOKEN": "$APP_TOKEN",
    "ELEVENLABS_API_KEY": "${ELEVENLABS_API_KEY:-}",
    "ELEVENLABS_STT_MODEL_ID": "${ELEVENLABS_STT_MODEL_ID:-scribe_v2}",
    "ELEVENLABS_USE_AUDIO_ISOLATION": "${ELEVENLABS_USE_AUDIO_ISOLATION:-false}",
    "RAW_AUDIO_RETENTION_DAYS": "$RAW_AUDIO_RETENTION_DAYS"
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
    --timeout 90 \
    --memory-size 512 \
    --environment "file://$TMP_DIR/lambda-env.json" \
    --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
else
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler handler.lambda_handler \
    --timeout 90 \
    --memory-size 512 \
    --architectures arm64 \
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

aws logs put-retention-policy \
  --log-group-name "/aws/lambda/$FUNCTION_NAME" \
  --retention-in-days 30 \
  --region "$REGION" >/dev/null 2>&1 || true

if ! aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda create-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors AllowOrigins='*',AllowMethods='GET,POST',AllowHeaders='content-type,x-app-token,x-admin-token,authorization',MaxAge=300 \
    --region "$REGION" >/dev/null
else
  aws lambda update-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors AllowOrigins='*',AllowMethods='GET,POST',AllowHeaders='content-type,x-app-token,x-admin-token,authorization',MaxAge=300 \
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

sed \
  -e "s#__API_URL__#$API_URL#g" \
  -e "s#__APP_TOKEN__#$APP_TOKEN#g" \
  "$AWS_DIR/static/index.html" > "$TMP_DIR/index.html"
aws s3 cp "$TMP_DIR/index.html" "s3://$SITE_BUCKET/index.html" \
  --content-type text/html \
  --cache-control "public,max-age=60" >/dev/null

WEBSITE_ENDPOINT="$SITE_BUCKET.s3-website.$REGION.amazonaws.com"
S3_OBJECT_URL="https://$SITE_BUCKET.s3.$REGION.amazonaws.com/index.html"
DISTRIBUTION_ID=""
CLOUDFRONT_DOMAIN=""

if [ "$USE_CLOUDFRONT" = "true" ]; then
  DISTRIBUTION_ID="$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='$COMMENT'].Id | [0]" \
    --output text 2>/dev/null || true)"

  if [ -z "$DISTRIBUTION_ID" ] || [ "$DISTRIBUTION_ID" = "None" ]; then
    CALLER_REFERENCE="${SITE_BUCKET}-$(date +%s)"
    cat > "$TMP_DIR/cloudfront.json" <<JSON
{
  "CallerReference": "$CALLER_REFERENCE",
  "Comment": "$COMMENT",
  "Enabled": true,
  "DefaultRootObject": "index.html",
  "PriceClass": "PriceClass_100",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "site-origin",
        "DomainName": "$WEBSITE_ENDPOINT",
        "CustomOriginConfig": {
          "HTTPPort": 80,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "http-only",
          "OriginSslProtocols": {
            "Quantity": 1,
            "Items": ["TLSv1.2"]
          }
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "site-origin",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"],
      "CachedMethods": {
        "Quantity": 2,
        "Items": ["GET", "HEAD"]
      }
    },
    "ForwardedValues": {
      "QueryString": false,
      "Cookies": {"Forward": "none"}
    },
    "MinTTL": 0,
    "DefaultTTL": 60,
    "MaxTTL": 300,
    "Compress": true
  }
}
JSON
    cat > "$TMP_DIR/cloudfront-with-tags.json" <<JSON
{
  "DistributionConfig": $(cat "$TMP_DIR/cloudfront.json"),
  "Tags": {
    "Items": [
      {
        "Key": "Owner",
        "Value": "$OWNER_TAG_VALUE"
      }
    ]
  }
}
JSON
    DISTRIBUTION_ID="$(aws cloudfront create-distribution-with-tags \
      --distribution-config-with-tags "file://$TMP_DIR/cloudfront-with-tags.json" \
      --query Distribution.Id \
      --output text)"
  else
    aws cloudfront create-invalidation \
      --distribution-id "$DISTRIBUTION_ID" \
      --paths "/*" >/dev/null
  fi

  CLOUDFRONT_DOMAIN="$(aws cloudfront get-distribution --id "$DISTRIBUTION_ID" --query Distribution.DomainName --output text)"
  CLOUDFRONT_ARN="$(aws cloudfront get-distribution --id "$DISTRIBUTION_ID" --query Distribution.ARN --output text)"
  aws cloudfront tag-resource \
    --resource "$CLOUDFRONT_ARN" \
    --tags "Items=[{Key=Owner,Value=$OWNER_TAG_VALUE}]" >/dev/null
fi

APP_URL="$S3_OBJECT_URL"
if [ -n "$CLOUDFRONT_DOMAIN" ]; then
  APP_URL="https://$CLOUDFRONT_DOMAIN"
fi

cat > "$AWS_DIR/last_deploy.json" <<JSON
{
  "region": "$REGION",
  "data_store": "$DATA_STORE",
  "site_bucket": "$SITE_BUCKET",
  "report_bucket": "$REPORT_BUCKET",
  "session_table": "$SESSION_TABLE",
  "lambda_function": "$FUNCTION_NAME",
  "api_url": "$API_URL",
  "cloudfront_distribution_id": "$DISTRIBUTION_ID",
  "app_url": "$APP_URL",
  "cloudfront_url": "$([ -n "$CLOUDFRONT_DOMAIN" ] && printf 'https://%s' "$CLOUDFRONT_DOMAIN")",
  "s3_object_url": "$S3_OBJECT_URL",
  "s3_website_url": "http://$WEBSITE_ENDPOINT",
  "admin_token_file": "$AWS_DIR/admin_token.txt",
  "app_token_file": "$AWS_DIR/app_token.txt"
}
JSON
printf '%s\n' "$ADMIN_TOKEN" > "$AWS_DIR/admin_token.txt"
chmod 600 "$AWS_DIR/admin_token.txt"
printf '%s\n' "$APP_TOKEN" > "$AWS_DIR/app_token.txt"
chmod 600 "$AWS_DIR/app_token.txt"

echo ""
echo "Deployment complete."
echo "App URL: $APP_URL"
echo "S3 HTTPS URL: $S3_OBJECT_URL"
echo "S3 website URL: http://$WEBSITE_ENDPOINT"
echo "API URL: $API_URL"
echo "Admin token saved to: $AWS_DIR/admin_token.txt"
echo "App token saved to: $AWS_DIR/app_token.txt"
if [ -z "${ELEVENLABS_API_KEY:-}" ]; then
  echo "Warning: ELEVENLABS_API_KEY was not set during deploy; assessment API will request provider configuration."
fi
