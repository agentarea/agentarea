import os

from google.adk.models.lite_llm import LiteLlm


def get_litellm_llm(model: str, api_key: str = None, **kwargs):
    """
    Returns a callable that wraps litellm's completion function for the specified model.
    Optionally sets the API key in the environment.
    Additional kwargs are passed to litellm.completion.
    """
    lite_llm = LiteLlm(
        model=model,
        api_key=api_key,
        **kwargs
    )
    
    return lite_llm
