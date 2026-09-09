"""未来数据适配器只能提交结构化观察；本Phase没有网络实现。"""
from typing import Protocol, Iterable
from .contracts import MarketObservation

class MarketDataAdapter(Protocol):
    def observations(self) -> Iterable[MarketObservation]:
        """返回保留provider时间、接收时间、单位和固定引用的观察；不作定价分析。"""
        ...