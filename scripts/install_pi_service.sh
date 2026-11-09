#!/usr/bin/env bash
# Run the live system (door -> recording -> segments -> ML -> SQLite) as a service on the Pi.
# Usage: bash scripts/install_pi_service.sh [production|test|acquisition]
#   test: also show every clip and prediction in the review tool (port 9000).
set -euo pipefail
cd "$(dirname "$0")/.."
mode=${1:-production}
case "$mode" in
  production) flag=--production ;;
  test) flag=--test ;;
  acquisition) flag=--data-aquisition ;;
  *) echo "mode must be production, test or acquisition" >&2; exit 1 ;;
esac
repository=$(pwd)
python3 -c "import tomllib, sys; c = tomllib.load(open('config/pi.toml', 'rb'));
sys.exit(0 if c.get('door', {}).get('gpio_pin') is not None else
'Set [door] gpio_pin in config/pi.toml first (check it with --check-door).')"
sudo tee /etc/systemd/system/smart-fridge.service >/dev/null <<UNIT
[Unit]
Description=Smart fridge live system ($mode)
After=network-online.target fridge-review.service
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$repository
ExecStart=$repository/.venv/bin/python run.py --config config/pi.toml --run $flag
# SIGTERM closes an open recording cleanly before stopping.
KillSignal=SIGTERM
# Only this process gets SIGTERM; it stops rpicam-vid itself so the MP4 is finished.
KillMode=mixed
TimeoutStopSec=60
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable smart-fridge.service
sudo systemctl restart smart-fridge.service
systemctl --no-pager status smart-fridge.service | head -5
echo "Logs: journalctl -u smart-fridge -f"
