#!/usr/bin/env python3
"""Read-only public DTC store auditor using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


VERSION = "1.1.0"
USER_AGENT = "AuditDTCStore/1.1 (+read-only website quality audit)"
MAX_BODY_BYTES = 4_000_000
VALID_STATUSES = {"pass", "warn", "fail", "unknown"}
VALID_SOURCE_TYPES = {"public-browser", "authorized-browser", "user-export", "local-lab", "enhanced"}
VALID_AUTHORIZATIONS = {
    "public-readonly",
    "browser-authorized-readonly",
    "authorized-side-effect",
    "user-provided",
}
SAFETY_KEYS = {
    "submitted_forms",
    "created_account",
    "generated_abandoned_checkout",
    "triggered_messages",
    "submitted_order",
}

CATEGORIES = {
    "conversion": {"label": "转化闭环", "weight": 35},
    "traffic": {"label": "投流承接", "weight": 30},
    "seo": {"label": "SEO 基础", "weight": 20},
    "ux": {"label": "移动端与基础体验", "weight": 15},
}

CHECKS = {
    "C1": {"category": "conversion", "weight": 4, "label": "首页和核心商品页可访问", "priority": "P0"},
    "C2": {"category": "conversion", "weight": 6, "label": "商品页存在明确加购/购买入口", "priority": "P0"},
    "C3": {"category": "conversion", "weight": 6, "label": "支持 Guest Checkout", "priority": "P0"},
    "C4": {"category": "conversion", "weight": 7, "label": "三步内到达付款页", "priority": "P0"},
    "C5": {"category": "conversion", "weight": 7, "label": "主流支付方式可见", "priority": "P0"},
    "C6": {"category": "conversion", "weight": 5, "label": "Checkout 无阻断错误", "priority": "P0"},
    "T1": {"category": "traffic", "weight": 4, "label": "基础网络响应不超过 3 秒", "priority": "P1"},
    "T2": {"category": "traffic", "weight": 7, "label": "移动性能达到合格阈值", "priority": "P1"},
    "T3": {"category": "traffic", "weight": 6, "label": "广告落地页与承诺商品一致", "priority": "P1"},
    "T4": {"category": "traffic", "weight": 5, "label": "具备评价与物流/退换承诺", "priority": "P1"},
    "T5": {"category": "traffic", "weight": 4, "label": "移动端首屏直接呈现对应商品", "priority": "P1"},
    "T6": {"category": "traffic", "weight": 4, "label": "具备弃购挽回机制", "priority": "P1"},
    "S1": {"category": "seo", "weight": 4, "label": "核心页面 Title 描述性强且不重复", "priority": "P1"},
    "S2": {"category": "seo", "weight": 3, "label": "核心页面 Meta Description 完整", "priority": "P1"},
    "S3": {"category": "seo", "weight": 2, "label": "商品图片文件名与 Alt 基本可读", "priority": "P2"},
    "S4": {"category": "seo", "weight": 3, "label": "Sitemap 可发现且可读取", "priority": "P1"},
    "S5": {"category": "seo", "weight": 3, "label": "Canonical 与索引指令合理", "priority": "P1"},
    "S6": {"category": "seo", "weight": 2, "label": "商品页具有 Product 结构化数据", "priority": "P2"},
    "S7": {"category": "seo", "weight": 3, "label": "Search Console 已验证并有可读数据", "priority": "P1"},
    "U1": {"category": "ux", "weight": 2, "label": "页面声明移动端 Viewport", "priority": "P1"},
    "U2": {"category": "ux", "weight": 4, "label": "手机端无明显错位、溢出或遮挡", "priority": "P0"},
    "U3": {"category": "ux", "weight": 3, "label": "无关键死链和破图", "priority": "P1"},
    "U4": {"category": "ux", "weight": 4, "label": "物流与退换政策页齐全", "priority": "P1"},
    "U5": {"category": "ux", "weight": 2, "label": "联系入口可发现", "priority": "P2"},
}

CTA_PATTERNS = [
    r"\badd to (?:cart|bag|basket)\b",
    r"\badd to basket\b",
    r"\bbuy (?:now|it now)\b",
    r"\bshop now\b",
    r"\bpre-?order\b",
    r"加入购物车",
    r"立即购买",
    r"现在购买",
]
REVIEW_PATTERNS = [r"\breviews?\b", r"\bratings?\b", r"\bstars?\b", r"评价", r"评论", r"评分"]
SHIPPING_PATTERNS = [r"\bshipping\b", r"\bdelivery\b", r"\bships?\b", r"物流", r"配送", r"发货"]
RETURN_PATTERNS = [r"\breturns?\b", r"\brefunds?\b", r"\bexchange\b", r"退货", r"退款", r"换货"]
POLICY_PATTERNS = {
    "shipping": [r"shipping", r"delivery", r"物流", r"配送"],
    "returns": [r"return", r"refund", r"exchange", r"退换", r"退货", r"退款"],
    "privacy": [r"privacy", r"隐私"],
    "terms": [r"terms", r"conditions", r"条款"],
    "contact": [r"contact", r"support", r"help", r"联系我们", r"客服"],
}
SKIP_PATH_PATTERNS = [
    r"/account(?:/|$)",
    r"/login(?:/|$)",
    r"/register(?:/|$)",
    r"/checkout(?:/|$)",
    r"/cart(?:/|$)",
    r"/admin(?:/|$)",
    r"/search(?:/|$)",
]
ASSET_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico",
    ".css", ".js", ".json", ".xml", ".pdf", ".zip", ".mp4", ".webm",
    ".woff", ".woff2", ".ttf", ".eot",
}


class StoreHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.in_script = False
        self.script_type = ""
        self.script_parts: list[str] = []
        self.json_ld: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.headings: list[dict[str, str]] = []
        self.controls: list[str] = []
        self.text_parts: list[str] = []
        self._active_link: dict[str, Any] | None = None
        self._active_heading: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (attrs_dict.get("name") or attrs_dict.get("property") or attrs_dict.get("http-equiv") or "").lower()
            if key:
                self.meta[key] = attrs_dict.get("content", "").strip()
        elif tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href", "")
            if href:
                self.links.append({"href": href, "text": "", "rel": rel})
        elif tag == "a":
            self._active_link = {
                "href": attrs_dict.get("href", ""),
                "text_parts": [],
                "rel": attrs_dict.get("rel", "").lower(),
            }
        elif tag == "img":
            src = attrs_dict.get("src") or attrs_dict.get("data-src") or attrs_dict.get("data-lazy-src") or ""
            self.images.append({
                "src": src,
                "alt": attrs_dict.get("alt", "").strip(),
                "width": attrs_dict.get("width", ""),
                "height": attrs_dict.get("height", ""),
            })
        elif tag in {"h1", "h2", "h3"}:
            self._active_heading = {"tag": tag, "text_parts": []}
        elif tag in {"button", "input"}:
            control_text = " ".join([
                attrs_dict.get("value", ""),
                attrs_dict.get("aria-label", ""),
                attrs_dict.get("name", ""),
                attrs_dict.get("id", ""),
                attrs_dict.get("class", ""),
            ]).strip()
            if control_text:
                self.controls.append(control_text)
        elif tag == "script":
            self.in_script = True
            self.script_type = attrs_dict.get("type", "").lower()
            self.script_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        elif tag == "a" and self._active_link is not None:
            self.links.append({
                "href": self._active_link["href"],
                "text": clean_text(" ".join(self._active_link["text_parts"])),
                "rel": self._active_link["rel"],
            })
            self._active_link = None
        elif tag in {"h1", "h2", "h3"} and self._active_heading is not None:
            self.headings.append({
                "tag": self._active_heading["tag"],
                "text": clean_text(" ".join(self._active_heading["text_parts"])),
            })
            self._active_heading = None
        elif tag == "script":
            if self.script_type == "application/ld+json":
                self.json_ld.append("".join(self.script_parts).strip())
            self.in_script = False
            self.script_type = ""
            self.script_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.in_script:
            self.script_parts.append(data)
            return
        text = clean_text(data)
        if not text:
            return
        self.text_parts.append(text)
        if self._active_link is not None:
            self._active_link["text_parts"].append(text)
        if self._active_heading is not None:
            self._active_heading["text_parts"].append(text)

    @property
    def title(self) -> str:
        return clean_text(" ".join(self.title_parts))

    @property
    def visible_text(self) -> str:
        return clean_text(" ".join(self.text_parts))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def normalize_start_url(raw: str) -> str:
    raw = raw.strip()
    if not re.match(r"^https?://", raw, flags=re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.netloc:
        raise ValueError(f"无效 URL：{raw}")
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", parsed.query, ""))


def normalize_link(base: str, href: str) -> str | None:
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    absolute = urldefrag(urljoin(base, href))[0]
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if Path(parsed.path.lower()).suffix in ASSET_EXTENSIONS:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))


def host_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    return host_key(a) == host_key(b)


def safe_crawl_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return not any(re.search(pattern, path) for pattern in SKIP_PATH_PATTERNS)


def fetch_url(url: str, timeout: float, method: str = "GET", max_bytes: int = MAX_BODY_BYTES) -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    if method == "GET" and max_bytes < MAX_BODY_BYTES:
        headers["Range"] = f"bytes=0-{max_bytes - 1}"
    request = Request(url, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = b"" if method == "HEAD" else response.read(max_bytes)
            elapsed = time.perf_counter() - started
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                text = body.decode(charset, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "url": url,
                "final_url": response.geturl(),
                "elapsed_seconds": round(elapsed, 3),
                "content_type": content_type,
                "headers": dict(response.headers.items()),
                "text": text,
                "error": "",
            }
    except HTTPError as exc:
        elapsed = time.perf_counter() - started
        body = b""
        if method != "HEAD":
            try:
                body = exc.read(max_bytes)
            except Exception:
                body = b""
        return {
            "ok": False,
            "status": exc.code,
            "url": url,
            "final_url": exc.geturl(),
            "elapsed_seconds": round(elapsed, 3),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "text": body.decode("utf-8", errors="replace"),
            "error": str(exc),
        }
    except (URLError, TimeoutError, OSError) as exc:
        elapsed = time.perf_counter() - started
        return {
            "ok": False,
            "status": 0,
            "url": url,
            "final_url": url,
            "elapsed_seconds": round(elapsed, 3),
            "content_type": "",
            "headers": {},
            "text": "",
            "error": str(exc),
        }


def parse_html(response: dict[str, Any]) -> StoreHTMLParser | None:
    if "html" not in response.get("content_type", "").lower() and "<html" not in response.get("text", "")[:1000].lower():
        return None
    parser = StoreHTMLParser()
    try:
        parser.feed(response.get("text", ""))
    except Exception:
        return parser
    return parser


def contains_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def has_jsonld_type(raw_items: list[str], expected: str) -> bool:
    def walk(value: Any) -> bool:
        if isinstance(value, dict):
            type_value = value.get("@type")
            if isinstance(type_value, str) and type_value.lower() == expected.lower():
                return True
            if isinstance(type_value, list) and any(str(item).lower() == expected.lower() for item in type_value):
                return True
            return any(walk(item) for item in value.values())
        if isinstance(value, list):
            return any(walk(item) for item in value)
        return False

    for raw in raw_items:
        try:
            if walk(json.loads(raw)):
                return True
        except (json.JSONDecodeError, TypeError):
            continue
    return False


def classify_page(url: str, parser: StoreHTMLParser | None) -> str:
    path = urlparse(url).path.lower()
    if path in {"", "/"}:
        return "home"
    if parser and has_jsonld_type(parser.json_ld, "Product"):
        return "product"
    if re.search(r"/(?:products?|p)/", path):
        return "product"
    if parser:
        purchase_text = " ".join([parser.visible_text, " ".join(parser.controls)])
        has_purchase_cta = contains_any(purchase_text, CTA_PATTERNS)
        has_commerce_signal = bool(re.search(
            r"(?:[$€£¥]\s?\d|\b(?:usd|eur|gbp|cad|aud)\b|\bin stock\b|\bavailability\b|库存|现货)",
            purchase_text,
            flags=re.I,
        ))
        if has_purchase_cta and has_commerce_signal:
            return "product"
    if re.search(r"/(?:collections?|categories?|shop)(?:/|$)", path):
        return "collection"
    if any(re.search(pattern, path) for patterns in POLICY_PATTERNS.values() for pattern in patterns):
        return "policy"
    return "other"


def page_priority(url: str, landing_url: str | None) -> tuple[int, int, str]:
    if landing_url and urldefrag(url)[0] == urldefrag(landing_url)[0]:
        return (0, len(url), url)
    path = urlparse(url).path.lower()
    if re.search(r"/(?:products?|p)/", path):
        return (1, len(url), url)
    if re.search(r"/(?:collections?|categories?|shop)(?:/|$)", path):
        return (2, len(url), url)
    if any(re.search(pattern, path) for patterns in POLICY_PATTERNS.values() for pattern in patterns):
        return (3, len(url), url)
    return (4, len(url), url)


def extract_sitemap_urls(text: str, base_url: str, limit: int = 200) -> list[str]:
    urls: list[str] = []
    for match in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.I | re.S):
        candidate = clean_text(match)
        if candidate:
            candidate = urljoin(base_url, candidate)
            if same_site(base_url, candidate):
                urls.append(candidate)
        if len(urls) >= limit:
            break
    return urls


def generic_image_filename(url: str) -> bool:
    name = Path(urlparse(url).path).stem.lower()
    if not name:
        return True
    if re.fullmatch(r"(?:img|image|photo|pic|dsc|screenshot)[-_]?\d*", name):
        return True
    if re.fullmatch(r"\d{5,}", name):
        return True
    compact = re.sub(r"[^a-z0-9]", "", name)
    if len(compact) >= 16:
        digit_ratio = sum(ch.isdigit() for ch in compact) / len(compact)
        vowel_ratio = sum(ch in "aeiou" for ch in compact) / len(compact)
        if digit_ratio > 0.45 or vowel_ratio < 0.08:
            return True
    return False


def probe_status(url: str, timeout: float) -> dict[str, Any]:
    result = fetch_url(url, timeout=timeout, method="HEAD", max_bytes=1)
    if result["status"] in {0, 403, 405, 501}:
        result = fetch_url(url, timeout=timeout, method="GET", max_bytes=2048)
    return {
        "url": url,
        "status": result["status"],
        "ok": result["ok"],
        "error": result["error"],
    }


def make_finding(
    check_id: str,
    status: str,
    evidence: str,
    recommendation: str,
    source_url: str = "",
    automation: str = "public",
    value: Any = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"无效状态：{status}")
    check = CHECKS[check_id]
    result = {
        "id": check_id,
        "category": check["category"],
        "label": check["label"],
        "weight": check["weight"],
        "priority": check["priority"],
        "status": status,
        "evidence": clean_text(str(evidence)),
        "recommendation": clean_text(str(recommendation)),
        "source_url": source_url,
        "automation": automation,
    }
    if value is not None:
        result["value"] = value
    if provenance:
        result["provenance"] = provenance
    return result


def unknown_finding(check_id: str, evidence: str, recommendation: str) -> dict[str, Any]:
    return make_finding(check_id, "unknown", evidence, recommendation, automation="unverified")


def parse_evidence_timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 必须是 ISO 8601 时间字符串")
    normalized = value.strip()
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} 不是有效的 ISO 8601 时间：{normalized}") from exc
    return normalized


def validate_pass_evidence(check_id: str, item: dict[str, Any]) -> None:
    if check_id == "T6" and item["status"] in {"pass", "fail"}:
        value = item.get("value")
        if not isinstance(value, dict):
            raise ValueError(f"{check_id} 判定 {item['status']} 时必须提供 value 对象")
        authoritative_sources = {
            "automation_detail",
            "automation_list",
            "platform_settings",
            "user_export",
        }
        config_source = value.get("config_state_source")
        if item["status"] == "pass":
            successful_evidence = value.get("recent_successful_run") is True or value.get("message_received") is True
            if (
                value.get("config_enabled") is not True
                or config_source not in authoritative_sources
                or not successful_evidence
            ):
                raise ValueError(
                    "T6 pass 需要权威详情/列表/设置证据证明自动化已启用，"
                    "并有近期成功 Run 或已收到测试消息"
                )
        else:
            failure_basis = value.get("failure_basis")
            disabled_config = (
                failure_basis == "disabled_config"
                and value.get("config_enabled") is False
                and config_source in authoritative_sources
            )
            persistent_failures = (
                failure_basis == "persistent_failures"
                and value.get("recent_runs_failed") is True
                and config_source in authoritative_sources
            )
            broken_recovery_link = (
                failure_basis == "broken_recovery_link"
                and value.get("recovery_link_valid") is False
                and config_source in authoritative_sources
            )
            if not (disabled_config or persistent_failures or broken_recovery_link):
                raise ValueError(
                    "T6 fail 需要权威详情/列表/设置证据证明配置关闭、持续失败或恢复链接失效；"
                    "首页推荐卡和单次投递状态不能作为失败依据"
                )
        return

    if item["status"] != "pass" or check_id not in {"T2", "T3", "T6", "S7"}:
        return
    value = item.get("value")
    if not isinstance(value, dict):
        raise ValueError(f"{check_id} 判定 pass 时必须提供 value 对象")

    if check_id == "T2":
        if value.get("data_type") != "field":
            raise ValueError("T2 只有移动端字段数据才能判定 pass；实验室数据最高为 warn")
        if value.get("form_factor") != "PHONE":
            raise ValueError("T2 判定 pass 时 form_factor 必须为 PHONE")
        status_good = all(value.get(key) == "good" for key in ("lcp_status", "inp_status", "cls_status"))
        numeric_good = (
            isinstance(value.get("lcp_ms"), (int, float))
            and isinstance(value.get("inp_ms"), (int, float))
            and isinstance(value.get("cls"), (int, float))
            and value["lcp_ms"] <= 2500
            and value["inp_ms"] <= 200
            and value["cls"] <= 0.1
        )
        if not (status_good or numeric_good):
            raise ValueError("T2 pass 需要 LCP、INP、CLS 全部为 good，或提供达标的 p75 数值")

    if check_id == "T3":
        fatal = value.get("fatal_mismatches")
        required_matches = ("product_match", "offer_match", "market_match", "cta_available")
        if not isinstance(fatal, list) or fatal or not all(value.get(key) is True for key in required_matches):
            raise ValueError("T3 pass 需要无致命不匹配，且商品、优惠、市场与 CTA 均匹配")

    if check_id == "S7":
        readable = any(
            value.get(key) is True
            for key in ("sitemap_readable", "performance_readable", "url_inspection_readable", "cwv_readable")
        )
        if value.get("property_accessible") is not True or not readable:
            raise ValueError("S7 pass 需要目标 Property 可访问，且至少一类后台数据可读")


def load_enhanced_evidence(path: Path | None) -> dict[str, Any]:
    if not path:
        return {"audit_version": None, "session": {}, "checks": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("增强证据 JSON 顶层必须是对象")
    evidence_version = str(payload.get("audit_version", "1.0"))
    strict_v11 = evidence_version.startswith("1.1")

    session = payload.get("session", {})
    if not isinstance(session, dict):
        raise ValueError("增强证据 JSON 的 session 必须是对象")
    authorization = session.get("authorization")
    if authorization is not None and authorization not in VALID_AUTHORIZATIONS:
        raise ValueError(f"session.authorization 无效：{authorization}")
    if strict_v11:
        if authorization not in VALID_AUTHORIZATIONS:
            raise ValueError("1.1 增强证据必须提供有效的 session.authorization")
        parse_evidence_timestamp(session.get("captured_at"), "session.captured_at")

    raw_safety = session.get("safety", {})
    if not isinstance(raw_safety, dict):
        raise ValueError("session.safety 必须是对象")
    safety: dict[str, bool] = {}
    for key, value in raw_safety.items():
        if key not in SAFETY_KEYS:
            continue
        if not isinstance(value, bool):
            raise ValueError(f"session.safety.{key} 必须是布尔值")
        safety[key] = value
    if strict_v11:
        missing_safety = sorted(SAFETY_KEYS - set(safety))
        if missing_safety:
            raise ValueError(f"1.1 增强证据缺少 safety 字段：{', '.join(missing_safety)}")
        if safety.get("created_account") or safety.get("submitted_order"):
            raise ValueError("本 Skill 不支持创建账户或提交订单")
        side_effect_happened = any(
            safety.get(key, False)
            for key in ("submitted_forms", "generated_abandoned_checkout", "triggered_messages")
        )
        if side_effect_happened and authorization != "authorized-side-effect":
            raise ValueError("发生测试表单、弃购记录或消息触发时，authorization 必须为 authorized-side-effect")

    checks = payload.get("checks", {})
    if not isinstance(checks, dict):
        raise ValueError("增强证据 JSON 的 checks 必须是对象")
    valid: dict[str, dict[str, Any]] = {}
    for check_id, item in checks.items():
        if check_id not in CHECKS or not isinstance(item, dict):
            continue
        status = item.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(f"{check_id} 的 status 无效：{status}")
        if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise ValueError(f"{check_id} 必须提供非空 evidence")
        source_type = item.get("source_type", "enhanced")
        item_authorization = item.get("authorization", authorization)
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"{check_id} 的 source_type 无效：{source_type}")
        if item_authorization is not None and item_authorization not in VALID_AUTHORIZATIONS:
            raise ValueError(f"{check_id} 的 authorization 无效：{item_authorization}")
        if strict_v11:
            if "source_type" not in item or "authorization" not in item or "captured_at" not in item:
                raise ValueError(f"1.1 增强证据中的 {check_id} 必须提供 source_type、authorization、captured_at")
            parse_evidence_timestamp(item["captured_at"], f"{check_id}.captured_at")
        validate_pass_evidence(check_id, item)
        valid[check_id] = item
    return {
        "audit_version": evidence_version,
        "session": {
            "authorization": authorization,
            "captured_at": session.get("captured_at"),
            "safety": safety,
        },
        "checks": valid,
    }


def apply_enhanced(findings: list[dict[str, Any]], enhanced: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in findings}
    for check_id, item in enhanced.items():
        previous = by_id.get(check_id)
        recommendation = item.get("recommendation") or (previous or {}).get("recommendation") or "根据增强证据复测。"
        by_id[check_id] = make_finding(
            check_id,
            item["status"],
            item.get("evidence", "已提供增强证据"),
            recommendation,
            source_url=item.get("source_url", ""),
            automation=item.get("source_type", "enhanced"),
            value=item.get("value"),
            provenance={
                key: item[key]
                for key in ("source_type", "authorization", "captured_at")
                if item.get(key) is not None
            },
        )
    return [by_id[check_id] for check_id in CHECKS]


def audit(args: argparse.Namespace) -> dict[str, Any]:
    start_url = normalize_start_url(args.url)
    landing_url = normalize_start_url(args.landing_url) if args.landing_url else None
    if landing_url and not same_site(start_url, landing_url):
        raise ValueError("landing-url 必须与主站同域")

    home = fetch_url(start_url, timeout=args.timeout)
    home_parser = parse_html(home)
    base_url = home.get("final_url") or start_url
    public_fetch_blocked = home["status"] in {403, 429}

    response_samples = [home["elapsed_seconds"]]
    for _ in range(max(0, args.repeats - 1)):
        sample = fetch_url(start_url, timeout=args.timeout, max_bytes=128_000)
        response_samples.append(sample["elapsed_seconds"])
        time.sleep(0.1)
    median_response = round(statistics.median(response_samples), 3)

    robots_url = urljoin(base_url, "/robots.txt")
    robots = fetch_url(robots_url, timeout=args.timeout, max_bytes=512_000)
    declared_sitemaps = []
    if robots["ok"]:
        for line in robots["text"].splitlines():
            match = re.match(r"\s*sitemap\s*:\s*(\S+)", line, flags=re.I)
            if match:
                declared_sitemaps.append(urljoin(base_url, match.group(1)))

    sitemap_candidates = declared_sitemaps + [
        urljoin(base_url, "/sitemap.xml"),
        urljoin(base_url, "/sitemap_index.xml"),
    ]
    sitemap_result: dict[str, Any] | None = None
    sitemap_urls: list[str] = []
    seen_sitemaps: set[str] = set()
    for candidate in sitemap_candidates:
        if candidate in seen_sitemaps:
            continue
        seen_sitemaps.add(candidate)
        result = fetch_url(candidate, timeout=args.timeout, max_bytes=2_000_000)
        if result["ok"] and ("xml" in result["content_type"].lower() or "<urlset" in result["text"] or "<sitemapindex" in result["text"]):
            sitemap_result = result
            sitemap_urls = extract_sitemap_urls(result["text"], base_url)
            break

    discovered: set[str] = {base_url}
    if landing_url:
        discovered.add(landing_url)
    if home_parser:
        for item in home_parser.links:
            link = normalize_link(base_url, item.get("href", ""))
            if link and same_site(base_url, link) and safe_crawl_url(link):
                discovered.add(link)
    for link in sitemap_urls:
        normalized = normalize_link(base_url, link)
        if normalized and same_site(base_url, normalized) and safe_crawl_url(normalized):
            discovered.add(normalized)

    ordered = [base_url]
    ordered.extend(
        url for url in sorted(discovered - {base_url}, key=lambda item: page_priority(item, landing_url))
        if url != base_url
    )
    selected = ordered[: args.max_pages]

    pages: list[dict[str, Any]] = []
    for index, url in enumerate(selected):
        if index == 0:
            response, parser = home, home_parser
        else:
            response = fetch_url(url, timeout=args.timeout)
            parser = parse_html(response)
            time.sleep(0.1)
        page = {
            "url": url,
            "final_url": response.get("final_url", url),
            "status": response["status"],
            "ok": response["ok"],
            "elapsed_seconds": response["elapsed_seconds"],
            "content_type": response["content_type"],
            "error": response["error"],
            "type": classify_page(url, parser),
            "title": parser.title if parser else "",
            "meta_description": parser.meta.get("description", "") if parser else "",
            "canonical": "",
            "robots_meta": parser.meta.get("robots", "") if parser else "",
            "viewport": parser.meta.get("viewport", "") if parser else "",
            "h1": [item["text"] for item in parser.headings if item["tag"] == "h1"] if parser else [],
            "links": parser.links if parser else [],
            "images": parser.images if parser else [],
            "visible_text": parser.visible_text[:250_000] if parser else "",
            "controls": parser.controls if parser else [],
            "has_product_schema": has_jsonld_type(parser.json_ld, "Product") if parser else False,
        }
        if parser:
            for item in parser.links:
                if "canonical" in item.get("rel", "").split():
                    page["canonical"] = urljoin(url, item.get("href", ""))
                    break
        pages.append(page)

    core_pages = [page for page in pages if page["type"] in {"home", "product", "collection"}]
    product_pages = [page for page in pages if page["type"] == "product"]
    accessible_core = [page for page in core_pages if page["ok"]]

    internal_links: list[str] = []
    image_urls: list[str] = []
    policy_hits: dict[str, list[str]] = defaultdict(list)
    contact_hits: list[str] = []
    for page in pages:
        for item in page["links"]:
            link = normalize_link(page["final_url"], item.get("href", ""))
            if link and same_site(base_url, link):
                combined = f"{link} {item.get('text', '')}"
                for policy_type, patterns in POLICY_PATTERNS.items():
                    if contains_any(combined, patterns):
                        policy_hits[policy_type].append(link)
                        if policy_type == "contact":
                            contact_hits.append(link)
                if safe_crawl_url(link):
                    internal_links.append(link)
        for image in page["images"]:
            src = image.get("src", "")
            if src:
                image_urls.append(urljoin(page["final_url"], src))

    link_results = []
    for url in list(dict.fromkeys(internal_links))[: args.max_links]:
        link_results.append(probe_status(url, timeout=args.timeout))
        time.sleep(0.05)
    image_results = []
    for url in list(dict.fromkeys(image_urls))[: args.max_images]:
        image_results.append(probe_status(url, timeout=args.timeout))
        time.sleep(0.05)

    findings: list[dict[str, Any]] = []

    if public_fetch_blocked:
        findings.append(unknown_finding(
            "C1",
            f"审计客户端收到 HTTP {home['status']}，疑似机器人防护或限流，不能据此判断真实用户不可访问。",
            "改用真实浏览器访问并记录状态；不要把审计客户端被拦截直接判为网站故障。",
        ))
    else:
        c1_ok = home["ok"] and bool(accessible_core)
        c1_status = "pass" if c1_ok and (not product_pages or all(page["ok"] for page in product_pages)) else "fail"
        findings.append(make_finding(
            "C1", c1_status,
            f"首页 HTTP {home['status']}；抽样核心页 {len(accessible_core)}/{len(core_pages)} 可访问。",
            "修复 4xx/5xx、重定向循环或错误模板，并复测首页与核心商品页。",
            source_url=base_url,
        ))

    cta_pages = []
    for page in product_pages:
        haystack = " ".join([page["visible_text"], " ".join(page["controls"])])
        if contains_any(haystack, CTA_PATTERNS):
            cta_pages.append(page["url"])
    if not product_pages:
        findings.append(unknown_finding("C2", "未在抽样页面中识别到商品页。", "提供一个核心商品页 URL 后复测 CTA。"))
    elif len(cta_pages) == len(product_pages):
        findings.append(make_finding("C2", "pass", f"{len(cta_pages)}/{len(product_pages)} 个商品页识别到加购或购买 CTA；静态检查不判断首屏显著性。", "使用手机视口确认 CTA 首屏可见且未被弹窗遮挡。", cta_pages[0]))
    elif cta_pages:
        findings.append(make_finding("C2", "warn", f"仅 {len(cta_pages)}/{len(product_pages)} 个商品页识别到 CTA。", "统一核心商品页的加购入口，并用浏览器确认按钮可见可点击。", cta_pages[0]))
    else:
        findings.append(make_finding("C2", "fail", f"{len(product_pages)} 个商品页均未识别到加购或购买 CTA。", "优先修复商品页购买入口，并复测加购。", product_pages[0]["url"]))

    findings.extend([
        unknown_finding("C3", "公开页面不能可靠确认是否强制注册。", "使用浏览器进入 Checkout，确认可 Guest Checkout。"),
        unknown_finding("C4", "未执行交互式加购到 Checkout。", "用手机视口记录从加购到付款页的主要操作次数。"),
        unknown_finding("C5", "支付图标不能证明 Checkout 中支付方式可用。", "在安全停止点前核对目标市场支付方式；不要提交订单。"),
        unknown_finding("C6", "未执行交互式 Checkout。", "只读进入 Checkout，检查空白页、404 和阻断错误。"),
    ])

    if not home["ok"]:
        t1_status = "unknown"
    elif median_response <= 3:
        t1_status = "pass"
    elif median_response <= 5:
        t1_status = "warn"
    else:
        t1_status = "fail"
    findings.append(make_finding(
        "T1", t1_status,
        f"三次以内公开请求样本：{response_samples} 秒；中位数 {median_response} 秒。该值不是 LCP。",
        "使用移动端字段数据或 Lighthouse 复核；若持续超时，优先检查服务器、CDN、首屏资源和第三方脚本。",
        base_url,
        value={"samples_seconds": response_samples, "median_seconds": median_response},
    ))
    findings.append(unknown_finding(
        "T2",
        "未取得 PageSpeed/Search Console 移动端字段数据或本地实验室性能数据。",
        "先用浏览器读取 PageSpeed；遇到 429 时经授权查看 Search Console，或运行 Lighthouse 并标记 lab_only。",
    ))

    if landing_url and args.expected_product:
        landing_page = next((page for page in pages if urldefrag(page["url"])[0] == urldefrag(landing_url)[0]), None)
        if not landing_page:
            t3_status, t3_evidence = "fail", "指定落地页未进入抽样或无法读取。"
        else:
            haystack = " ".join([landing_page["title"], " ".join(landing_page["h1"]), landing_page["visible_text"][:6000]]).casefold()
            expected = args.expected_product.casefold()
            expected_found = expected in haystack
            t3_status = "warn" if expected_found else "fail"
            t3_evidence = (
                f"公开页面初筛：预期商品“{args.expected_product}”"
                f"{'出现在' if expected_found else '未出现在'}落地页 Title/H1/主要文本中；"
                "尚未核对当前广告、优惠、市场与首屏 CTA。"
            )
        findings.append(make_finding(
            "T3",
            t3_status,
            t3_evidence,
            "经授权读取当前广告或导入广告证据，核对商品、优惠、市场、最终 URL 和首屏 CTA。",
            landing_url,
        ))
    else:
        findings.append(unknown_finding("T3", "未同时提供广告落地页和预期商品。", "提供落地页 URL 与广告商品/承诺后复测。"))

    trust_pages = [page for page in (product_pages or core_pages) if page["ok"]]
    trust_text = " ".join(page["visible_text"] for page in trust_pages)
    has_reviews = contains_any(trust_text, REVIEW_PATTERNS)
    has_shipping = contains_any(trust_text, SHIPPING_PATTERNS)
    has_returns = contains_any(trust_text, RETURN_PATTERNS)
    trust_count = sum([has_reviews, has_shipping or has_returns])
    if not trust_pages:
        t4_status = "unknown"
    else:
        t4_status = "pass" if trust_count == 2 else ("warn" if trust_count == 1 else "fail")
    findings.append(make_finding(
        "T4", t4_status,
        f"评价信号：{'有' if has_reviews else '未识别'}；物流/退换信号：{'有' if has_shipping or has_returns else '未识别'}。",
        "在商品页靠近购买决策区域提供真实评价、配送时效和退换说明。",
        (product_pages or core_pages or [{"url": base_url}])[0]["url"],
    ))
    findings.extend([
        unknown_finding("T5", "静态 HTML 不能确认手机首屏内容和 CTA 位置。", "用手机视口截图确认首屏直接呈现广告商品、价格和 CTA。"),
        unknown_finding(
            "T6",
            "公开页面不能证明弃购自动化已启用或近期成功运行。",
            "经授权在真实浏览器中只读查看自动化配置和最近 Run；触发测试消息需逐项二次确认。",
        ),
    ])

    titles = [clean_text(page["title"]) for page in core_pages if page["ok"]]
    default_titles = {"", "home", "homepage", "untitled", "my store", "shop"}
    good_titles = [title for title in titles if title.casefold() not in default_titles]
    title_duplicates = len(good_titles) - len({title.casefold() for title in good_titles})
    if not titles:
        s1_status = "unknown" if public_fetch_blocked else "fail"
    elif len(good_titles) == len(titles) and title_duplicates == 0:
        s1_status = "pass"
    elif good_titles:
        s1_status = "warn"
    else:
        s1_status = "fail"
    findings.append(make_finding(
        "S1", s1_status,
        f"核心页 {len(good_titles)}/{len(titles)} 个 Title 非空且非常见默认值；重复 {title_duplicates} 个。",
        "为首页、分类页和商品页设置描述性、简洁且基本唯一的 Title。",
        base_url,
    ))

    descriptions = [clean_text(page["meta_description"]) for page in core_pages if page["ok"]]
    good_desc = [item for item in descriptions if len(item) >= 20]
    desc_duplicates = len(good_desc) - len({item.casefold() for item in good_desc})
    if not descriptions:
        s2_status = "unknown" if public_fetch_blocked else "fail"
    elif not good_desc:
        s2_status = "fail"
    elif len(good_desc) == len(descriptions) and desc_duplicates == 0:
        s2_status = "pass"
    else:
        s2_status = "warn"
    findings.append(make_finding(
        "S2", s2_status,
        f"核心页 {len(good_desc)}/{len(descriptions)} 个 Meta Description 至少 20 字符；重复 {desc_duplicates} 个。",
        "为核心页面提供与页面内容一致、可读且基本唯一的 Meta Description。",
        base_url,
    ))

    image_items = [image for page in product_pages or core_pages for image in page["images"] if image.get("src")]
    generic_count = sum(generic_image_filename(urljoin(base_url, image["src"])) for image in image_items)
    missing_alt = sum(not clean_text(image.get("alt", "")) for image in image_items)
    if not image_items:
        s3_status = "unknown"
    else:
        generic_ratio = generic_count / len(image_items)
        missing_ratio = missing_alt / len(image_items)
        if generic_ratio <= 0.2 and missing_ratio <= 0.3:
            s3_status = "pass"
        elif generic_ratio <= 0.5 and missing_ratio <= 0.6:
            s3_status = "warn"
        else:
            s3_status = "fail"
    findings.append(make_finding(
        "S3", s3_status,
        f"抽样图片 {len(image_items)} 张；疑似随机/默认文件名 {generic_count}；缺少 Alt {missing_alt}。",
        "优先修复核心商品图片：使用可读文件名，并提供准确 Alt；装饰图可使用空 Alt。",
        (product_pages or core_pages or [{"url": base_url}])[0]["url"],
    ))

    if sitemap_result:
        findings.append(make_finding("S4", "pass", f"发现可读取 Sitemap：{sitemap_result['final_url']}，解析到 {len(sitemap_urls)} 个 URL。", "继续在 Search Console 中确认提交和处理状态。", sitemap_result["final_url"]))
    else:
        findings.append(make_finding("S4", "fail", "robots.txt 与常见路径均未发现可读取 Sitemap。", "生成站点地图，在 robots.txt 声明并提交至 Search Console。", robots_url))

    indexable = [page for page in accessible_core if "noindex" not in page["robots_meta"].lower()]
    canonical_count = sum(bool(page["canonical"]) for page in accessible_core)
    if not accessible_core:
        s5_status = "unknown"
    elif len(indexable) == len(accessible_core) and canonical_count >= max(1, round(len(accessible_core) * 0.8)):
        s5_status = "pass"
    elif indexable:
        s5_status = "warn"
    else:
        s5_status = "fail"
    findings.append(make_finding(
        "S5", s5_status,
        f"可读取核心页可索引 {len(indexable)}/{len(accessible_core)}；Canonical {canonical_count}/{len(accessible_core)}。",
        "移除核心页意外 noindex，并为可索引核心页设置自引用或正确 Canonical。",
        base_url,
    ))

    product_schema_count = sum(page["has_product_schema"] for page in product_pages)
    if not product_pages:
        s6_status = "unknown"
    elif product_schema_count == len(product_pages):
        s6_status = "pass"
    elif product_schema_count:
        s6_status = "warn"
    else:
        s6_status = "fail"
    findings.append(make_finding(
        "S6", s6_status,
        f"商品页 {product_schema_count}/{len(product_pages)} 个识别到 Product JSON-LD。",
        "按 Google Product/Merchant listing 要求补充并验证 Product 与 Offer 结构化数据。",
        (product_pages or [{"url": base_url}])[0]["url"],
    ))
    findings.append(unknown_finding(
        "S7",
        "公开验证标签不能证明当前 Search Console Property 仍可访问。",
        "让用户在真实浏览器中手动登录，只读核对 Property、Sitemap、效果、索引和 Core Web Vitals。",
    ))

    viewport_count = sum(bool(page["viewport"]) for page in accessible_core)
    if accessible_core and viewport_count == len(accessible_core):
        u1_status = "pass"
    elif viewport_count:
        u1_status = "warn"
    elif not accessible_core:
        u1_status = "unknown"
    else:
        u1_status = "fail"
    findings.append(make_finding(
        "U1", u1_status,
        f"可读取核心页 {viewport_count}/{len(accessible_core)} 个声明 viewport。",
        "为所有核心页面设置适合响应式布局的 viewport meta。",
        base_url,
    ))
    findings.append(unknown_finding("U2", "静态 HTML 不能判断实际布局、溢出和遮挡。", "用 390×844 手机视口检查首页、商品页、购物车和 Checkout。"))

    broken_links = [item for item in link_results if not item["ok"]]
    broken_images = [item for item in image_results if not item["ok"]]
    if not link_results and not image_results:
        u3_status = "unknown"
    elif not broken_links and not broken_images:
        u3_status = "pass"
    elif len(broken_links) + len(broken_images) <= 2:
        u3_status = "warn"
    else:
        u3_status = "fail"
    u3_source = (broken_links + broken_images)[0]["url"] if broken_links or broken_images else base_url
    findings.append(make_finding(
        "U3", u3_status,
        f"抽样链接 {len(link_results)} 个，失败 {len(broken_links)}；抽样图片 {len(image_results)} 张，失败 {len(broken_images)}。",
        "修复关键 4xx/5xx 链接、重定向循环和破图，再按同一 URL 清单复测。",
        u3_source,
        value={"broken_links": broken_links[:20], "broken_images": broken_images[:20]},
    ))

    shipping_ok = bool(policy_hits.get("shipping"))
    returns_ok = bool(policy_hits.get("returns"))
    if not any(page["ok"] and page["visible_text"] for page in pages):
        u4_status = "unknown"
    elif shipping_ok and returns_ok:
        u4_status = "pass"
    elif shipping_ok or returns_ok:
        u4_status = "warn"
    else:
        u4_status = "fail"
    findings.append(make_finding(
        "U4", u4_status,
        f"物流政策：{'发现' if shipping_ok else '未发现'}；退换/退款政策：{'发现' if returns_ok else '未发现'}。",
        "提供可独立打开的 Shipping 与 Returns/Refund 页面，并在页脚和购买路径中可发现。",
        (policy_hits.get("shipping") or policy_hits.get("returns") or [base_url])[0],
    ))

    if not any(page["ok"] and page["visible_text"] for page in pages):
        u5_status = "unknown"
    elif contact_hits:
        u5_status = "pass"
    elif contains_any(" ".join(page["visible_text"] for page in pages), POLICY_PATTERNS["contact"]):
        u5_status = "warn"
    else:
        u5_status = "fail"
    if u5_status == "pass":
        u5_evidence = "发现可识别的联系/支持入口。"
    elif u5_status == "warn":
        u5_evidence = "识别到联系/支持文本，但未确认独立入口。"
    elif u5_status == "fail":
        u5_evidence = "未发现联系/支持入口。"
    else:
        u5_evidence = "公开页面读取受阻，未能验证联系/支持入口。"
    findings.append(make_finding(
        "U5", u5_status,
        u5_evidence,
        "在页头或页脚提供可访问的 Contact/Support 页面和明确客服方式。",
        (contact_hits or [base_url])[0],
    ))

    enhanced_payload = load_enhanced_evidence(args.evidence_json)
    enhanced = enhanced_payload["checks"]
    findings = apply_enhanced(findings, enhanced)
    score = score_findings(findings)
    verdict = determine_verdict(findings, score)
    evidence_session = enhanced_payload["session"]
    authorization = evidence_session.get("authorization")
    safety = {
        "authorized_browser": authorization in {"browser-authorized-readonly", "authorized-side-effect"},
        "submitted_forms": False,
        "created_account": False,
        "generated_abandoned_checkout": False,
        "triggered_messages": False,
        "submitted_order": False,
    }
    safety.update(evidence_session.get("safety", {}))
    if not enhanced:
        mode = "public-readonly"
    elif authorization == "browser-authorized-readonly":
        mode = "public+browser-authorized-readonly"
    elif authorization == "authorized-side-effect":
        mode = "public+authorized-side-effect"
    elif authorization == "user-provided":
        mode = "public+user-provided-evidence"
    else:
        mode = "public+enhanced"

    return {
        "audit_version": VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "target": {
            "requested_url": start_url,
            "final_url": base_url,
            "landing_url": landing_url,
            "expected_product": args.expected_product,
        },
        "mode": mode,
        "evidence_session": evidence_session if enhanced else None,
        "safety": safety,
        "crawl": {
            "selected_pages": len(pages),
            "discovered_urls": len(discovered),
            "sitemap_url": sitemap_result["final_url"] if sitemap_result else None,
            "robots_url": robots_url,
            "pages": [
                {key: value for key, value in page.items() if key not in {"links", "images", "visible_text", "controls"}}
                for page in pages
            ],
            "link_results": link_results,
            "image_results": image_results,
        },
        "findings": findings,
        "score": score,
        "verdict": verdict,
        "limits": [
            "公开请求中位数不是 LCP 或真实用户字段数据。",
            "静态 HTML 不能确认首屏显著性、实际移动端布局、Guest Checkout 或支付可用性。",
            "Sitemap 可访问不等于已提交 Search Console。",
            "增强证据来自浏览器或用户导入时，以证据中记录的授权模式、时间和安全状态为准。",
            "本 Skill 不创建账户或提交订单。",
        ],
    }


def score_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    factors = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
    earned = 0.0
    known_weight = 0.0
    category_scores: dict[str, dict[str, float]] = {
        key: {"earned": 0.0, "known_weight": 0.0, "total_weight": float(value["weight"])}
        for key, value in CATEGORIES.items()
    }
    for item in findings:
        if item["status"] == "unknown":
            continue
        weight = float(item["weight"])
        item_earned = weight * factors[item["status"]]
        earned += item_earned
        known_weight += weight
        category_scores[item["category"]]["earned"] += item_earned
        category_scores[item["category"]]["known_weight"] += weight
    unknown_weight = 100.0 - known_weight
    return {
        "verified_score": round((earned / known_weight * 100) if known_weight else 0, 1),
        "coverage_percent": round(known_weight, 1),
        "earned_points": round(earned, 1),
        "strict_lower_bound": round(earned, 1),
        "potential_upper_bound": round(earned + unknown_weight, 1),
        "unknown_weight": round(unknown_weight, 1),
        "categories": category_scores,
    }


def determine_verdict(findings: list[dict[str, Any]], score: dict[str, Any]) -> str:
    p0_fail = any(item["priority"] == "P0" and item["status"] == "fail" for item in findings)
    if p0_fail:
        return "不合格"
    if score["coverage_percent"] < 70:
        return "部分诊断，不能最终判定"
    if score["verified_score"] >= 80:
        return "合格"
    if score["verified_score"] >= 60:
        return "待整改"
    return "不合格"


def escape_table(value: Any) -> str:
    return clean_text(str(value)).replace("|", "\\|")


def render_report(result: dict[str, Any]) -> str:
    score = result["score"]
    findings = result["findings"]
    safety = result["safety"]
    issues = [item for item in findings if item["status"] in {"fail", "warn"}]
    issues.sort(key=lambda item: ({"P0": 0, "P1": 1, "P2": 2}[item["priority"]], 0 if item["status"] == "fail" else 1, item["id"]))
    unknowns = [item for item in findings if item["status"] == "unknown"]
    p0_count = sum(item["priority"] == "P0" and item["status"] == "fail" for item in findings)
    mode_note = "包含经授权的测试副作用" if result["mode"].endswith("authorized-side-effect") else "未执行外部副作用"

    lines = [
        "# 独立站合格标准诊断报告",
        "",
        f"> 审计对象：{result['target']['final_url']}  ",
        f"> 审计时间：{result['generated_at']}  ",
        f"> 模式：{result['mode']}（{mode_note}）",
        "",
        "## 结论",
        "",
        f"- 判定：**{result['verdict']}**",
        f"- 已验证评分：**{score['verified_score']}/100**",
        f"- 检测覆盖率：**{score['coverage_percent']}%**",
        f"- 严格下限—潜在上限：**{score['strict_lower_bound']}–{score['potential_upper_bound']}**",
        f"- P0 失败：**{p0_count} 项**",
        "",
        "已验证评分只对已有证据的检查项计算；覆盖率低于 70% 时不做最终合格判断。",
        "",
        "## 老板先看",
        "",
    ]
    if issues:
        for index, item in enumerate(issues[:5], 1):
            lines.append(f"{index}. **{item['priority']} · {item['label']}**：{item['evidence']} 建议：{item['recommendation']}")
    else:
        lines.append("1. 当前已验证项没有发现失败或警告；继续补齐未知项。")

    lines.extend([
        "",
        "## 四模块结果",
        "",
        "| 模块 | 已得分 | 已验证权重 | 模块总权重 |",
        "|---|---:|---:|---:|",
    ])
    for key, category in CATEGORIES.items():
        item = score["categories"][key]
        lines.append(f"| {category['label']} | {item['earned']:.1f} | {item['known_weight']:.1f} | {item['total_weight']:.0f} |")

    lines.extend([
        "",
        "## P0/P1/P2 问题",
        "",
        "| 优先级 | ID | 状态 | 检查项 | 证据 | 建议 |",
        "|---|---|---|---|---|---|",
    ])
    if issues:
        for item in issues:
            lines.append(
                f"| {item['priority']} | {item['id']} | {item['status']} | "
                f"{escape_table(item['label'])} | {escape_table(item['evidence'])} | "
                f"{escape_table(item['recommendation'])} |"
            )
    else:
        lines.append("| — | — | — | 未发现 | — | — |")

    lines.extend([
        "",
        "## 全部检查项",
        "",
        "| 模块 | ID | 权重 | 状态 | 证据来源 | 检查项 |",
        "|---|---|---:|---|---|---|",
    ])
    for item in findings:
        lines.append(
            f"| {CATEGORIES[item['category']]['label']} | {item['id']} | {item['weight']} | "
            f"{item['status']} | {item['automation']} | {escape_table(item['label'])} |"
        )

    lines.extend([
        "",
        "## 未验证项",
        "",
        "| ID | 检查项 | 原因 | 补证方式 |",
        "|---|---|---|---|",
    ])
    if unknowns:
        for item in unknowns:
            lines.append(
                f"| {item['id']} | {escape_table(item['label'])} | "
                f"{escape_table(item['evidence'])} | {escape_table(item['recommendation'])} |"
            )
    else:
        lines.append("| — | 已全部覆盖 | — | — |")

    lines.extend([
        "",
        "## 数据边界",
        "",
    ])
    for limit in result["limits"]:
        lines.append(f"- {limit}")
    lines.extend([
        "",
        "## 安全记录",
        "",
        "| 行为 | 是否发生 |",
        "|---|---|",
        f"| 后台授权浏览 | {'是' if safety['authorized_browser'] else '否'} |",
        f"| 提交测试表单 | {'是' if safety['submitted_forms'] else '否'} |",
        f"| 生成弃购记录 | {'是' if safety['generated_abandoned_checkout'] else '否'} |",
        f"| 触发邮件或短信 | {'是' if safety['triggered_messages'] else '否'} |",
        f"| 创建账户 | {'是' if safety['created_account'] else '否'} |",
        f"| 提交订单 | {'是' if safety['submitted_order'] else '否'} |",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读自动诊断 DTC/电商独立站基础合格标准")
    parser.add_argument("--url", required=True, help="独立站首页 URL")
    parser.add_argument("--out-dir", required=True, type=Path, help="输出目录")
    parser.add_argument("--landing-url", help="可选：广告落地页 URL")
    parser.add_argument("--expected-product", help="可选：广告承诺或预期商品名称")
    parser.add_argument("--evidence-json", type=Path, help="可选：浏览器或后台增强证据 JSON")
    parser.add_argument("--max-pages", type=int, default=12, help="最多抓取 HTML 页面数，默认 12")
    parser.add_argument("--max-links", type=int, default=40, help="最多抽样内部链接数，默认 40")
    parser.add_argument("--max-images", type=int, default=30, help="最多抽样图片数，默认 30")
    parser.add_argument("--repeats", type=int, default=3, help="首页响应时间样本数，默认 3")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数，默认 15")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_pages < 1 or args.max_links < 0 or args.max_images < 0 or args.repeats < 1:
        print("参数错误：max-pages/repeats 必须大于 0，max-links/max-images 不能小于 0。", file=sys.stderr)
        return 2
    try:
        result = audit(args)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        json_path = args.out_dir / "audit.json"
        report_path = args.out_dir / "report.md"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(render_report(result), encoding="utf-8")
        print(json.dumps({
            "verdict": result["verdict"],
            "verified_score": result["score"]["verified_score"],
            "coverage_percent": result["score"]["coverage_percent"],
            "json": str(json_path.resolve()),
            "report": str(report_path.resolve()),
        }, ensure_ascii=False))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"审计失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
