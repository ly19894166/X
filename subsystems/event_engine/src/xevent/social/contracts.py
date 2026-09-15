"""Strict social data and source-review contracts; no fact or ranking output."""
from typing import Literal

from pydantic import model_validator

from ..contracts.common import Contract, Count, DerivedEnvelope, SHA256, Text, UTCDateTime, VersionRef

Platform = Literal["BLUESKY", "HN", "MASTODON"]


class SourceQualification(Contract):
    source_name: Text
    platform: Platform
    endpoint: Text
    official_api_doc: Text
    access_method: Literal["ANONYMOUS_HTTP_GET"] = "ANONYMOUS_HTTP_GET"
    authentication_required: bool | None
    rate_limit_status: Text
    raw_retention_status: Literal["ALLOWED", "UNKNOWN", "DENIED"]
    redistribution_status: Text
    deletion_semantics: Text
    edit_semantics: Text
    reviewed_at: UTCDateTime
    qualification_status: Literal["QUALIFIED", "HOLD_SOURCE_AUTHORIZATION"]
    authorization_proof: Text

    @model_validator(mode="after")
    def authorization(self):
        if self.qualification_status == "QUALIFIED" and (
            self.authentication_required is not False or self.raw_retention_status != "ALLOWED"
        ):
            raise ValueError("HOLD_SOURCE_AUTHORIZATION")
        return self


class SocialContent(Contract):
    platform: Platform
    native_id: Text
    author_id: Text | None = None
    author_handle: Text | None = None
    author_display_name: str | None = None
    created_at: UTCDateTime | None = None
    title: str | None = None
    text: str | None = None
    canonical_url: Text | None = None
    original_url: Text | None = None
    language: Text | None = None
    reply_count: Count | None = None
    repost_count: Count | None = None
    like_count: Count | None = None
    score: int | None = None
    comment_count: Count | None = None
    is_reply: bool | None = None
    is_repost: bool | None = None
    is_quote: bool | None = None
    signal_class: Literal["SOCIAL_LEAD", "OFFICIAL_SOCIAL_STATEMENT", "COMMUNITY_DISCUSSION",
                          "TECH_SIGNAL", "RUMOR", "UNKNOWN"] = "SOCIAL_LEAD"
    deletion_state: Literal["NOT_REPORTED", "EXPLICIT_DELETED", "DELETED_OR_MISSING_UNKNOWN"] = "NOT_REPORTED"

    @model_validator(mode="after")
    def no_official_in_v01(self):
        if self.signal_class == "OFFICIAL_SOCIAL_STATEMENT":
            raise ValueError("AUTHOR_IDENTITY_QUALIFICATION_HOLD")
        return self


class SocialObservation(SocialContent, DerivedEnvelope):
    source_ref: VersionRef
    first_seen_at: UTCDateTime
    received_at: UTCDateTime
    raw_ref: Text
    response_locator: Text
    normalized_hash: SHA256
    lifecycle: Literal["NEW", "UPDATED", "DELETED_OR_MISSING_UNKNOWN"]
    investigation_status: Literal["EVENT_INVESTIGATION_REQUIRED"] = "EVENT_INVESTIGATION_REQUIRED"

    @model_validator(mode="after")
    def social_time(self):
        if not self.first_seen_at <= self.received_at <= self.computed_at <= self.available_at:
            raise ValueError("PIT_SOCIAL_TIME")
        return self
