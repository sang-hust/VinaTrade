"""News RSS feeds (headline + summary + link only; full text is never copied)."""

import html
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from app.ingestion.adapters.base import DataAdapter

FEEDS = [
    ("CafeF", "https://cafef.vn/thi-truong-chung-khoan.rss", True),
    ("CafeF", "https://cafef.vn/doanh-nghiep.rss", False),
    ("Vietstock", "https://vietstock.vn/830/chung-khoan/co-phieu.rss", False),
    ("Vietstock", "https://vietstock.vn/737/doanh-nghiep/hoat-dong-kinh-doanh.rss", False),
    ("VnExpress", "https://vnexpress.net/rss/kinh-doanh.rss", True),
    ("VnEconomy", "https://vneconomy.vn/chung-khoan.rss", True),
]


def _clean(s: str | None) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def _img(desc: str | None) -> str | None:
    m = re.search(r'<img[^>]+src="([^"]+)"', desc or "")
    return m.group(1) if m else None


class RSSAdapter(DataAdapter):
    code = "RSS"

    async def fetch(self, source: str, url: str) -> list[dict]:
        r = await self.client.get(url, follow_redirects=True)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        out = []
        for it in root.iter("item"):
            link = (it.findtext("link") or "").strip()
            title = _clean(it.findtext("title"))
            if not link or not title:
                continue
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate") or "")
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                pub = datetime.now(UTC)
            desc_raw = it.findtext("description")
            out.append({"url": link[:500], "source": source, "title": title[:500], "summary": _clean(desc_raw)[:1200] or None,
                        "image_url": (_img(desc_raw) or "")[:500] or None, "published_at": pub})
        return out
