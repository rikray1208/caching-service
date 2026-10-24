from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state["engine"]
    return engine


EngineDependency = Annotated[AsyncEngine, Depends(get_engine)]
