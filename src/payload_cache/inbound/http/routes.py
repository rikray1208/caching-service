from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from payload_cache.application.payload_input import PayloadInput
from payload_cache.inbound.http.dependencies import PayloadServiceDependency
from payload_cache.inbound.http.schemas import CreatePayloadRequest, CreatePayloadResponse, PayloadResponse

router = APIRouter(tags=["Payload"])


@router.post(
    "/payload",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": CreatePayloadResponse, "description": "The input was seen before."}},
)
async def create_payload(
    body: CreatePayloadRequest, request: Request, response: Response, service: PayloadServiceDependency
) -> CreatePayloadResponse:
    stored = await service.create(PayloadInput(list_1=tuple(body.list_1), list_2=tuple(body.list_2)))
    # A path, which RFC 9110 allows: an absolute URL built from the Host header is wrong behind a proxy.
    # url_for(...).path keeps the proxy's root_path, which app.url_path_for would drop.
    response.headers["Location"] = request.url_for("get_payload", payload_id=stored.id).path
    if stored.created:
        return CreatePayloadResponse(id=stored.id, message="Payload created.")
    response.status_code = status.HTTP_200_OK
    return CreatePayloadResponse(id=stored.id, message="Payload already exists.")


@router.get("/payload/{payload_id}")
async def get_payload(payload_id: UUID, service: PayloadServiceDependency) -> PayloadResponse:
    return PayloadResponse(output=await service.get_output(payload_id))
