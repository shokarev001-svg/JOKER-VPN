#!/usr/bin/env bash
# Run the pinned revision on the VPS. This is an integration stage, not hard session expiry.
set -euo pipefail
umask 077
test "$(id -u)" = 0
revision=${1:?A full source commit SHA is required}
server_host=${2:?The public server IPv4 is required}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
test -s /opt/joker-activation/server.py
test -s /opt/joker-activation/vpn_sync.py
test -x /opt/joker-certbot/bin/python
systemctl is-active --quiet joker-activation.service
stage=$(mktemp -d /root/joker-profile-stage.XXXXXX)
backup=$(mktemp -d /root/joker-profile-backup.XXXXXX)
base="https://raw.githubusercontent.com/shokarev001-svg/JOKER-VPN/$revision/activation"
for file in server.py vpn_sync.py configure_endpoint.py test_server.py test_vpn_sync.py test_profile.py joker-vpn-sync.service joker-vpn-sync.timer; do
    curl --fail --silent --show-error --location --retry 2 --connect-timeout 15 --max-time 90 "$base/$file" -o "$stage/$file"
    test -s "$stage/$file"
done
python3 -m unittest discover -s "$stage" -p 'test_*.py'
systemd-analyze verify "$stage/joker-vpn-sync.service" "$stage/joker-vpn-sync.timer"
cp -p /opt/joker-activation/server.py "$backup/server.py"
cp -p /opt/joker-activation/vpn_sync.py "$backup/vpn_sync.py"
for file in joker-vpn-sync.service joker-vpn-sync.timer; do
    if test -f "/etc/systemd/system/$file"; then cp -p "/etc/systemd/system/$file" "$backup/$file"; fi
done
timer_enabled=0
timer_active=0
systemctl is-enabled --quiet joker-vpn-sync.timer 2>/dev/null && timer_enabled=1
systemctl is-active --quiet joker-vpn-sync.timer 2>/dev/null && timer_active=1
endpoint=/etc/joker-activation/vpn-endpoint.json
if test -f "$endpoint"; then cp -p "$endpoint" "$backup/vpn-endpoint.json"; fi
python3 - "$backup/ledger.sqlite3" <<'PY'
import sqlite3, sys
source = sqlite3.connect('file:/var/lib/joker-activation/ledger.sqlite3?mode=ro', uri=True, timeout=10)
destination = sqlite3.connect(sys.argv[1])
try:
    source.backup(destination)
    assert destination.execute('PRAGMA integrity_check').fetchone() == ('ok',)
finally:
    destination.close()
    source.close()
PY
rollback() {
    trap - ERR
    set +e
    systemctl stop joker-vpn-sync.timer joker-vpn-sync.service
    systemctl disable joker-vpn-sync.timer 2>/dev/null
    install -m 644 "$backup/server.py" /opt/joker-activation/server.py
    install -m 644 "$backup/vpn_sync.py" /opt/joker-activation/vpn_sync.py
    if test -f "$backup/vpn-endpoint.json"; then install -m 644 "$backup/vpn-endpoint.json" "$endpoint"; else rm -f "$endpoint"; fi
    for file in joker-vpn-sync.service joker-vpn-sync.timer; do
        if test -f "$backup/$file"; then install -m 644 "$backup/$file" "/etc/systemd/system/$file"; else rm -f "/etc/systemd/system/$file"; fi
    done
    systemctl daemon-reload
    systemctl restart joker-activation.service
    if test "$timer_enabled" = 1; then systemctl enable joker-vpn-sync.timer; fi
    if test "$timer_active" = 1; then systemctl start joker-vpn-sync.timer; fi
    if cmp -s "$backup/server.py" /opt/joker-activation/server.py && cmp -s "$backup/vpn_sync.py" /opt/joker-activation/vpn_sync.py && systemctl is-active --quiet joker-activation.service; then
        echo "UPDATE_FAILED; prior application files restored; backup: $backup" >&2
    else
        echo "UPDATE_FAILED; restoration needs attention; backup: $backup" >&2
    fi
    exit 1
}
trap rollback ERR
# Stop the old scheduler before replacing its script; the running VPN core is not restarted.
systemctl stop joker-vpn-sync.timer joker-vpn-sync.service 2>/dev/null || true
/opt/joker-certbot/bin/python "$stage/configure_endpoint.py" --host "$server_host"
chown root:root /etc/joker-activation "$endpoint"
chmod 755 /etc/joker-activation
install -o root -g root -m 644 "$stage/server.py" /opt/joker-activation/server.py
install -o root -g root -m 644 "$stage/vpn_sync.py" /opt/joker-activation/vpn_sync.py
systemctl restart joker-activation.service
python3 - <<'PY'
import json, time, urllib.request
for attempt in range(20):
    try:
        request = urllib.request.Request('http://127.0.0.1:8088/v1/status',
            data=b'{"include_profile":true}',
            headers={'Authorization': 'Bearer ' + '0'*64, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.load(response)
            assert 'vpn' in data and response.headers['Cache-Control'] == 'no-store'
        break
    except Exception:
        if attempt == 19:
            raise SystemExit('PROFILE_API_CHECK_FAILED')
        time.sleep(0.5)
PY
install -o root -g root -m 644 "$stage/joker-vpn-sync.service" /etc/systemd/system/joker-vpn-sync.service
install -o root -g root -m 644 "$stage/joker-vpn-sync.timer" /etc/systemd/system/joker-vpn-sync.timer
systemctl daemon-reload
systemctl start joker-vpn-sync.service
systemctl enable --now joker-vpn-sync.timer
systemctl is-active --quiet joker-activation.service
systemctl is-active --quiet joker-vpn-sync.timer
python3 /opt/joker-activation/vpn_sync.py
trap - ERR
echo 'PROFILE_UPDATE_OK'
echo "BACKUP: $backup"
