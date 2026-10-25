FROM node:22.22.0-bookworm-slim AS node
FROM python:3.11.14-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers DISCORD_ARCHIVE_DOCKER=1 \
    DISCORD_ARCHIVE_CREDENTIAL_STORE=file ARCHIVE_ROOT=/app \
    HF_HUB_DISABLE_TELEMETRY=1 HF_HOME=/tmp/huggingface
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update && apt-get install -y --no-install-recommends ca-certificates ffmpeg fonts-noto-cjk \
 && python -m venv /opt/whisper \
 && /opt/whisper/bin/pip install --no-cache-dir faster-whisper==1.2.1
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
 && node node_modules/playwright/cli.js install --with-deps chromium \
 && chmod -R a+rX /opt/browsers \
 && useradd --uid 1000 --create-home app \
 && mkdir -p data output .runtime/models .local \
 && chown -R app:app data output .runtime .local
COPY app.py ./
COPY discord_archive ./discord_archive
COPY web ./web
COPY scripts ./scripts
COPY tests ./tests
COPY docker ./docker
COPY helpers ./helpers
RUN python scripts/install_login_assistants.py --mac-zip helpers/login-assistant-mac.zip --windows-zip helpers/login-assistant-windows.zip \
 && chown -R app:app /app/.local \
 && chmod -R a+rX /app/scripts /app/docker /app/discord_archive /app/web \
 && rm -rf /var/lib/apt/lists/* /root/.cache /root/.npm
COPY --chown=app:app models/ /app/.runtime/models/
USER app
RUN /opt/whisper/bin/python -c "from pathlib import Path; from faster_whisper import WhisperModel; from faster_whisper.utils import download_model; p=Path('/app/.runtime/models/faster-whisper-small'); download_model('small',output_dir=str(p)) if not (p/'model.bin').is_file() else None; WhisperModel(str(p),device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)"
USER app
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 CMD ["python","docker/manage.py","health"]
STOPSIGNAL SIGTERM
ENTRYPOINT ["python","docker/supervisor.py"]
