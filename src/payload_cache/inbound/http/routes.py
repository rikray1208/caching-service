from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from payload_cache.application.payload_input import PayloadInput
from payload_cache.inbound.http.dependencies import PayloadServiceDependency
from payload_cache.inbound.http.schemas import CreatePayloadRequest, CreatePayloadResponse, PayloadResponse

router = APIRouter(tags=["Payload"])


@router.post("/payload", status_code=status.HTTP_201_CREATED)
async def create_payload(body: CreatePayloadRequest, service: PayloadServiceDependency) -> CreatePayloadResponse:
    payload_id = await service.create(PayloadInput(list_1=tuple(body.list_1), list_2=tuple(body.list_2)))
    return CreatePayloadResponse(id=payload_id, message="Payload created.")


@router.get("/payload/{payload_id}")
async def get_payload(payload_id: UUID, service: PayloadServiceDependency) -> PayloadResponse:
    output = await service.get_output(payload_id)
    if output is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return PayloadResponse(output=output)
