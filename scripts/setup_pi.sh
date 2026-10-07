#!/usr/bin/env bash
# One-time setup of the edge orchestrator on the Raspberry Pi.
# Usage (from this repository on the Pi): bash scripts/setup_pi.sh
set -euo pipefail
cd "$(dirname "$0")/.."
sudo apt update
# gpiozero/lgpio read the door switch; rpicam-apps and ffmpeg record and cut video.
sudo apt install -y python3-gpiozero python3-lgpio rpicam-apps ffmpeg python3-venv
# System site packages make the apt GPIO libraries visible inside the venv.
[ -d .venv ] || python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
.venv/bin/python -c "import gpiozero; print('gpiozero', gpiozero.__version__)"
rpicam-hello --list-cameras || true
echo "Next: verify the door switch (GPIO17): .venv/bin/python run.py --config config/pi.toml --check-door"
echo "then: .venv/bin/python run.py --config config/pi.toml --check-cameras"
