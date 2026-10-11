"""One OAuth connect flow for every connection kind.

A remote MCP server and a trusted catalog API are authorized the same way:
preflight, authorize, the provider's sign-in, one callback, then the stored
tokens refresh themselves. Only where the profile comes from and what the
callback attaches the credential to differ, and those live in ``targets``.
"""
