FROM python:3.12-slim

WORKDIR /app

COPY external_info_service.py .

# The feed is not copied: docker-compose.yml mounts the trainer's
# data/external_service/risk_feed.json, so an edited feed only needs a restart.
ENV RISK_FEED_PATH=/feed/risk_feed.json

EXPOSE 8099

CMD ["python", "external_info_service.py", "8099"]
