"""
GitHub Trending 収集モジュール
全言語のトレンドリポジトリを daily/weekly/monthly の3期間でスクレイピングし、
AI/LLM 関連キーワードでフィルタリングして収集する。
スマート再収集: 過去に調査済みのリポジトリは条件付きで再利用する。
"""

import hashlib
import json
import logging
import re
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.schemas import ArticleItem, DailyCollection

logger = logging.getLogger(__name__)

GITHUB_TRENDING_URL = "https://github.com/trending"
PERIODS = ["daily", "weekly", "monthly"]
INDEX_FILE = "github_trending_index.json"
KEYWORDS_FILE = "github_trending_keywords.json"


# ── 公開 API ──────────────────────────────────────────────────


async def collect_github_trending(target_date: date | None = None) -> list[ArticleItem]:
    """GitHub Trending (全言語) から AI/LLM 関連リポジトリを収集する"""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    collection_date = target_date + timedelta(days=1)
    collection_date_str = collection_date.isoformat()

    # 1. 3期間スクレイピング
    raw_by_period: dict[str, list[_RawRepo]] = {}
    for period in PERIODS:
        repos = await _scrape_trending_page(period)
        raw_by_period[period] = repos
        logger.info(f"GitHub Trending ({period}): {len(repos)} 件取得")

    # 2. キーワードフィルタ
    keywords = _load_keywords()
    for period, repos in raw_by_period.items():
        filtered = _filter_by_keywords(repos, keywords)
        raw_by_period[period] = filtered
        logger.info(f"GitHub Trending ({period}): フィルタ後 {len(filtered)} 件")

    # 3. 上限適用
    max_results = settings.github_trending_max_results
    for period in PERIODS:
        raw_by_period[period] = raw_by_period[period][:max_results]

    # 4. URL をキーにマージ（重複統合）
    merged = _merge_periods(raw_by_period)
    logger.info(f"GitHub Trending: マージ後 {len(merged)} ユニークリポジトリ")

    # 5. スマート再収集判定
    index = _load_index()
    items, resurveyed_urls = _build_items_with_reuse(
        merged, index, target_date, collection_date_str
    )

    # 6. インデックス更新
    _update_index(index, merged, collection_date_str, resurveyed_urls)
    _save_index(index)

    logger.info(f"GitHub Trending 収集完了: {len(items)} 件")
    return items


# ── 内部データ構造 ────────────────────────────────────────────


class _RawRepo:
    """スクレイピングで取得した生リポジトリ情報"""

    __slots__ = ("name", "url", "description", "stars_total", "stars_period")

    def __init__(
        self, name: str, url: str, description: str, stars_total: int, stars_period: int
    ):
        self.name = name
        self.url = url
        self.description = description
        self.stars_total = stars_total
        self.stars_period = stars_period


class _MergedRepo:
    """3期間分をマージしたリポジトリ情報"""

    __slots__ = (
        "name",
        "url",
        "description",
        "stars_total",
        "stars_daily",
        "stars_weekly",
        "stars_monthly",
        "rankings",
        "rank_daily",
        "rank_weekly",
        "rank_monthly",
        "rank_total",
    )

    def __init__(self, name: str, url: str, description: str, stars_total: int):
        self.name = name
        self.url = url
        self.description = description
        self.stars_total = stars_total
        self.stars_daily = 0
        self.stars_weekly = 0
        self.stars_monthly = 0
        self.rankings: set[str] = set()
        self.rank_daily = 0
        self.rank_weekly = 0
        self.rank_monthly = 0
        self.rank_total = 0


# ── スクレイピング ────────────────────────────────────────────


