"""授权先于每次HTTP请求；不跟随跳转，不访问feedparser解析出的URL。"""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import math

import feedparser
import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

from ..contracts.common import PITQuery
from ..contracts.models import Source
from ..ledger.contracts import RawObservation
from ..ledger.store import digest, ref, utcnow


class AuthorizationHold(ValueError):
    pass


class SourceUnavailable(ValueError):
    pass


class TemporaryFailure(Exception):
    def __init__(self, message, wait_seconds):
        super().__init__(message)
        self.wait_seconds = wait_seconds


def authorization_gate(source: Source, now, purpose="EVENT_RESEARCH"):
    if (not source.enabled or source.authorization_status not in ("AUTHORIZED", "NOT_REQUIRED")
            or source.terms_status != "REVIEWED" or purpose not in (source.allowed_uses or ())
            or source.raw_retention_allowed is not True):
        raise AuthorizationHold("AUTHORIZATION_HOLD：来源未明确允许当前用途及原文留存")
    source.require_visible(PITQuery(as_of=now, mode="LIVE_FORWARD"))
    if source.access_restrictions:
        raise AuthorizationHold("AUTHORIZATION_HOLD：配置有限制，最小Adapter不自动解释，需先完成适用性审核")


@dataclass(frozen=True)
class AdapterResult:
    observation: RawObservation | None
    entries: tuple
    etag: str | None
    last_modified: str | None
    received_at: object
    not_modified: bool = False


class HTTPAdapter:
    def __init__(self, *, transport=None, clock=utcnow, sleep=None, attempts=3, max_wait=5.0, max_bytes=1048576):
        if not 1 <= attempts <= 3 or not 0 <= max_wait <= 30 or max_bytes <= 0:
            raise ValueError("ADAPTER_LIMIT：请求/重试必须有界")
        self.clock, self.attempts, self.max_wait, self.max_bytes = clock, attempts, max_wait, max_bytes
        self.sleep = sleep
        self.client = httpx.Client(transport=transport, timeout=httpx.Timeout(10, connect=5), follow_redirects=False,
                                   trust_env=False, headers={"User-Agent": "X-Event-Engine/0.1 (manual research; bounded collector)"})

    def close(self):
        self.client.close()

    def _delay(self, response):
        raw = response.headers.get("Retry-After")
        if not raw:
            return min(1.0, self.max_wait)
        try:
            seconds = float(raw)
        except ValueError:
            try:
                date = parsedate_to_datetime(raw)
                if date.tzinfo is None:
                    raise ValueError("naive retry time")
                seconds = (date - self.clock()).total_seconds()
            except (ValueError, TypeError, OverflowError):
                raise SourceUnavailable("RETRY_AFTER_INVALID：服务端等待时间无法验证")
        if not math.isfinite(seconds):
            raise SourceUnavailable("RETRY_AFTER_INVALID：等待时间不是有限数值")
        if seconds > self.max_wait:
            # 不把长Retry-After截短后提前重试；留给后续人工/调度任务。
            raise SourceUnavailable("RETRY_AFTER_HOLD：服务端要求等待超过本轮上限")
        return max(0.0, seconds)

    def fetch(self, source, *, etag=None, last_modified=None, rss=False, change_type="INITIAL"):
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        kwargs = dict(stop=stop_after_attempt(self.attempts), retry=retry_if_exception_type(TemporaryFailure),
                      wait=lambda state: state.outcome.exception().wait_seconds, reraise=True)
        if self.sleep is not None:
            kwargs["sleep"] = self.sleep
        try:
            for attempt in Retrying(**kwargs):
                with attempt:
                    authorization_gate(source, self.clock())
                    try:
                        with self.client.stream("GET", source.canonical_locator, headers=headers) as response:
                            first_seen = self.clock()
                            status = response.status_code
                            if status == 429 or status in (500, 502, 503, 504):
                                raise TemporaryFailure(f"HTTP_{status}", self._delay(response))
                            if status == 304:
                                if not headers:
                                    raise SourceUnavailable("HTTP_304：无条件请求不能复用未知响应")
                                return AdapterResult(None, (), response.headers.get("etag") or etag,
                                                     response.headers.get("last-modified") or last_modified, self.clock(), True)
                            if not 200 <= status < 300:
                                raise SourceUnavailable(f"HTTP_{status}：永久错误/跳转，不重试")
                            parts, size = [], 0
                            for part in response.iter_bytes():
                                size += len(part)
                                if size > self.max_bytes:
                                    raise SourceUnavailable("RESPONSE_TOO_LARGE：响应超过本轮上限")
                                parts.append(part)
                            raw = b"".join(parts)
                            collected = self.clock()
                            entries = ()
                            if rss:
                                parsed = feedparser.parse(raw)  # 只传bytes，禁止feedparser自行联网
                                if parsed.bozo or not parsed.version:
                                    raise SourceUnavailable("RSS_INVALID：解析失败，保留失败健康状态")
                                entries = tuple(dict(id=e.get("id"), link=e.get("link"), title=e.get("title"),
                                                     published_raw=e.get("published")) for e in parsed.entries)
                            # 保存HTTP原始响应；RSS条目只作解析输出，不自动把每条映射成事件。
                            observation = RawObservation(source_ref=ref(source), locator=source.canonical_locator, raw=raw,
                                        first_seen_at=first_seen, collected_at=collected, published_at=None,
                                        content_version=digest(raw), change_type=change_type)
                            return AdapterResult(observation, entries, response.headers.get("etag"),
                                                 response.headers.get("last-modified"), collected)
                    except (httpx.TimeoutException, httpx.NetworkError) as exc:
                        raise TemporaryFailure(type(exc).__name__, min(1.0, self.max_wait)) from exc
                    except httpx.RequestError as exc:
                        raise SourceUnavailable(f"SOURCE_UNAVAILABLE：{type(exc).__name__}") from exc
        except TemporaryFailure as exc:
            raise SourceUnavailable(f"SOURCE_UNAVAILABLE：有界重试耗尽：{exc}") from exc
