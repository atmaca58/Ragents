import asyncio


def test_model_calls_wait_for_same_account_without_blocking_other_async_work(tmp_path):
    from ragents.auth import async_account_guard

    async def scenario():
        order = []
        entered, release = asyncio.Event(), asyncio.Event()

        async def first():
            async with async_account_guard("default", tmp_path):
                order.append("first")
                entered.set()
                await release.wait()

        async def second():
            await entered.wait()
            async with async_account_guard("default", tmp_path):
                order.append("second")

        left, right = asyncio.create_task(first()), asyncio.create_task(second())
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.sleep(0.02)
        assert order == ["first"]
        release.set()
        await asyncio.wait_for(asyncio.gather(left, right), 1)
        assert order == ["first", "second"]

    asyncio.run(scenario())
