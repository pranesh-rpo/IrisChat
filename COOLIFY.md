# ☁️ Deploying Iris on Coolify

Coolify is an amazing self-hosted platform. Here is how to deploy IrisChat properly.

## 1. Create Resource
- Go to your Project.
- Click **+ New**.
- Select **Git Repository** (Private or Public).
- Enter this repository URL.

## 2. Configuration (Important!)

Before clicking "Deploy", go to **Configuration**.

### 🏗️ Build Pack
- Coolify usually auto-detects **Nixpacks**. This is fine.
- **Python Version**: 3.11 (Default)
- **Install Command**: `pip install -r requirements.txt`
- **Start Command**: `python main.py`

### 🔑 Environment Variables
You MUST set these variables in the **Environment Variables** tab:

| Key | Value | Description |
|-----|-------|-------------|
| `TELEGRAM_BOT_TOKEN` | `123456:ABC-DEF...` | Your Telegram Bot Token. |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | **CRITICAL**: Connects to host's Ollama. |
| `OLLAMA_MODEL` | `gemma2:2b` | The model you pulled on the host. |
| `PYTHONUNBUFFERED` | `1` | Ensures logs show up in Coolify. |

> **Note on Ollama Connection:**
> - If `http://host.docker.internal:11434` fails, try `http://172.17.0.1:11434`.
> - Ensure Ollama is running on the host: `ollama serve`.
> - Ensure Ollama listens on all interfaces (optional but helpful): `OLLAMA_HOST=0.0.0.0 ollama serve`.

### 💾 Persistent Storage (Volumes)
To keep your **Economy Data** (User Balances) safe when you redeploy:

1. Go to **Storage**.
2. Add a new Volume:
   - **Source Path**: (Leave empty or specify a host path)
   - **Destination Path**: `/app/chat_history.db`
3. This ensures the database file isn't deleted during updates.

## 3. Deploy
- Click **Deploy**.
- Watch the **Build Logs**.
- Once "Healthy", check the **Application Logs** to see if Iris connected to Ollama.
