from fastapi import FastAPI
from faststream.redis import RedisBroker
from faststream.redis.fastapi import RedisRouter

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
