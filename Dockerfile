FROM python:3.13-slim

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app \
    PATH=/home/app/.local/bin:/home/app/.opencode/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

# git is required: the opencode agent commits/pushes the repo at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        tini \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /bin/bash app \
    && mkdir -p /home/app/.local/share/opencode/log /home/app/.config/opencode /home/app/.opencode \
    && chown -R app:app /home/app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

# Baked copy keeps the image self-contained (e.g. migrate one-shot). On the
# server compose bind-mounts the live checkout over /app so opencode has a real
# git worktree and the file-based data persists.
COPY --chown=app:app . /app

USER app

EXPOSE 8090 4096

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "uvicorn", "scripts.web_v2.app:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8090"]
