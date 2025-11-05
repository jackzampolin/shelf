from pydantic import BaseModel, Field


class PageRange(BaseModel):
    start_page: int = Field(..., ge=1, description="First page number (inclusive)")
    end_page: int = Field(..., ge=1, description="Last page number (inclusive)")

    def __len__(self) -> int:
        return self.end_page - self.start_page + 1

    def contains(self, page_num: int) -> bool:
        return self.start_page <= page_num <= self.end_page
