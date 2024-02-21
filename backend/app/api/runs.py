import asyncio
import json
from typing import Optional, Sequence

import langsmith.client
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from langchain.pydantic_v1 import ValidationError
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langserve.schema import FeedbackCreateRequest
from langserve.server import _unpack_input
from langsmith.utils import tracing_is_enabled
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

from app.agent import agent
from app.schema import OpengptsUserId
from app.storage import get_assistant, public_user_id
from app.stream import astream_messages, to_sse

router = APIRouter()


class CreateRunPayload(BaseModel):
    """Payload for creating a run."""

    assistant_id: str
    thread_id: str
    input: Optional[Sequence[AnyMessage]] = Field(default_factory=list)


async def _run_input_and_config(request: Request, opengpts_user_id: OpengptsUserId):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise RequestValidationError(errors=["Invalid JSON body"])
    assistant, public_assistant = await asyncio.gather(
        asyncio.get_running_loop().run_in_executor(
            None, get_assistant, opengpts_user_id, body["assistant_id"]
        ),
        asyncio.get_running_loop().run_in_executor(
            None, get_assistant, public_user_id, body["assistant_id"]
        ),
    )
    assistant = assistant or public_assistant
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    config: RunnableConfig = {
        **assistant["config"],
        "configurable": {
            **assistant["config"]["configurable"],
            "user_id": opengpts_user_id,
            "thread_id": body["thread_id"],
            "assistant_id": body["assistant_id"],
        },
    }
    try:
        input_ = (
            _unpack_input(agent.get_input_schema(config).validate(body["input"]))
            if body["input"] is not None
            else None
        )
    except ValidationError as e:
        raise RequestValidationError(e.errors(), body=body)

    return input_, config


@router.post("")
async def create_run(
    payload: CreateRunPayload,  # for openapi docs
    request: Request,
    opengpts_user_id: OpengptsUserId,
    background_tasks: BackgroundTasks,
):
    """Create a run."""
    input_, config = await _run_input_and_config(request, opengpts_user_id)
    background_tasks.add_task(agent.ainvoke, input_, config)
    return {"status": "ok"}  # TODO add a run id


@router.post("/stream")
async def stream_run(
    payload: CreateRunPayload,  # for openapi docs
    request: Request,
    opengpts_user_id: OpengptsUserId,
):
    """Create a run."""
    input_, config = await _run_input_and_config(request, opengpts_user_id)

    return EventSourceResponse(to_sse(astream_messages(agent, input_, config)))


@router.get("/input_schema")
async def input_schema() -> dict:
    """Return the input schema of the runnable."""
    return agent.get_input_schema().schema()


@router.get("/output_schema")
async def output_schema() -> dict:
    """Return the output schema of the runnable."""
    return agent.get_output_schema().schema()


@router.get("/config_schema")
async def config_schema() -> dict:
    """Return the config schema of the runnable."""
    return agent.config_schema().schema()


if tracing_is_enabled():
    langsmith_client = langsmith.client.Client()

    @router.post("/feedback")
    def create_run_feedback(feedback_create_req: FeedbackCreateRequest) -> dict:
        """
        Send feedback on an individual run to langsmith

        Note that a successful response means that feedback was successfully
        submitted. It does not guarantee that the feedback is recorded by
        langsmith. Requests may be silently rejected if they are
        unauthenticated or invalid by the server.
        """

        langsmith_client.create_feedback(
            feedback_create_req.run_id,
            feedback_create_req.key,
            score=feedback_create_req.score,
            value=feedback_create_req.value,
            comment=feedback_create_req.comment,
            source_info={
                "from_langserve": True,
            },
        )

        return {"status": "ok"}
