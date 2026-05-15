from abc import ABC, abstractmethod

from ..models.results import TestResult


class BasePerformer(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.context: dict = {}

    @abstractmethod
    def run(self, test_case: dict) -> TestResult: ...

    def setup(self) -> None:
        pass

    def teardown(self) -> None:
        pass
