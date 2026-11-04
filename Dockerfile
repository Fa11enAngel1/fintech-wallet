FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fintech ./fintech
ENV WALLET_DB=/data/wallet.db
VOLUME /data
EXPOSE 8000
RUN useradd -m app && mkdir -p /data && chown app /data
USER app
CMD ["gunicorn", "-b", "0.0.0.0:8000", "fintech.web:create_app()"]
