# ML service image. Build context = PMG_AI/ (it needs pmg_predict.py + artifacts/ from the parent folder).
# python 3.12: scikit-learn 1.7.2 (pinned to match the joblib model) has wheels for 3.11-3.13.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 ML_HOST=0.0.0.0 ML_PORT=5001 LOG_DIR=/logs
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY pmg_predict.py demo_claims.py ./
COPY artifacts/ artifacts/
COPY ml_service/ ml_service/
RUN useradd -r -u 10001 pmg && mkdir /logs && chown pmg /logs
USER pmg
EXPOSE 5001
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:5001/health', timeout=2)"
CMD ["python", "ml_service/serve.py"]
