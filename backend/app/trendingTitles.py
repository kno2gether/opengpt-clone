from typing import Optional, Type

from langchain_core.pydantic_v1 import BaseModel, Field
from langchain.callbacks.manager import CallbackManagerForToolRun
from langchain.tools.base import BaseTool
import requests

class TrendingTitlesAPIWrapper(BaseModel):
    """Wrapper for Trending Titles API."""
    api_key: str = Field(description="API key for authentication")

    def get_trending_titles(self):
        """Retrieve trending titles from the API."""
        url = "https://kno2getherworkflow.ddns.net/webhook/getTrendingTitles"
        headers = {"api-key": self.api_key}
        response = requests.post(url, headers=headers)
        response.raise_for_status()  # This will raise an error for non-200 responses
        return response.json()

# Assuming no input is required, we define a minimal input model for consistency
class TrendingTitlesInput(BaseModel):
    # This can be expanded with actual parameters if needed
    pass

class TrendingTitlesQueryRun(BaseTool):
    """Tool that fetches trending titles."""

    name: str = "trending_titles"
    description: str = (
        "A wrapper around an API that provides trending titles. "
        "Useful for when you need to fetch current trending topics or titles."
    )
    api_wrapper: TrendingTitlesAPIWrapper = Field(default_factory=TrendingTitlesAPIWrapper)
    args_schema: Type[BaseModel] = TrendingTitlesInput

    def _run(
        self,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Use the Trending Titles tool."""
        # Assuming no additional parameters are needed beyond the API key
        return self.api_wrapper.get_trending_titles()