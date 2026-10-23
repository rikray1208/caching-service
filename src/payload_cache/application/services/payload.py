from uuid import UUID

from payload_cache.application.payload_input import PayloadInput
from payload_cache.application.ports.payload_gateway import NewPayload, PayloadGateway, PayloadNotFoundError
from payload_cache.application.services.transformation import TransformationService


class PayloadService:
    def __init__(self, transformation_service: TransformationService, payload_gateway: PayloadGateway) -> None:
        self._transformation_service = transformation_service
        self._payload_gateway = payload_gateway

    async def create(self, payload_input: PayloadInput) -> UUID:
        transformations = await self._transformation_service.transform_all(payload_input.texts())
        output = payload_input.render(transformations)
        return await self._payload_gateway.add(NewPayload(output=output))

    async def get_output(self, payload_id: UUID) -> str:
        output = await self._payload_gateway.find_output(payload_id)
        if output is None:
            raise PayloadNotFoundError(payload_id)
        return output
