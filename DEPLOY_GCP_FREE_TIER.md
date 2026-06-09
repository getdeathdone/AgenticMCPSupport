# Deploy on Google Cloud Free Tier

This guide deploys the Autonomous IT Support Agent on a Google Compute Engine VM. It uses a lightweight Python venv, `systemd`, and `nginx`. This is better for the free `e2-micro` shape than running a heavier Docker stack.

## 1. Create the VM

In Google Cloud Console:

- Compute Engine -> VM instances -> Create instance
- Machine type: `e2-micro`
- OS: Ubuntu LTS
- Region: pick a Free Tier eligible US region
- Boot disk: 30 GB standard persistent disk
- Allow HTTP traffic
- Allow HTTPS traffic

If you use `gcloud`, the shape is roughly:

```bash
gcloud compute instances create support-agent \
  --zone=us-west1-b \
  --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --tags=http-server,https-server
```

Open firewall if needed:

```bash
gcloud compute firewall-rules create allow-http \
  --allow=tcp:80 \
  --target-tags=http-server

gcloud compute firewall-rules create allow-https \
  --allow=tcp:443 \
  --target-tags=https-server
```

## 2. SSH Into The VM

```bash
gcloud compute ssh support-agent --zone=us-west1-b
```

## 3. Install System Packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx
```

## 4. Clone The Project

```bash
sudo mkdir -p /opt/support-agent
sudo chown "$USER:$USER" /opt/support-agent
git clone <your-github-repo-url> /opt/support-agent
cd /opt/support-agent
```

## 5. Install Python Dependencies

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Configure Production Environment

```bash
cp .env.example .env
nano .env
```

Use:

```env
ENVIRONMENT=production
APP_HOST=127.0.0.1
APP_PORT=8000
SUPPORT_DB_PATH=/opt/support-agent/data/support.db
SUPPORT_DB_SEED_ENABLED=true
DATABASE_UPLOAD_ENABLED=false
DATABASE_UPLOAD_PASSWORD=
LANGFUSE_TRACING_ENABLED=false
LANGFUSE_HOST=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

Create the default SQLite database:

```bash
PYTHONPATH=/opt/support-agent/src .venv/bin/python -m support_agent.db_setup
```

## 7. Test The App

```bash
.venv/bin/python scripts/run_web.py
```

In another SSH session:

```bash
curl http://127.0.0.1:8000/health
```

Stop the foreground server with `Ctrl+C`.

## 8. Create A systemd Service

```bash
sudo nano /etc/systemd/system/support-agent.service
```

Paste:

```ini
[Unit]
Description=Autonomous IT Support Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/support-agent
EnvironmentFile=/opt/support-agent/.env
Environment=PYTHONPATH=/opt/support-agent/src
ExecStart=/opt/support-agent/.venv/bin/python /opt/support-agent/scripts/run_web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable support-agent
sudo systemctl start support-agent
sudo systemctl status support-agent
```

Logs:

```bash
sudo journalctl -u support-agent -f
```

## 9. Configure nginx

```bash
sudo nano /etc/nginx/sites-available/support-agent
```

Use your domain if you have one. If not, temporarily use `_`.

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/support-agent /etc/nginx/sites-enabled/support-agent
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Open:

```text
http://YOUR_VM_EXTERNAL_IP
```

## 10. Optional HTTPS With A Domain

Point your domain DNS `A` record to the VM external IP, then:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## 11. Update Deployment

```bash
cd /opt/support-agent
git pull
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=/opt/support-agent/src python -m support_agent.db_setup
sudo systemctl restart support-agent
```

## Notes

- Public users cannot mutate the server database.
- Browser-local database edits are stored in the user's `localStorage`.
- Browser-local docs are read in the browser and only relevant chunks are sent as temporary `session_context`.
- `DATABASE_UPLOAD_ENABLED=false` should stay disabled for public demos.