async def _scrape_trending_page(period: str) -> list[_RawRepo]:
    """GitHub Trending の1ページをスクレイピングする"""
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Daily-Survey/1.0)"},
        ) as client:
            resp = await client.get(
                GITHUB_TRENDING_URL,
                params={"since": period},
                follow_redirects=True,
            )
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"GitHub Trending ({period}) 取得失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    repos: list[_RawRepo] = []

    for article in soup.select("article.Box-row"):
        h2 = article.select_one("h2 a")
        if not h2:
            continue

        href = str(h2.get("href", "")).strip()
        if not href:
            continue
        repo_url = f"https://github.com{href}"
        repo_name = href.strip("/")

        desc_el = article.select_one("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        # 総スター数
        stars_el = article.select_one("a[href$='/stargazers']")
        stars_total = (
            _parse_star_count(stars_el.get_text(strip=True)) if stars_el else 0
        )

        # 期間スター増加数（"N stars today/this week/this month"）
        period_el = article.select_one("span.d-inline-block.float-sm-right")
        stars_period = 0
        if period_el:
            stars_period = _parse_star_count(period_el.get_text(strip=True))

        repos.append(
            _RawRepo(
                name=repo_name,
                url=repo_url,
                description=description,
                stars_total=stars_total,
                stars_period=stars_period,
            )
        )

    return repos


def _parse_star_count(text: str) -> int:
    """'1,234' や '1.2k stars today' → 整数に変換"""
    text = text.lower().replace(",", "").strip()
    # 数値部分だけ抽出
    m = re.match(r"([\d.]+)\s*k?", text)
    if not m:
        return 0
    num = float(m.group(1))
    if "k" in text:
        return int(num * 1000)
    return int(num)


# ── フィルタ・マージ ──────────────────────────────────────────


def _filter_by_keywords(repos: list[_RawRepo], keywords: list[str]) -> list[_RawRepo]:
    """キーワードで AI/LLM 関連リポジトリをフィルタリング"""
    if not keywords:
        return repos

    patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]
    result = []
    for repo in repos:
        text = f"{repo.name} {repo.description}"
        if any(p.search(text) for p in patterns):
            result.append(repo)
    return result


def _merge_periods(raw_by_period: dict[str, list[_RawRepo]]) -> list[_MergedRepo]:
    """3期間分の結果を URL をキーにマージし、ランキング順位を付与"""
    merged_dict: dict[str, _MergedRepo] = {}

    period_to_attr = {
        "daily": "stars_daily",
        "weekly": "stars_weekly",
        "monthly": "stars_monthly",
    }

    for period, repos in raw_by_period.items():
        attr = period_to_attr[period]
        for rank, repo in enumerate(repos, 1):
            if repo.url not in merged_dict:
                merged_dict[repo.url] = _MergedRepo(
                    name=repo.name,
                    url=repo.url,
                    description=repo.description,
                    stars_total=repo.stars_total,
                )
            m = merged_dict[repo.url]
            setattr(m, attr, repo.stars_period)
            m.rankings.add(period)
            setattr(m, f"rank_{period}", rank)
            # 総スター数は最大値を採用
            if repo.stars_total > m.stars_total:
                m.stars_total = repo.stars_total

    # total ランキング順位を付与（全リポジトリを総スター降順でソート）
    all_repos = sorted(merged_dict.values(), key=lambda r: r.stars_total, reverse=True)
    for total_rank, merged in enumerate(all_repos, 1):
        merged.rank_total = total_rank
        merged.rankings.add("total")

    return all_repos


# ── スマート再収集 ────────────────────────────────────────────


def _build_items_with_reuse(
    merged: list[_MergedRepo],
    index: dict,
    target_date: date,
    collection_date_str: str,
) -> tuple[list[ArticleItem], set[str]]:
    """マージ済みリポジトリからArticleItemリストを構築（再利用判定込み）
    Returns: (items, resurveyed_urls) — resurveyed_urls は新規調査対象の URL セット
    """
    stale_days = settings.github_trending_stale_days
    items: list[ArticleItem] = []
    resurveyed_urls: set[str] = set()

    for repo in merged:
        tags = _build_ranking_tags(repo)
        repo_id = f"github_trending:{_url_to_id(repo.url)}"

        # 再利用判定
        reused_item = _try_reuse(
            repo, index, target_date, stale_days, collection_date_str
        )

        if reused_item is not None:
            # ランキング tags を更新（他の tags は維持）
            base_tags = [t for t in reused_item.tags if not _is_ranking_tag(t)]
            reused_item.tags = base_tags + tags
            # reused_from タグ追加
            if not any(t.startswith("reused_from:") for t in reused_item.tags):
                reused_item.tags.append(f"reused_from:{reused_item.published_date}")
            reused_item.id = repo_id
            items.append(reused_item)
        else:
            resurveyed_urls.add(repo.url)
            title = repo.name
            if repo.stars_total:
                title += f" ({_format_stars(repo.stars_total)})"

            items.append(
                ArticleItem(
                    id=repo_id,
                    title_en=title,
                    title_ja=title,
                    abstract_en=repo.description,
                    published_date=target_date.isoformat(),
                    url=repo.url,
                    source_type="github_trending",
                    source_name="GitHub Trending",
                    tags=["github", "trending"] + tags,
                )
            )

    return items, resurveyed_urls


