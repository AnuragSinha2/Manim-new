# Dockerfile for Manim CE - Optimized for Security and Efficiency

FROM python:3.12-slim as base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gosu build-essential ffmpeg libportaudio2 portaudio19-dev libasound-dev \
    libcairo2-dev libpango1.0-dev texlive-latex-base texlive-latex-extra \
    texlive-fonts-recommended texlive-fonts-extra dvisvgm git apt-transport-https \
    ca-certificates gnupg curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add - && \
    apt-get update -y && apt-get install google-cloud-sdk -y

FROM base as final

ARG UID=1001
ARG GID=1001
RUN groupadd -g $GID manimgroup && \
    useradd -u $UID -g manimgroup -m -s /bin/bash manimuser

RUN mkdir -p /manim/animations /manim/media /manim/temp /manim/uploads /manim/tts_output /manim/output /manim/logs /manim/manim_output /manim/assets /tmp/manim_output && \
    chown -R manimuser:manimgroup /manim /tmp/manim_output

USER manimuser
WORKDIR /manim

COPY --chown=manimuser:manimgroup requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PATH="/home/manimuser/.local/bin:${PATH}"
COPY --chown=manimuser:manimgroup . .

USER root
RUN chmod +x /manim/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/manim/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]