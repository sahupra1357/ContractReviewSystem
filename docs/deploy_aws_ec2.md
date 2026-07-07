# AWS EC2 Demo Deployment — SYNTHETIC DATA ONLY

One VM running the exact local compose stack. This is demo hosting **and**
the first foothold of the production path (design §7 targets AWS) — but it
is NOT the in-VPC production architecture; say so on the slide.

## Cost

`t4g.xlarge` (4 vCPU / 16GB, ARM — matches our images) ≈ **$0.13/hour**
(~$3/day running 24/7). New-account credits typically cover the demo period
entirely; **stop the instance between rehearsals** (stopped = only EBS
pennies). Nothing else billed beyond a 30GB gp3 volume.

## Steps (~20 minutes, most of it unattended)

1. Create the AWS account → console → EC2 → **Launch instance**:
   - AMI: Ubuntu Server 24.04 LTS **(64-bit ARM)**
   - Type: `t4g.xlarge` · Storage: 30GB gp3
   - Security group: **no inbound rules needed** (the app is published via a
     Cloudflare tunnel; add SSH from your IP only if you want shell access)
2. Create a GitHub **fine-grained PAT** (read-only, this repo only) —
   Settings → Developer settings → Fine-grained tokens.
3. In the launch wizard, expand **Advanced → User data** and paste
   `scripts/ec2-user-data.sh` with the three `CHANGE_ME` values filled in
   (GitHub PAT, a demo-scoped `ANTHROPIC_API_KEY`, a demo password).
4. Launch. First boot ~15 min (torch build layer + BGE download on first
   analysis). Progress: `tail -f /var/log/cloud-init-output.log` over SSH,
   or just wait.
5. Get the public URL: `grep -o 'https://[a-z-]*\.trycloudflare\.com' /var/log/cloudflared.log`
   — sign in as `reviewer1` / your demo password. The seeded synthetic
   corpus processes automatically; novel-PII docs will sit in `pii_hold`
   for the admin demo moment.

## Notes

- The quick-tunnel URL changes on every tunnel restart. For a stable URL,
  create a (free) Cloudflare account + named tunnel, or attach an Elastic IP
  and put caddy in front instead.
- Credentials on the VM: `.env` (mode 600) + compose override — the
  laptop-only `ant`-profile mount is disabled there.
- Teardown: terminate the instance, delete the volume, revoke the demo API
  key and the GitHub PAT.
- **Never upload real contracts to this instance.** Real-data processing
  waits for the in-VPC pilot build.
