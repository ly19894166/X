"""Bounded JSON parsing; preserve HTML and nullable fields without interpretation."""
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit

from ..adapters.http import SourceUnavailable
from .contracts import SocialContent


def endpoint_gate(platform, endpoint):
    u = urlsplit(endpoint)
    if u.scheme != "https" or u.username or u.password or u.fragment or u.port not in (None, 443):
        raise ValueError("SOCIAL_ENDPOINT_SCOPE")
    if platform == "BLUESKY":
        valid = u.netloc == "public.api.bsky.app" and u.path in (
            "/xrpc/app.bsky.feed.searchPosts", "/xrpc/app.bsky.feed.getAuthorFeed")
    elif platform == "HN":
        import re
        valid = u.netloc == "hacker-news.firebaseio.com" and bool(re.fullmatch(
            r"/v0/(newstories|updates|item/[0-9]+)\.json", u.path))
    else:
        valid = bool(u.hostname) and u.path == "/api/v1/timelines/public"
    if not valid:
        raise ValueError("SOCIAL_ENDPOINT_SCOPE")


def normalize(platform, raw, *, expected_id=None, instance=None):
    """Return content rows and provider-native cursor. Lists are discovery, not posts."""
    try:
        data = json.loads(raw)
        rows, cursor = [], None
        if platform == "HN":
            if isinstance(data, list) or isinstance(data, dict) and "items" in data:
                ids = data if isinstance(data, list) else data["items"]
                if not isinstance(ids, list) or any(type(i) is not int or i < 0 for i in ids):
                    raise ValueError("HN_IDS")
                return (), str(max(ids)) if ids else None
            if data is None:
                if expected_id is None:
                    raise ValueError("MISSING_ITEM_ID")
                rows = [SocialContent(platform=platform, native_id=expected_id,
                          deletion_state="DELETED_OR_MISSING_UNKNOWN")]
            else:
                if type(data["id"]) is not int or (expected_id and str(data["id"]) != expected_id):
                    raise ValueError("HN_ID")
                if data.get("type") not in (None, "story"):
                    raise ValueError("HN_STORIES_ONLY")
                if data.get("type") is None and data.get("deleted") is not True:
                    raise ValueError("HN_TYPE_MISSING")
                created = data.get("time")
                if created is not None and type(created) is not int:
                    raise ValueError("HN_TIME")
                rows = [SocialContent(platform=platform, native_id=str(data["id"]),
                    author_id=data.get("by"), author_handle=data.get("by"),
                    created_at=datetime.fromtimestamp(created, timezone.utc) if created is not None else None,
                    title=data.get("title"), text=data.get("text"), original_url=data.get("url"),
                    canonical_url=f'https://news.ycombinator.com/item?id={data["id"]}',
                    score=data.get("score"), comment_count=data.get("descendants"),
                    deletion_state="EXPLICIT_DELETED" if data.get("deleted") is True else "NOT_REPORTED")]
            cursor = rows[0].native_id
        elif platform == "BLUESKY":
            posts = data.get("posts")
            feed = data.get("feed")
            if posts is None:
                posts = [item["post"] for item in feed]
            if not isinstance(posts, list):
                raise ValueError("BLUESKY_POSTS")
            cursor = data.get("cursor")
            for p in posts:
                a, record = p["author"], p["record"]
                uri = p["uri"]
                if not isinstance(uri, str) or not uri.startswith("at://"):
                    raise ValueError("BLUESKY_URI")
                embed = p.get("embed", {})
                rows.append(SocialContent(platform=platform, native_id=uri,
                    author_id=a["did"], author_handle=a.get("handle"), author_display_name=a.get("displayName"),
                    created_at=record.get("createdAt"), text=record.get("text"),
                    canonical_url=f'https://bsky.app/profile/{a["did"]}/post/{uri.rsplit("/", 1)[-1]}',
                    original_url=embed.get("external", {}).get("uri"),
                    language=(record.get("langs") or [None])[0], reply_count=p.get("replyCount"),
                    repost_count=p.get("repostCount"), like_count=p.get("likeCount"),
                    is_reply=record.get("reply") is not None,
                    is_quote=True if "record" in embed else None))
        elif platform == "MASTODON":
            if not isinstance(data, list) or not instance:
                raise ValueError("MASTODON_ARRAY_INSTANCE")
            for p in data:
                a = p["account"]
                if p.get("visibility") != "public" or not p["id"].isdigit():
                    raise ValueError("MASTODON_PUBLIC_ONLY")
                rows.append(SocialContent(platform=platform, native_id=instance + ":" + p["id"],
                    author_id=instance + ":" + a["id"], author_handle=a.get("acct"),
                    author_display_name=a.get("display_name"), created_at=p.get("created_at"),
                    text=p.get("content"), canonical_url=p.get("url"), language=p.get("language"),
                    reply_count=p.get("replies_count"), repost_count=p.get("reblogs_count"),
                    like_count=p.get("favourites_count"), is_reply=p.get("in_reply_to_id") is not None,
                    is_repost=p.get("reblog") is not None))
            cursor = str(max(int(p["id"]) for p in data)) if data else None
        else:
            raise ValueError("PLATFORM")
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError("CURSOR_TYPE")
        keys = [r.native_id for r in rows]
        if len(set(keys)) != len(keys):
            raise ValueError("AMBIGUOUS_NATIVE_ID")
        return tuple(rows), cursor
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError) as exc:
        raise SourceUnavailable("SOCIAL_JSON_INVALID: " + type(exc).__name__) from exc
