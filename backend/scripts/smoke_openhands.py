"""Host-executable Step 29 smoke test for the real OpenHands path."""

import asyncio

from ava.contracts.requests import RunRequest
from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider
from ava.runtimes.adapters.openhands.openhands_runtime import OpenHandsRuntime


async def main() -> None:
    provider = OpenAICompatibleModelProvider(
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen2.5-coder:7b",
        provider_name="local",
    )
    try:
        result = await OpenHandsRuntime().execute(
            run_id="step-29-smoke",
            request=RunRequest(prompt="Reply with exactly: AVA OPENHANDS OK"),
            model_provider=provider,
        )
        print(f"status: {result.status}")
        print(f"content: {result.content}")
        if result.content != "AVA OPENHANDS OK":
            raise SystemExit("Unexpected final response")
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
