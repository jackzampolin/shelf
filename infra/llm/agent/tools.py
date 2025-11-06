from abc import ABC, abstractmethod
from typing import List, Dict


class AgentTools(ABC):

    @abstractmethod
    def get_tools(self) -> List[Dict]:
        pass

    @abstractmethod
    def execute_tool(self, name: str, arguments: Dict) -> str:
        pass

    @abstractmethod
    def is_complete(self) -> bool:
        pass
