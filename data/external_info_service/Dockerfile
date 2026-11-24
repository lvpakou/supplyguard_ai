FROM python:3.12-slim

WORKDIR /app

COPY external_info_service.py .
COPY risk_feed.json .

ENV PORT=8099

EXPOSE 8099

CMD ["python", "external_info_service.py"]