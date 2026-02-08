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

### 3. Environment Variables
Add these environment variables in Coolify:

| Variable | Value | Description |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | `your_bot_token` | From BotFather |
| `GEMINI_API_KEY` | `your_gemini_key` | Optional (Backup AI) |
| `GROQ_API_KEY` | `your_groq_key` | Optional (Backup AI) |
| `OLLAMA_BASE_URL` | `http://YOUR_VPS_PUBLIC_IP:11434` | **Use your VPS Public IP.** (e.g., `http://24.11.22.33:11434`) |
| `OLLAMA_MODEL` | `gemma3:1b` | The model you want to use. |
| `UPI_ID` | `your_upi` | For !pay command. |

**Important Note on `OLLAMA_BASE_URL`:**
- **Recommended**: Use `http://YOUR_VPS_PUBLIC_IP:11434`. This bypasses Docker network issues by routing traffic via the internet interface.
- **Alternative (Internal)**: `http://172.17.0.1:11434` (requires Docker host networking to work perfectly).

---

### 4. Important: Configure VPS Firewall (One-Time Setup)
Since you are using the Public IP, you must open port `11434` on your VPS. We have a script for this.

1.  **SSH into your VPS**:
    ```bash
    ssh user@your-vps-ip
    ```
2.  **Run the Fix Script**:
    ```bash
    # Download the script (if you haven't cloned the repo)
    curl -O https://raw.githubusercontent.com/YOUR_USERNAME/IrisChat/main/fix_ollama_linux.sh
    
    # Run it
    chmod +x fix_ollama_linux.sh
    ./fix_ollama_linux.sh
    ```
    *   This script will open Port 11434 to the internet so Coolify can reach it.

---

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
