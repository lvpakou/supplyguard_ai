"""The one chat model the whole app uses (only through LangChain interfaces).

Every node and agent gets its model from get_llm(). To change model, change it here.
"""

from functools import lru_cache

from langchain_openai import AzureChatOpenAI

from supplyguard_ai.config import require


@lru_cache(maxsize=1)
def get_llm() -> AzureChatOpenAI:
    settings = require(
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
    )
    return AzureChatOpenAI(
        azure_endpoint=settings["AZURE_OPENAI_ENDPOINT"],
        api_key=settings["AZURE_OPENAI_API_KEY"],
        api_version=settings["OPENAI_API_VERSION"],
        azure_deployment=settings["AZURE_OPENAI_DEPLOYMENT_NAME"],
        temperature=0,  # predictable extraction and explanations
    )
