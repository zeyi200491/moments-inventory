from __future__ import annotations

import json

import httpx
import pytest

from moments_inventory.ai_kefu.providers import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleChatProvider,
    OpenAICompatibleProviderError,
)


def test_openai_compatible_provider_posts_chat_completions_request():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "您好，这边先帮您确认一下库存。",
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleChatProvider(
        api_base="https://example.com/v1",
        api_key="secret-key",
        model="gpt-4.1-mini",
        timeout_seconds=30,
        transport=transport,
    )

    reply = provider.create_reply(
        system_prompt="系统提示",
        user_prompt="用户提示",
    )

    assert reply == "您好，这边先帮您确认一下库存。"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret-key"
    assert captured["body"] == {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "用户提示"},
        ],
    }


def test_openai_compatible_provider_reuses_http_client():
    provider = OpenAICompatibleChatProvider(
        api_base="https://example.com/v1",
        api_key="secret-key",
        model="gpt-4.1-mini",
        timeout_seconds=30,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}]},
            )
        ),
    )

    first_client = provider._client
    provider.create_reply(system_prompt="系统提示", user_prompt="第一次")
    provider.create_reply(system_prompt="系统提示", user_prompt="第二次")

    assert provider._client is first_client


def test_openai_compatible_provider_rejects_empty_response_content():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}}]},
        )
    )
    provider = OpenAICompatibleChatProvider(
        api_base="https://example.com/v1/",
        api_key="secret-key",
        model="gpt-4.1-mini",
        timeout_seconds=30,
        transport=transport,
    )

    with pytest.raises(OpenAICompatibleProviderError, match="空回复"):
        provider.create_reply(system_prompt="系统提示", user_prompt="用户提示")


def test_openai_compatible_provider_surfaces_http_errors():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401,
            json={"error": {"message": "invalid api key"}},
        )
    )
    provider = OpenAICompatibleChatProvider(
        api_base="https://example.com/v1",
        api_key="bad-key",
        model="gpt-4.1-mini",
        timeout_seconds=30,
        transport=transport,
    )

    with pytest.raises(OpenAICompatibleProviderError, match="401"):
        provider.create_reply(system_prompt="系统提示", user_prompt="用户提示")


def test_openai_compatible_embedding_provider_posts_embeddings_request():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        api_base="https://example.com/v1",
        api_key="secret-key",
        model="text-embedding-3-small",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )

    embeddings = provider.embed_texts(["第一条", "第二条"])

    assert embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/v1/embeddings"
    assert captured["authorization"] == "Bearer secret-key"
    assert captured["body"] == {
        "model": "text-embedding-3-small",
        "input": ["第一条", "第二条"],
    }
