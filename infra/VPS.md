# VPS Setup

## Provider & plan
- Provider: Hetzner Cloud
- Plan: CPX42
- Region: Helsinki
- OS: Ubuntu 24.4 x86 320GB

## Users
- Primary user: `sean` (sudo, key-only SSH)
- Root: SSH login disabled, accessible via `sudo`

## SSH
- Port: 22
- Authentication: key-only (`PasswordAuthentication no`)
- Root login: disabled (`PermitRootLogin no`)

## Firewall (ufw)
- Default: deny incoming, allow outgoing
- Open ports: 22/tcp (SSH)

## fail2ban
- Active jails: sshd
- maxretry 5, findtime 10m, bantime 1h
- Config: /etc/fail2ban/jail.d/sshd.conf

## Backups
- Manual Hetzner snapshots at major checkpoints
- Pre-launch TODO: enable automated daily backups

## Pre-launch hardening checklist (deferred)
- [ ] Install unattended-upgrades
- [ ] Enable Hetzner automated backups
- [ ] Review firewall rules for production services
- [ ] Add monitoring/alerting
