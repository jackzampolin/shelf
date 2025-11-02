from typing import Dict, List, Any

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


class BaseStage:
    name: str = None
    dependencies: List[str] = []

    def get_status(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[Any, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_status() method: the progress to completion"
        )

    def before(self, storage: BookStorage, logger: PipelineLogger) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement before() method: check the dependancy stage(s) status is complete"
        )

    def run(
        self,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run() method: the thing that this stage does"
        )
