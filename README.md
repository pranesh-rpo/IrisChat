# IrisChat ✨

IrisChat is a charming, AI-driven Telegram chatbot designed for group chats. She is fun, cute, and acts like a friendly group member!

## Features
- 💖 **Charming Personality**: Iris is designed to be cute, enthusiastic, and friendly (like "Cutie" bots).
- 🧠 **AI-Powered**: Supports **Google Gemini Pro** or **Groq** (Llama 3, Mixtral) for intelligent responses.
- 💬 **Group Chat Ready**: Responds to mentions, replies, and `!iris` commands.
- 💸 **Donations**: Built-in UPI QR code generator (`!donate`) to accept support.

## How to Use
- **Start/Reset**: Type `!iris` in the chat to wake her up or reset the conversation.
- **Donate**: Type `!donate` to see a UPI QR code.
- **Chat**: Just mention her, reply to her, or say "Iris" in your sentence!

## Setup

1.  **Clone/Download** this repository.
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment**:
    - Copy `.env.example` to `.env`:
        ```bash
        cp .env.example .env
        ```
    - Open `.env` and fill in your API keys (You only need ONE):
        - `TELEGRAM_BOT_TOKEN`: Get this from [@BotFather](https://t.me/BotFather).
        - `GROQ_API_KEY`: Get this from [Groq Cloud](https://console.groq.com/keys) (Recommended for speed!).
        - `GEMINI_API_KEY`: Get this from [Google AI Studio](https://makersuite.google.com/app/apikey).
    - *Note: If both keys are present, Iris will prefer Groq.*

## Running Iris (Locally)

1.  **Create and Activate Virtual Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run**:
    ```bash
    python main.py
    ```

## ☁️ Free Hosting / Deployment

You can host Iris for **FREE** on platforms like Render or Fly.io.

### Option 1: Render.com (Easiest)
1.  Fork this repo to your GitHub.
2.  Sign up at [Render.com](https://render.com).
3.  Click **New +** -> **Blueprints**.
4.  Connect your repository.
5.  Render will automatically detect `render.yaml` and deploy it!
    - *Don't forget to add your Environment Variables (TELEGRAM_BOT_TOKEN, GEMINI_API_KEY) in the Render dashboard if they aren't asked for!*

### Option 2: Docker
You can build and run Iris anywhere with Docker:
```bash
docker build -t irischat .
docker run -e TELEGRAM_BOT_TOKEN=your_token -e GEMINI_API_KEY=your_key irischat
```

## Customization

You can tweak Iris's personality in `main.py` by modifying the `SYSTEM_PROMPT` variable.
