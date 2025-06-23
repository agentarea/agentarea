from fastapi import FastAPI
from faststream.redis import RedisBroker
from faststream.redis.fastapi import RedisRouter

app = FastAPI(title="AgentArea Worker")
broker = RedisBroker("redis://localhost:6379")
router = RedisRouter(broker)


@router.after_startup
async def setup():
    """Set up broker connection on startup."""
    await broker.connect()


@router.before_shutdown
async def cleanup():
    """Clean up broker connection on shutdown."""
    await broker.disconnect()


def main():
    """Run the worker server."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
