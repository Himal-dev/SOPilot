#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AWS_DIR="$ROOT_DIR/deploy/aws"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-south-1}}"
INSTANCE_NAME="${INSTANCE_NAME:-sopilot-plant-doctor}"
KEY_PAIR_NAME="${KEY_PAIR_NAME:-sopilot-plant-doctor-key}"
BLUEPRINT_ID="${BLUEPRINT_ID:-ubuntu_24_04}"
BUNDLE_ID="${BUNDLE_ID:-nano_3_1}"
OWNER_TAG_VALUE="${OWNER_TAG_VALUE:-himalmangla@gmail.com}"
APP_TOKEN="${APP_TOKEN:-$(openssl rand -hex 18)}"
TRIAL_CODE="${PLANT_DOCTOR_TRIAL_CODE:-$(openssl rand -hex 4)}"

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

TMP_DIR="$(mktemp -d)"
ARCHIVE="$TMP_DIR/sopilot.tar.gz"
ENV_FILE="$TMP_DIR/sopilot.env"
REMOTE_SCRIPT="$TMP_DIR/install_sopilot.sh"
KEY_FILE="$AWS_DIR/lightsail_${KEY_PAIR_NAME}.pem"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "Deploying Plant Doctor to Lightsail"
echo "Region: $REGION"
echo "Instance: $INSTANCE_NAME"
echo "Bundle: $BUNDLE_ID"
echo "Owner tag: $OWNER_TAG_VALUE"

if [ ! -f "$KEY_FILE" ]; then
  aws lightsail create-key-pair \
    --key-pair-name "$KEY_PAIR_NAME" \
    --query privateKeyBase64 \
    --output text \
    --region "$REGION" | base64 --decode > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
fi

if ! aws lightsail get-instance --instance-name "$INSTANCE_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lightsail create-instances \
    --instance-names "$INSTANCE_NAME" \
    --availability-zone "${REGION}a" \
    --blueprint-id "$BLUEPRINT_ID" \
    --bundle-id "$BUNDLE_ID" \
    --key-pair-name "$KEY_PAIR_NAME" \
    --tags key=Owner,value="$OWNER_TAG_VALUE" \
    --region "$REGION" >/dev/null
fi

for _ in $(seq 1 60); do
  STATE="$(aws lightsail get-instance \
    --instance-name "$INSTANCE_NAME" \
    --query 'instance.state.name' \
    --output text \
    --region "$REGION")"
  if [ "$STATE" = "running" ]; then
    break
  fi
  sleep 5
done

aws lightsail open-instance-public-ports \
  --instance-name "$INSTANCE_NAME" \
  --port-info fromPort=80,toPort=80,protocol=TCP \
  --region "$REGION" >/dev/null 2>&1 || true
aws lightsail open-instance-public-ports \
  --instance-name "$INSTANCE_NAME" \
  --port-info fromPort=443,toPort=443,protocol=TCP \
  --region "$REGION" >/dev/null 2>&1 || true

PUBLIC_IP="$(aws lightsail get-instance \
  --instance-name "$INSTANCE_NAME" \
  --query 'instance.publicIpAddress' \
  --output text \
  --region "$REGION")"
DOMAIN="${PLANT_DOCTOR_DOMAIN:-${PUBLIC_IP}.sslip.io}"
APP_URL="https://$DOMAIN/"

