"""The one chat model the whole app uses (only through LangChain interfaces).

Every node and agent gets its model from get_llm(). To change model, change it here.
LLM_CACHE=1 in the environment saves every answer in .llm_cache.sqlite (dev and eval only).
"""

import os
from functools import lru_cache

from langchain_openai import AzureChatOpenAI

from supplyguard_ai.config import REPO_ROOT, require


@lru_cache(maxsize=1)
def get_llm() -> AzureChatOpenAI:
    if os.getenv("LLM_CACHE") == "1":  # same prompt again -> saved answer, no Azure call
        import warnings
        warnings.filterwarnings("ignore", message="The default value of `allowed_objects`")
        from langchain_community.cache import SQLiteCache
        from langchain_community.cache import SQLiteCache
        from langchain_core.globals import set_llm_cache

        set_llm_cache(SQLiteCache(database_path=str(REPO_ROOT / ".llm_cache.sqlite")))
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
        max_retries=6,  # on "429 too many requests": wait and try again instead of failing
    )
