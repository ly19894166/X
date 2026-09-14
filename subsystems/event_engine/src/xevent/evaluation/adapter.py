"""Future import contract only. No sockets, provider implementation or broker."""
from typing import Protocol, Iterable
from .contracts import OutcomeQuote


class MarketOutcomeAdapter(Protocol):
    def observations(self) -> Iterable[OutcomeQuote]:
        """Return separately qualified, timestamped fixed-version observation archives."""
        ...
