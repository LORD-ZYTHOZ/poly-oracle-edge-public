#!/bin/bash
set -e

echo "=== poly-executor setup ==="

# System deps
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl

# Node + PM2
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
npm install -g pm2

# Clone repo
cd /opt
rm -rf poly-oracle-edge
git clone https://github.com/LORD-ZYTHOZ/poly-oracle-edge
cd poly-oracle-edge/executor

# Python env
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt

# Env file
cp .env.example .env

# Log dir
mkdir -p /var/log/poly-executor

echo ""
echo "=== Setup complete ==="
echo "Now edit your .env file:"
echo "  nano /opt/poly-oracle-edge/executor/.env"
echo ""
echo "Then start:"
echo "  cd /opt/poly-oracle-edge/executor && pm2 start pm2.config.js && pm2 save"