tar -czf "$ARCHIVE" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.pytest_cache' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='sopilot.egg-info' \
  --exclude='deploy/aws/*token*.txt' \
  --exclude='deploy/aws/*last_deploy*.json' \
  --exclude='deploy/aws/plant_doctor_trial_code.txt' \
  --exclude='deploy/aws/*.pem' \
  -C "$ROOT_DIR" .

cat > "$ENV_FILE" <<ENV
OPENAI_API_KEY=$OPENAI_API_KEY
ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY
ELEVENLABS_PLANT_DOCTOR_AGENT_ID=$ELEVENLABS_PLANT_DOCTOR_AGENT_ID
PLANT_DOCTOR_AUTO_APPROVE=true
PLANT_DOCTOR_SKIP_LOCAL_REPORT_WRITE=true
PLANT_DOCTOR_APP_TOKEN=$APP_TOKEN
PLANT_DOCTOR_TRIAL_CODE=$TRIAL_CODE
PLANT_DOCTOR_CORS_ORIGINS=*
ENV
chmod 600 "$ENV_FILE"

cat > "$REMOTE_SCRIPT" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail

DOMAIN="$1"

export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip caddy

if [ ! -f /swapfile ]; then
  sudo fallocate -l 1G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

sudo mkdir -p /opt/sopilot /var/log/sopilot
sudo tar -xzf /tmp/sopilot.tar.gz -C /opt/sopilot
sudo install -m 600 -o root -g root /tmp/sopilot.env /opt/sopilot/.env
sudo chown -R ubuntu:ubuntu /opt/sopilot /var/log/sopilot

python3 -m venv /opt/sopilot/.venv
/opt/sopilot/.venv/bin/pip install --upgrade pip
/opt/sopilot/.venv/bin/pip install -e '/opt/sopilot[app]'

sudo tee /etc/systemd/system/sopilot-plant-doctor.service >/dev/null <<'SERVICE'
[Unit]
Description=SOPilot Plant Doctor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/sopilot
EnvironmentFile=/opt/sopilot/.env
ExecStart=/opt/sopilot/.venv/bin/uvicorn app.server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=append:/var/log/sopilot/app.log
StandardError=append:/var/log/sopilot/app.log

[Install]
WantedBy=multi-user.target
SERVICE

sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
$DOMAIN {
  encode gzip zstd
  reverse_proxy 127.0.0.1:8000
}
CADDY

sudo systemctl daemon-reload
sudo systemctl enable sopilot-plant-doctor
sudo systemctl restart sopilot-plant-doctor
sudo systemctl enable caddy
sudo systemctl restart caddy
REMOTE
chmod +x "$REMOTE_SCRIPT"

echo "Waiting for SSH on $PUBLIC_IP"
for _ in $(seq 1 80); do
  if ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -i "$KEY_FILE" "ubuntu@$PUBLIC_IP" "true" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

scp -o StrictHostKeyChecking=accept-new -i "$KEY_FILE" "$ARCHIVE" "ubuntu@$PUBLIC_IP:/tmp/sopilot.tar.gz" >/dev/null
scp -o StrictHostKeyChecking=accept-new -i "$KEY_FILE" "$ENV_FILE" "ubuntu@$PUBLIC_IP:/tmp/sopilot.env" >/dev/null
scp -o StrictHostKeyChecking=accept-new -i "$KEY_FILE" "$REMOTE_SCRIPT" "ubuntu@$PUBLIC_IP:/tmp/install_sopilot.sh" >/dev/null
ssh -o StrictHostKeyChecking=accept-new -i "$KEY_FILE" "ubuntu@$PUBLIC_IP" "bash /tmp/install_sopilot.sh '$DOMAIN'"

printf '%s' "$APP_TOKEN" > "$AWS_DIR/lightsail_app_token.txt"
printf '%s' "$TRIAL_CODE" > "$AWS_DIR/plant_doctor_trial_code.txt"
chmod 600 "$AWS_DIR/lightsail_app_token.txt" "$AWS_DIR/plant_doctor_trial_code.txt"

cat > "$AWS_DIR/plant_doctor_lightsail_last_deploy.json" <<JSON
{
  "region": "$REGION",
  "instance_name": "$INSTANCE_NAME",
  "public_ip": "$PUBLIC_IP",
  "domain": "$DOMAIN",
  "app_url": "$APP_URL",
  "bundle_id": "$BUNDLE_ID",
  "owner_tag": "$OWNER_TAG_VALUE",
  "trial_code_file": "$AWS_DIR/plant_doctor_trial_code.txt",
  "ssh_key_file": "$KEY_FILE"
}
JSON

echo ""
echo "Plant Doctor Lightsail deployment complete."
echo "App URL: $APP_URL"
echo "Trial code saved to: $AWS_DIR/plant_doctor_trial_code.txt"
