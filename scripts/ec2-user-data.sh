#!/bin/bash
# EC2 user-data — Contract Review Co-Pilot demo VM (SYNTHETIC DATA ONLY)
#
# Paste into the EC2 launch wizard's "User data" AFTER filling the three
# values below. Target: Ubuntu 24.04 ARM64 AMI on t4g.xlarge (4 vCPU/16GB).
# First boot takes ~15 min (docker build downloads the torch layer).
#
# Security group: allow NOTHING inbound except (optionally) SSH from your IP.
# The app is published through a Cloudflare tunnel started below — no open
# web ports needed.

set -euxo pipefail

# ----- fill these in ---------------------------------------------------
GITHUB_TOKEN="CHANGE_ME"        # fine-grained PAT, read-only on the repo
ANTHROPIC_API_KEY="CHANGE_ME"   # demo-scoped key; revoke after the demo
CRS_DEMO_PASSWORD="CHANGE_ME"   # login password for reviewer1/admin1
# -----------------------------------------------------------------------
REPO="sahupra1357/ContractReviewSystem"

apt-get update && apt-get install -y docker.io docker-compose-v2 git curl
systemctl enable --now docker

cd /opt
git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" crs
cd crs

# containers get credentials via env here (no ant profile on the VM);
# an override file avoids the empty-env-shadows-profile trap on laptops
cat > docker-compose.override.yml <<EOF
services:
  backend:
    environment:
      ANTHROPIC_API_KEY: \${ANTHROPIC_API_KEY}
      CRS_DEMO_PASSWORD: \${CRS_DEMO_PASSWORD}
  worker:
    environment:
      ANTHROPIC_API_KEY: \${ANTHROPIC_API_KEY}
    volumes: []          # drop the laptop-only ant-profile mount
EOF
cat > .env <<EOF
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
CRS_DEMO_PASSWORD=${CRS_DEMO_PASSWORD}
CRS_JWT_SECRET=$(openssl rand -hex 32)
EOF
chmod 600 .env

docker compose up -d --build

# wait for the API, then seed the synthetic demo corpus
for i in $(seq 1 60); do
  curl -sf http://localhost:8000/health && break
  sleep 10
done
docker compose exec -T backend env CRS_DEMO_PASSWORD="${CRS_DEMO_PASSWORD}" \
  python -m backend.seed_demo || true

# public HTTPS URL via Cloudflare quick tunnel (URL in the log below)
curl -L -o /usr/local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
chmod +x /usr/local/bin/cloudflared
nohup cloudflared tunnel --url http://localhost:8000 \
  > /var/log/cloudflared.log 2>&1 &

echo "BOOTSTRAP DONE — demo URL: grep trycloudflare /var/log/cloudflared.log"
