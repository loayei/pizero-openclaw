#!/bin/bash

rsync -avz --delete --exclude='__pycache__' --exclude='.lgd-*' ./ pi@pizero.local:/home/pi/pizero-openclaw/ &&
ssh pi@pizero.local "
  sudo cp /home/pi/pizero-openclaw/pizero-openclaw.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable pizero-openclaw &&
  sudo systemctl restart pizero-openclaw &&
  sleep 2 &&
  sudo journalctl -u pizero-openclaw -n 30 --no-pager
"