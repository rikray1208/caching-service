from uuid import UUID

from payload_cache.application.payload_input import PayloadInput
from payload_cache.application.ports.payload_gateway import NewPayload, PayloadGateway, PayloadNotFoundError
from payload_cache.application.ports.transformer import Transformer


class PayloadService:
    def __init__(self, transformer: Transformer, payload_gateway: PayloadGateway) -> None:
        self._transformer = transformer
        self._payload_gateway = payload_gateway

    async def create(self, payload_input: PayloadInput) -> UUID:
        transformations: dict[str, str] = {}
        for text in payload_input.texts():
            transformations[text] = await self._transformer.transform(text)

        output = payload_input.render(transformations)
        return await self._payload_gateway.add(NewPayload(output=output))

    async def get_output(self, payload_id: UUID) -> str:
        output = await self._payload_gateway.find_output(payload_id)
        if output is None:
            raise PayloadNotFoundError(payload_id)
        return output
