"""PRANA AI backend framework — generic, provider-independent."""
from framework.agent.base import Agent

__version__ = "0.1.0"


def agent(provider, registry, *, user=None, **kw) -> Agent:
    """Public facade: construct an Agent. `user` accepted for API symmetry; the
    UserContext is passed per-call to Agent.run()."""
    return Agent(provider, registry, **kw)
