"""Real persistence with synthetic channel messages and mocked external adapters."""

from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_caspian import event, message
from test_chat_runtime import Model

from svaar.actions.catalog import build_registry
from svaar.actions.dispatcher import ApprovalPolicy, Dispatcher
from svaar.actions.models import ToolExecution
from svaar.agent.caspian import CaspianTransport
from svaar.agent.loop import AgentLoop
from svaar.agent.runtime import ChatRuntime
from svaar.agent.worker import GatewayWorker
from svaar.decisions.service import DecisionService
from svaar.identity.models import ChannelBinding, Principal, Role
from svaar.identity.service import create_invite, create_org

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("channel,privacy", [("slack", "im"), ("discord", "dm")])
def test_private_channel_enrollment_reply_read_tool_and_restart_dedupe(
    session_factory, channel, privacy
):
    with session_factory.begin() as session:
        org = create_org(session, "Offline test")
        invite = create_invite(session, org.id, Role.DEV, timedelta(hours=1))
        code = invite.code
    page = [
        event(seq=1, id="join", channel=channel, chat_type=privacy, text="/join " + code),
        event(seq=2, id="question", channel=channel, chat_type=privacy),
    ]
    sends = []

    def respond(request):
        if request.url.path == "/v1/events":
            cursor = int(request.url.params["after_seq"])
            return httpx.Response(200, json=[e for e in page if e["seq"] > cursor])
        assert request.method == "POST"
        sends.append(request)
        return httpx.Response(
            201,
            json=message(
                id="out-" + str(len(sends)),
                channel=channel,
                chat_type=privacy,
                direction="outbound",
                status="sent",
            ),
        )

    adapter = CaspianTransport(
        api_key=SecretStr("offline"),
        connection_id="conn-1",
        address="bot",
        channel=channel,
        transport=httpx.MockTransport(respond),
    )
    loop = AgentLoop(
        Model(),
        Dispatcher(build_registry(), ApprovalPolicy(timedelta(minutes=10), 3, False)),
        DecisionService(None, high=0.85, low=0.55),
    )
    runtime = ChatRuntime(session_factory, loop)
    try:
        worker = GatewayWorker(
            session_factory, runtime, adapter, channel="caspian:" + channel, connection_id="conn-1"
        )
        assert worker.tick() == "ready"
        assert len(sends) == 2
        restarted = GatewayWorker(
            session_factory, runtime, adapter, channel="caspian:" + channel, connection_id="conn-1"
        )
        assert restarted.tick() == "ready"
        assert len(sends) == 2
        with session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Principal)) == 1
            assert session.scalar(select(func.count()).select_from(ToolExecution)) == 1
            assert session.scalar(select(ChannelBinding.channel)) == "caspian:" + channel
    finally:
        adapter.close()
        loop.close()
