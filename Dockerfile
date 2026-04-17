FROM python:3.11-slim

# System deps: Node.js (Agent SDK), git (npx skills add), Playwright browser deps
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl git ca-certificates \
      libatspi2.0-0 libnss3 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2t64 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libpango-1.0-0 libcairo2 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (required by Agent SDK subprocess transport)
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Download Chromium binary for Playwright (system libs already installed above)
RUN python -m playwright install chromium

COPY app/ app/
COPY prompts/ /project/prompts/
COPY scripts/ /project/scripts/

# CC needs /project as cwd with writable memory/ and skill install dir
RUN mkdir -p /project/memory /project/.agents

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
