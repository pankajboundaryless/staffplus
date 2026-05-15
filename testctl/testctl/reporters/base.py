from abc import ABC, abstractmethod

from ..models.results import RunResult


class BaseReporter(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def send(self, run: RunResult) -> None: ...
