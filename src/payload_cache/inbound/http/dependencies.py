from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payload_cache.application.ports.transformer import Transformer
from payload_cache.application.services.payload import PayloadService
from payload_cache.application.services.transformation import TransformationService
from payload_cache.outbound.persistence.sqla_payload_gateway import SqlaPayloadGateway


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state["session_factory"]
    return session_factory


SessionFactoryDependency = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


def get_transformer(request: Request) -> Transformer:
    transformer: Transformer = request.app.state["transformer"]
    return transformer


TransformerDependency = Annotated[Transformer, Depends(get_transformer)]


def get_payload_service(
    session_factory: SessionFactoryDependency, transformer: TransformerDependency
) -> PayloadService:
    return PayloadService(TransformationService(transformer), SqlaPayloadGateway(session_factory))


PayloadServiceDependency = Annotated[PayloadService, Depends(get_payload_service)]
