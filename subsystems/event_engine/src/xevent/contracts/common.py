"""PIT 是 X 的领域约束；类型解析和 JSON Schema 由 Pydantic 提供。"""
from datetime import datetime, timezone
from typing import Annotated, Literal, TypeVar

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict,
    Field, TypeAdapter, model_validator,
)

Text = Annotated[str, Field(min_length=1, pattern=r"\S", description="非空文本，保留原值")]
Code6 = Annotated[str, Field(pattern=r"^[0-9]{6}$", description="六位代码文本，保留前导零；不负责证券身份映射")]
PositiveInt = Annotated[int, Field(gt=0)]
Count = Annotated[int, Field(ge=0)]
Ratio = Annotated[float, Field(ge=0, le=1)]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256十六进制摘要；不代表内容真实")]
T = TypeVar("T")
Items = Annotated[tuple[T, ...], Field(strict=False)]
Mode = Literal["LIVE_FORWARD", "OBSERVED_REPLAY", "PUBLIC_PIT_RESEARCH"]
Band = Literal["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "UNKNOWN"]
ClaimKind = Literal["FACT", "INTENT", "FORECAST", "OPINION", "RUMOR", "NARRATIVE"]


def _aware_input(value):
    if not isinstance(value, (str, datetime)) or (isinstance(value, str) and "T" not in value):
        raise ValueError("TIME_INVALID：必须是带时区的RFC3339时间或datetime，禁止数值时间戳")
    return TypeAdapter(AwareDatetime).validate_python(value)


UTCDateTime = Annotated[
    AwareDatetime, BeforeValidator(_aware_input),
    AfterValidator(lambda v: v.astimezone(timezone.utc)),
    Field(description="必须带时区；内部规范为UTC；拒绝naive时间"),
]


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


class VersionRef(Contract):
    object_id: Text = Field(description="引用的稳定对象ID；不得使用动态latest")
    version: PositiveInt = Field(description="引用的具体正整数版本")


class InputVersionRef(VersionRef):
    available_at: UTCDateTime
    research_available_at: UTCDateTime | None = None


class PublicPIT(Contract):
    public_available_at: UTCDateTime
    research_available_at: UTCDateTime
    availability_proof: Text = Field(description="不可变历史版本及公开时间的证据定位；不是主观推测")
    simulated_latency_seconds: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def time_gate(self):
        if (self.research_available_at - self.public_available_at).total_seconds() < self.simulated_latency_seconds:
            raise ValueError("PIT_PUBLIC_TIME：模拟可用时间不得早于公开时间加模拟延迟")
        return self


class PITQuery(Contract):
    as_of: UTCDateTime
    mode: Mode
    effective_at: UTCDateTime | None = None


class PITError(ValueError):
    """调用者必须处理；不能把不可见对象继续送入研究。"""


class VersionEnvelope(Contract):
    object_id: Text
    version: PositiveInt
    schema_version: Literal["X_EVENT_V0.1"] = "X_EVENT_V0.1"
    recorded_at: UTCDateTime = Field(description="该版本成功耐久化提交完成时间；Phase1仅校验fixture声明")
    available_at: UTCDateTime = Field(description="正式研究可用时间，不早于提交及输入门槛")
    effective_from: UTCDateTime | None = None
    effective_to: UTCDateTime | None = None
    supersedes_version: PositiveInt | None = None
    evidence_refs: Items[VersionRef] = ()
    input_version_refs: Items[InputVersionRef] = ()
    run_id: Text
    policy_version: Text
    status: Literal["READY", "DEGRADED", "HOLD", "QUARANTINED"] = "READY"
    reason_codes: Items[Text] = ()
    content_hash: SHA256
    mode: Mode = "LIVE_FORWARD"
    public_pit: PublicPIT | None = None

    @model_validator(mode="after")
    def envelope_gate(self):
        if self.available_at < self.recorded_at:
            raise ValueError("PIT_RECORDED：available_at不得早于耐久化提交完成时间")
        if self.effective_to is not None and (self.effective_from is None or self.effective_to <= self.effective_from):
            raise ValueError("EFFECTIVE_INTERVAL：有效区间必须左闭右开且结束晚于开始")
        if self.supersedes_version is not None and self.supersedes_version >= self.version:
            raise ValueError("VERSION_ORDER：被替代版本必须早于本版本")
        declared = {(r.object_id, r.version) for r in self.input_version_refs}
        if any((r.object_id, r.version) not in declared for r in self.evidence_refs):
            raise ValueError("PIT_REFERENCE：证据引用必须声明输入版本及可用时间")
        if self.status in ("HOLD", "QUARANTINED", "DEGRADED") and not self.reason_codes:
            raise ValueError("STATUS_REASON：暂停、隔离或降级必须记录原因")
        if (self.mode == "PUBLIC_PIT_RESEARCH") != (self.public_pit is not None):
            raise ValueError("PIT_MODE：公共历史研究必须携带证明，实盘/观测回放不得携带模拟时间")
        for ref in self.input_version_refs:
            if ref.available_at > self.available_at:
                raise ValueError("PIT_INPUT：输入尚不可用")
            if self.public_pit and (ref.research_available_at is None or ref.research_available_at > self.public_pit.research_available_at):
                raise ValueError("PIT_PUBLIC_INPUT：公共研究输入缺少合格模拟可用时间")
            if not self.public_pit and ref.research_available_at is not None:
                raise ValueError("PIT_MODE：不得把模拟输入混入实盘/观测回放")
        return self

    def is_visible(self, query: PITQuery) -> bool:
        public = query.mode == "PUBLIC_PIT_RESEARCH"
        if public != (self.mode == "PUBLIC_PIT_RESEARCH"):
            raise PITError("PIT_MODE：公共历史研究与实盘/观测回放隔离")
        if query.mode == "LIVE_FORWARD" and self.mode != "LIVE_FORWARD":
            raise PITError("PIT_MODE：回放结果不能冒充实盘产出")
        timestamp = self.public_pit.research_available_at if public else self.available_at
        when = query.effective_at or query.as_of
        return (
            self.status in ("READY", "DEGRADED") and timestamp <= query.as_of
            and (self.effective_from is None or self.effective_from <= when)
            and (self.effective_to is None or when < self.effective_to)
        )

    def require_visible(self, query: PITQuery) -> None:
        if not self.is_visible(query):
            raise PITError("PIT_NOT_VISIBLE：截止时点不可知、未就绪或不在现实有效区间")


class DerivedEnvelope(VersionEnvelope):
    computed_at: UTCDateTime = Field(description="派生结果实际完成时间；不能用研究开始时间替代")
    research_computed_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def derived_gate(self):
        latest_input = max((r.available_at for r in self.input_version_refs), default=self.computed_at)
        if self.computed_at < latest_input or self.available_at < max(latest_input, self.computed_at, self.recorded_at):
            raise ValueError("PIT_DERIVED：派生可用时间必须覆盖输入、计算完成与提交时间")
        if self.public_pit:
            if self.research_computed_at is None or self.research_computed_at > self.public_pit.research_available_at:
                raise ValueError("PIT_PUBLIC_COMPUTE：必须记录模拟计算完成时间")
            if any(r.research_available_at > self.research_computed_at for r in self.input_version_refs):
                raise ValueError("PIT_PUBLIC_COMPUTE：模拟计算不能早于输入")
        elif self.research_computed_at is not None:
            raise ValueError("PIT_MODE：实盘不能带模拟计算时间")
        return self


class ObservationWindow(Contract):
    start: UTCDateTime
    end: UTCDateTime

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("WINDOW_ORDER：观察窗结束必须晚于开始")
        return self


class SampleStatistic(Contract):
    numerator: Count
    denominator: Count
    outcome_available_at: UTCDateTime = Field(description="这些统计结果最晚何时可知，禁止未来结果回填")
    rate: Ratio | None = None
    missing_reason: Text | None = None

    @model_validator(mode="after")
    def count_gate(self):
        if self.numerator > self.denominator:
            raise ValueError("STAT_COUNT：分子不能超过分母")
        if self.denominator == 0:
            if self.rate is not None or self.missing_reason is None:
                raise ValueError("STAT_UNKNOWN：零样本率必须null并说明原因")
        elif self.rate is not None and abs(self.rate - self.numerator / self.denominator) > 1e-9:
            raise ValueError("STAT_RATE：率与分子分母不一致")
        if self.rate is None and self.missing_reason is None:
            raise ValueError("STAT_UNKNOWN：未知率必须说明原因")
        return self
