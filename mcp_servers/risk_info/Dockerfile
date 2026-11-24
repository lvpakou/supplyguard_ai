FROM python:3.12-slim
WORKDIR /service
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
ENV MCP_HOST=0.0.0.0 MCP_PORT=8000 MCP_TRANSPORT=streamable-http
ENV RISK_SERVICE_URL=http://risk-info:8099
EXPOSE 8000
CMD ["python", "server.py"]
