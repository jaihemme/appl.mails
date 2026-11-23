# Image minimale : les scripts n'utilisent que la bibliothèque standard de Python.
FROM python:3.13-slim

# encodage UTF-8 systématique + heure locale pour les horodatages
ENV PYTHONUTF8=1 \
    TZ=Europe/Zurich

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY src/ /app/src/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# tout le travail (entrée + résultats) se fait dans /data : à mapper sur l'hôte
VOLUME /data

ENTRYPOINT ["/app/entrypoint.sh"]