def _try_reuse(
    repo: _MergedRepo,
    index: dict,
    target_date: date,
    stale_days: int,
    collection_date_str: str,
) -> ArticleItem | None:
    """過去の調査結果を再利用できるか判定し、可能なら ArticleItem を返す"""
    repos_index = index.get("repos", {})
    entry = repos_index.get(repo.url)

    if entry is None:
        return None

    last_surveyed = entry.get("last_surveyed_date", "")
    if not last_surveyed:
        return None

    # 期限切れチェック
    try:
        surveyed_date = date.fromisoformat(last_surveyed)
    except ValueError:
        return None

    if (target_date - surveyed_date).days >= stale_days:
        return None

    # description 変更チェック
    old_hash = entry.get("description_hash", "")
    new_hash = hashlib.md5(repo.description.encode()).hexdigest()[:16]
    if old_hash and old_hash != new_hash:
        return None

    # 過去データから ArticleItem を取得
    return _load_previous_item(repo.url, last_surveyed)


def _load_previous_item(repo_url: str, surveyed_date_str: str) -> ArticleItem | None:
    """過去の JSON ファイルから該当リポジトリの ArticleItem を取得"""
    data_dir = settings.data_dir
    repo_id = f"github_trending:{_url_to_id(repo_url)}"

    # github_trending → python の順でフォールバック
    for filename in ["papers_github_trending.json", "papers_python.json"]:
        file_path = data_dir / surveyed_date_str / filename
        if not file_path.exists():
            continue
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
            collection = DailyCollection.model_validate(raw)
            for item in collection.items:
                if item.id == repo_id or item.url == repo_url:
                    return item.model_copy()
        except Exception as e:
            logger.warning(f"過去データ読み込み失敗 ({file_path}): {e}")

    return None


# ── ランキングタグ構築 ────────────────────────────────────────


def _build_ranking_tags(repo: _MergedRepo) -> list[str]:
    """ランキング情報を tags 文字列リストとして構築"""
    tags = []
    for period in PERIODS:
        if period in repo.rankings:
            tags.append(f"ranking:{period}")
    tags.append("ranking:total")

    tags.append(f"stars_daily:{repo.stars_daily}")
    tags.append(f"stars_weekly:{repo.stars_weekly}")
    tags.append(f"stars_monthly:{repo.stars_monthly}")
    tags.append(f"stars_total:{repo.stars_total}")

    if repo.rank_daily:
        tags.append(f"rank_daily:{repo.rank_daily}")
    if repo.rank_weekly:
        tags.append(f"rank_weekly:{repo.rank_weekly}")
    if repo.rank_monthly:
        tags.append(f"rank_monthly:{repo.rank_monthly}")
    if repo.rank_total:
        tags.append(f"rank_total:{repo.rank_total}")

    return tags


def _is_ranking_tag(tag: str) -> bool:
    """ランキング関連のタグか判定"""
    prefixes = ("ranking:", "stars_", "rank_", "reused_from:")
    return any(tag.startswith(p) for p in prefixes)


# ── インデックス管理 ──────────────────────────────────────────


def _load_index() -> dict:
    """github_trending_index.json を読み込む"""
    path = settings.data_dir / INDEX_FILE
    if not path.exists():
        return {"repos": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"repos": {}}


def _save_index(index: dict) -> None:
    """github_trending_index.json を保存"""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / INDEX_FILE
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def _update_index(
    index: dict,
    merged: list[_MergedRepo],
    collection_date_str: str,
    resurveyed_urls: set[str],
) -> None:
    """インデックスを最新のスクレイピング結果で更新"""
    repos = index.setdefault("repos", {})
    for repo in merged:
        desc_hash = hashlib.md5(repo.description.encode()).hexdigest()[:16]
        entry = repos.get(repo.url, {})
        is_resurveyed = repo.url in resurveyed_urls

        repos[repo.url] = {
            "last_seen_date": collection_date_str,
            "last_surveyed_date": collection_date_str
            if is_resurveyed
            else entry.get("last_surveyed_date", collection_date_str),
            "description_hash": desc_hash,
        }


# ── キーワード管理 ────────────────────────────────────────────


def _load_keywords() -> list[str]:
    """カスタムキーワードファイルがあればそちらを優先、なければ config のデフォルト"""
    path = settings.data_dir / KEYWORDS_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return settings.github_trending_keywords


def load_keywords() -> list[str]:
    """外部から呼べるキーワード読み込み（ルーター用）"""
    return _load_keywords()


def save_keywords(keywords: list[str]) -> None:
    """キーワードリストを永続化"""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / KEYWORDS_FILE
    path.write_text(
        json.dumps(keywords, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── ユーティリティ ────────────────────────────────────────────


def _url_to_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _format_stars(count: int) -> str:
    """スター数を読みやすい形式にフォーマット"""
    if count >= 1000:
        return f"★ {count:,}"
    return f"★ {count}"
