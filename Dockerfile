FROM python:3.12-slim

# タイムゾーン設定
ENV TZ=Asia/Tokyo
ENV UV_CACHE_DIR=/app/.uv-cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv のインストール
RUN pip install uv

# 依存関係のインストール（キャッシュ効率化のため先にコピー）
# uv.lock があれば利用し、なければ pyproject.toml から生成する
# --no-install-project: Webアプリのためプロジェクト自体はビルド不要
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# アプリケーションコードのコピー
COPY app/ ./app/
COPY prompts/ ./prompts/

# 必要なディレクトリを作成し、実行ユーザー(1001)に権限を付与
RUN mkdir -p data summaries db logs && chown -R 1001:1001 /app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
