from fastapi import FastAPI
from faststream.redis import RedisBroker
from faststream.redis.fastapi import RedisRouter

from agentarea_domain.worker.faststream_app import start_faststream, stop_faststream

app = FastAPI(title="AgentArea Worker")
broker = RedisBroker("redis://localhost:6379")
router = RedisRouter(broker)


@router.after_startup
async def setup():
    await broker.connect()


@router.before_shutdown
async def cleanup():
    await broker.disconnect()


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
