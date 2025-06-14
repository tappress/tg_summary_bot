FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY *.py .

# Install uv
RUN pip install uv

# Install dependencies
RUN uv sync

# Run the bot
CMD ["uv", "run", "python", "bot.py"]