"""冻结的 Phase 1 公共契约。"""
from .common import VersionEnvelope
from .models import (
    Actor, ActorTopicProfile, EvidenceRelation, EvidenceVersion, EventDNA,
    EventVersion, NarrativeSourceProfile, Source, SourceTopicProfile, Statement,
)

SCHEMAS = {model.__name__: model for model in (
    VersionEnvelope, Source, SourceTopicProfile, NarrativeSourceProfile, Actor,
    ActorTopicProfile, Statement, EvidenceVersion, EvidenceRelation, EventVersion, EventDNA,
)}
__all__ = [*SCHEMAS, "SCHEMAS"]
