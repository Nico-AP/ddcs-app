class ResearchAPIAccessTokenRetrievalError(Exception):
    """Raised when access token could not be obtained."""


class ResearchAPIRequestError(Exception):
    """Raised when response retrieved from Research API contains errors."""
