# Hermes UI IaC

One-command systemd deployment for `/root/hermes_UI`.

## What this installs

- systemd service: `hermes-ui`
- service file: `/etc/systemd/system/hermes-ui.service`
- bind address: `0.0.0.0:8765`
- project directory: `/root/hermes_UI`
- app entrypoint: `/root/hermes_UI/app.py`

This makes the UI start automatically whenever the VM boots.

## Install / update

```bash
cd /root/hermes_UI/iac
sudo ./install.sh
```

The script will:

1. verify `app.py`
2. run Python syntax check
3. stop an old ad-hoc UI process on port 8765 if needed
4. install the systemd service
5. enable boot auto-start
6. restart the service
7. run a local health check
8. print host-browser URLs using detected VM IPs

## Check status

```bash
cd /root/hermes_UI/iac
./status.sh
```

Or directly:

```bash
systemctl status hermes-ui --no-pager
ss -ltnp | grep ':8765'
curl http://127.0.0.1:8765/api/health
```

Expected listener:

```text
0.0.0.0:8765
```

## Host browser access

From the host machine, open:

```text
http://<VM_IP>:8765
```

Find VM IP from inside the VM:

```bash
hostname -I
```

If the VM listens on `0.0.0.0:8765` and local health check works but the host still cannot open it, check VM networking:

- VirtualBox: use Bridged Adapter, or configure NAT Port Forwarding host `8765` -> guest `8765`.
- VMware: use Bridged, or configure NAT Port Forwarding.
- WSL2: use Windows `netsh interface portproxy` if direct access does not work.
- Linux firewall: check `ufw status`, `firewall-cmd --state`, or `iptables -S INPUT`.

## Logs

```bash
journalctl -u hermes-ui -f
```

## Restart / stop

```bash
sudo systemctl restart hermes-ui
sudo systemctl stop hermes-ui
```

## Uninstall service only

```bash
cd /root/hermes_UI/iac
sudo ./uninstall.sh
```

This removes the systemd service but does not delete `/root/hermes_UI`.
