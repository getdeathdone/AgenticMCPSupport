# Autonomous IT Support Agent

Production-style FastAPI + LangGraph demo for an autonomous IT support workflow. The agent routes requests to a simulated RAG knowledge base or MCP-backed SQLite tools for tickets, services, incidents, and user devices.

## Features

- LangGraph conditional routing: `RAG` or `TOOL`
- Local MCP server for SQLite-backed support tools
- SQLite support database with tickets, services, incidents, users, devices, and knowledge articles
- Markdown knowledge base documents for RAG-style troubleshooting answers
- Typo-tolerant routing for common misspellings
- Langfuse callback integration
- Web UI with chat, database preview, and source visibility
- Browser-cached read-only default database snapshot
- Admin-only optional SQLite upload endpoint, disabled by default

## Local Setup

```powershell
Set-Location D:\_AI\AgenticMCPSupport
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m support_agent.db_setup
python scripts\run_web.py
```

Open:

```text
http://localhost:8000
```

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | Runtime name, for example `local` or `production`. |
| `SUPPORT_DB_PATH` | `data/support.db` | Active SQLite database path. |
| `SUPPORT_DB_SEED_ENABLED` | `true` | Seeds deterministic demo data when the DB is initialized. |
| `DATABASE_UPLOAD_ENABLED` | `false` | Enables or disables admin upload/default database mutation endpoints. |
| `DATABASE_UPLOAD_PASSWORD` | empty | Optional admin password required for DB upload/default actions. |
| `LANGFUSE_TRACING_ENABLED` | `true` | Enables Langfuse callback configuration when keys are present. |
| `LANGFUSE_HOST` | `http://localhost:3000` | Langfuse host URL. |
| `LANGFUSE_PUBLIC_KEY` | empty | Langfuse public key. |
| `LANGFUSE_SECRET_KEY` | empty | Langfuse secret key. |

## Knowledge Base Documents

RAG answers use markdown documents from:

```text
knowledge_base/
```

Current documents:

```text
vpn_troubleshooting.md
email_troubleshooting.md
password_reset.md
device_performance.md
access_management.md
incident_escalation.md
```

To expand RAG coverage, add another `.md` file to `knowledge_base/`. Use a clear H1 title and H2 sections. The agent indexes the files at request time and returns sources like:

```text
Markdown knowledge base: knowledge_base/vpn_troubleshooting.md
```

If no markdown document matches, the agent falls back to the SQLite `knowledge_articles` table.

## Production Safety

For public hosting, keep upload disabled:

```env
ENVIRONMENT=production
DATABASE_UPLOAD_ENABLED=false
SUPPORT_DB_SEED_ENABLED=false
```

The public UI does not expose upload or database switching. On page load, the browser downloads `/api/database/snapshot` and caches the default database snapshot in `localStorage`. If the user clears browser storage, the snapshot is downloaded again from the site.

When a chat message is sent, the browser extracts only relevant rows from that local snapshot and sends them as temporary `session_context`. The server does not receive the full database file. If matching rows are present, the agent answers from `Browser session context`; otherwise it falls back to MCP tools, SQLite, and markdown docs.

The Database tab includes local-only Add/Edit/Delete/Reset controls. Edits are stored in browser `localStorage`, affect only that browser session, and never mutate the server SQLite database.

The Sources tab also supports local `.md`/`.txt` documents. Files are read in the browser, stored in `localStorage`, and only the most relevant chunks are sent as temporary `session_context`. The server never stores the uploaded local document files.

If you intentionally need database upload for private admin maintenance, enable it and keep it password protected:

```env
ENVIRONMENT=production
DATABASE_UPLOAD_ENABLED=true
DATABASE_UPLOAD_PASSWORD=replace-with-a-long-random-password
```

Admin mutation endpoints require `X-Upload-Password`:

```bash
curl -X POST \
  -H "X-Upload-Password: replace-with-a-long-random-password" \
  -F "file=@support.db" \
  http://127.0.0.1:8000/api/database/upload
```

## Free Always-On Hosting Recommendation

For a site that should stay online without free-tier sleep, use a small always-on VM. For Google Cloud Free Tier, follow:

```text
DEPLOY_GCP_FREE_TIER.md
```

The generic VPS deployment shape is below.

High-level deployment:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx
git clone <your-repo-url> /opt/support-agent
cd /opt/support-agent
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python -m support_agent.db_setup
```

Edit `.env` for production:

```env
ENVIRONMENT=production
SUPPORT_DB_PATH=/opt/support-agent/data/support.db
SUPPORT_DB_SEED_ENABLED=false
DATABASE_UPLOAD_ENABLED=false
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_SECRET_KEY=your-secret-key
```

## systemd Service

Create `/etc/systemd/system/support-agent.service`:

```ini
[Unit]
Description=Autonomous IT Support Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/support-agent
EnvironmentFile=/opt/support-agent/.env
ExecStart=/opt/support-agent/.venv/bin/python /opt/support-agent/scripts/run_web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable support-agent
sudo systemctl start support-agent
sudo systemctl status support-agent
```

## nginx Reverse Proxy

Create `/etc/nginx/sites-available/support-agent`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

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
sudo nginx -t
sudo systemctl reload nginx
```

Add HTTPS with Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## Useful Checks

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/database/active
sudo journalctl -u support-agent -f
```
