from __future__ import annotations

from typing import Protocol

import httpx


class ChatProvider(Protocol):
    def create_reply(self, system_prompt: str, user_prompt: str) -> str:
        ...


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAICompatibleProviderError(RuntimeError):
    pass


class OpenAICompatibleChatProvider:
    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = httpx.Client(
            timeout=self._timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def create_reply(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.post(
                f"{self._api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenAICompatibleProviderError(
                f"OpenAI 兼容接口请求失败，HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenAICompatibleProviderError(
                f"OpenAI 兼容接口请求异常：{exc}"
            ) from exc

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAICompatibleProviderError(
                "OpenAI 兼容接口返回结构不符合预期"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise OpenAICompatibleProviderError("OpenAI 兼容接口返回了空回复")
        return content.strip()


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = httpx.Client(
            timeout=self._timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = self._client.post(
                f"{self._api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "input": texts,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenAICompatibleProviderError(
                f"OpenAI 兼容 embedding 请求失败，HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenAICompatibleProviderError(
                f"OpenAI 兼容 embedding 请求异常：{exc}"
            ) from exc

        payload = response.json()
        try:
            rows = payload["data"]
        except (KeyError, TypeError) as exc:
            raise OpenAICompatibleProviderError(
                "OpenAI 兼容 embedding 返回结构不符合预期"
            ) from exc

        embeddings: list[list[float]] = []
        for row in rows:
            embedding = row["embedding"]
            if (
                not isinstance(embedding, list)
                or not embedding
                or any(not isinstance(value, (int, float)) for value in embedding)
            ):
                raise OpenAICompatibleProviderError("OpenAI 兼容 embedding 返回了非法向量")
            embeddings.append([float(value) for value in embedding])

        if len(embeddings) != len(texts):
            raise OpenAICompatibleProviderError("OpenAI 兼容 embedding 返回数量与输入数量不一致")
        return embeddings
