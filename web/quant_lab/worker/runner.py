"""RQ worker entry point for Quant Lab."""
import os
import sys
from redis import Redis
from rq import Worker, Queue

# Add web/ directory to path for quant_lab module
WEB_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, WEB_DIR)

# Also add project root for other imports
PROJECT_ROOT = os.path.dirname(WEB_DIR)
sys.path.insert(0, PROJECT_ROOT)


def run_worker():
    """Start the RQ worker."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_conn = Redis.from_url(redis_url)

    # Listen on quant_lab queue
    queues = [Queue("quant_lab", connection=redis_conn)]

    worker = Worker(queues, connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    run_worker()
