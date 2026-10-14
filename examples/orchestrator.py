import asyncio
import hashlib
import heapq
import json
import random
import statistics
import time
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class Task:
    name: str
    payload: dict
    dependencies: list[str] = field(default_factory=list)
    priority: int = 0
    retries: int = 2
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    attempts: int = 0
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.perf_counter)
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class Event:
    kind: str
    task_id: str
    timestamp: str
    details: dict = field(default_factory=dict)


class EventBus:
    def __init__(self, max_events=10000):
        self.events = deque(maxlen=max_events)
        self.subscribers = defaultdict(list)
        self.counts = Counter()

    def subscribe(self, kind, callback):
        self.subscribers[kind].append(callback)

    def publish(self, kind, task_id, **details):
        event = Event(kind, task_id, datetime.now(timezone.utc).isoformat(), details)
        self.events.append(event)
        self.counts[kind] += 1
        for callback in self.subscribers.get(kind, []):
            callback(event)
        for callback in self.subscribers.get("*", []):
            callback(event)
        return event

    def export(self):
        return [asdict(event) for event in self.events]


class ResultCache:
    def __init__(self, capacity=2048, ttl=60):
        self.capacity = capacity
        self.ttl = ttl
        self.data = {}
        self.hits = 0
        self.misses = 0

    def key(self, name, payload):
        raw = json.dumps([name, payload], sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, name, payload):
        key = self.key(name, payload)
        item = self.data.get(key)
        if item is None:
            self.misses += 1
            return None
        expiry, value = item
        if time.monotonic() >= expiry:
            del self.data[key]
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, name, payload, value):
        key = self.key(name, payload)
        if len(self.data) >= self.capacity:
            oldest = min(self.data, key=lambda k: self.data[k][0])
            del self.data[oldest]
        self.data[key] = (time.monotonic() + self.ttl, value)


class ToolBox:
    def __init__(self):
        self.tools: dict[str, Callable] = {}
        self.calls = Counter()
        self.failures = Counter()

    def register(self, name, function):
        self.tools[name] = function

    async def call(self, name, payload):
        if name not in self.tools:
            raise KeyError(f"Unknown tool: {name}")
        self.calls[name] += 1
        result = self.tools[name](payload)
        if asyncio.iscoroutine(result):
            return await result
        return result


class DependencyGraph:
    def __init__(self):
        self.tasks = {}
        self.children = defaultdict(set)
        self.remaining = {}

    def add(self, task):
        if task.task_id in self.tasks:
            raise ValueError("Duplicate task id")
        self.tasks[task.task_id] = task
        self.remaining[task.task_id] = len(task.dependencies)
        for dependency in task.dependencies:
            self.children[dependency].add(task.task_id)

    def validate(self):
        for task in self.tasks.values():
            for dependency in task.dependencies:
                if dependency not in self.tasks:
                    raise ValueError(f"Missing dependency: {dependency}")
        visiting, visited = set(), set()

        def visit(node):
            if node in visiting:
                raise ValueError("Dependency cycle detected")
            if node in visited:
                return
            visiting.add(node)
            for child in self.children.get(node, ()):
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in self.tasks:
            visit(node)
        return True

    def release_children(self, task_id):
        ready = []
        for child in self.children.get(task_id, ()):
            self.remaining[child] -= 1
            if self.remaining[child] == 0:
                ready.append(self.tasks[child])
        return ready


class Metrics:
    def __init__(self):
        self.latencies = []
        self.queue_waits = []
        self.completed = 0
        self.failed = 0
        self.skipped = 0
        self.started = time.perf_counter()

    def record(self, task):
        if task.started_at is not None and task.finished_at is not None:
            self.latencies.append(task.finished_at - task.started_at)
            self.queue_waits.append(task.started_at - task.created_at)
        if task.status == "completed":
            self.completed += 1
        elif task.status == "failed":
            self.failed += 1
        elif task.status == "skipped":
            self.skipped += 1

    def snapshot(self):
        elapsed = max(time.perf_counter() - self.started, 1e-9)
        return {
            "completed": self.completed,
            "failed": self.failed,
            "skipped": self.skipped,
            "elapsed_seconds": round(elapsed, 6),
            "throughput_tasks_per_second": round(
                (self.completed + self.failed + self.skipped) / elapsed, 2
            ),
            "mean_task_latency_ms": round(statistics.mean(self.latencies) * 1000, 3)
            if self.latencies else 0,
            "p95_task_latency_ms": round(
                sorted(self.latencies)[min(int(len(self.latencies) * 0.95), len(self.latencies) - 1)] * 1000, 3
            ) if self.latencies else 0,
            "mean_queue_wait_ms": round(statistics.mean(self.queue_waits) * 1000, 3)
            if self.queue_waits else 0,
        }


class Agent:
    def __init__(self, name, tools, cache, events):
        self.name = name
        self.tools = tools
        self.cache = cache
        self.events = events
        self.completed_ids = set()

    async def execute(self, task):
        cached = self.cache.get(task.name, task.payload)
        if cached is not None:
            self.events.publish("cache_hit", task.task_id, agent=self.name)
            return cached
        self.events.publish("tool_start", task.task_id, agent=self.name, tool=task.name)
        result = await self.tools.call(task.name, task.payload)
        self.cache.put(task.name, task.payload, result)
        self.events.publish("tool_finish", task.task_id, agent=self.name, tool=task.name)
        self.completed_ids.add(task.task_id)
        return result


class Orchestrator:
    def __init__(self, concurrency=4):
        self.graph = DependencyGraph()
        self.events = EventBus()
        self.cache = ResultCache()
        self.tools = ToolBox()
        self.metrics = Metrics()
        self.concurrency = concurrency
        self.queue = []
        self.sequence = 0
        self.agent_pool = [
            Agent(f"agent-{i}", self.tools, self.cache, self.events)
            for i in range(concurrency)
        ]
        self.register_tools()

    def register_tools(self):
        self.tools.register("sum", lambda p: sum(p.get("numbers", [])))
        self.tools.register("multiply", lambda p: __import__("math").prod(p.get("numbers", [])))
        self.tools.register("transform", lambda p: {
            "text": str(p.get("text", "")).upper(),
            "length": len(str(p.get("text", ""))),
            "tokens": len(str(p.get("text", "")).split()),
        })
        self.tools.register("analyze", lambda p: {
            "count": len(p.get("values", [])),
            "mean": statistics.mean(p["values"]) if p.get("values") else 0,
            "unique": len(set(p.get("values", []))),
            "checksum": hashlib.sha256(
                json.dumps(p.get("values", []), sort_keys=True).encode()
            ).hexdigest()[:16],
        })
        self.tools.register("simulate", lambda p: {
            "sample": random.Random(p.get("seed", 1)).random(),
            "iterations": sum(i % 7 for i in range(p.get("iterations", 1000))),
        })

    def add_task(self, task):
        self.graph.add(task)
        self.events.publish("task_added", task.task_id, name=task.name)

    def enqueue(self, task):
        self.sequence += 1
        heapq.heappush(self.queue, (-task.priority, self.sequence, task.task_id))

    async def run_task(self, task, agent):
        task.status = "running"
        task.started_at = time.perf_counter()
        self.events.publish("task_started", task.task_id, agent=agent.name)
        while task.attempts <= task.retries:
            task.attempts += 1
            try:
                task.result = await agent.execute(task)
                task.status = "completed"
                task.finished_at = time.perf_counter()
                self.events.publish("task_completed", task.task_id, attempts=task.attempts)
                return task
            except Exception as exc:
                task.error = f"{type(exc).__name__}: {exc}"
                self.tools.failures[task.name] += 1
                self.events.publish("task_retry", task.task_id, attempt=task.attempts, error=task.error)
                await asyncio.sleep(min(0.01 * task.attempts, 0.05))
        task.status = "failed"
        task.finished_at = time.perf_counter()
        self.events.publish("task_failed", task.task_id, error=task.error)
        return task

    async def run(self):
        self.graph.validate()
        for task in self.graph.tasks.values():
            if self.graph.remaining[task.task_id] == 0:
                self.enqueue(task)
        semaphore = asyncio.Semaphore(self.concurrency)
        running = {}

        async def launch(task, agent):
            async with semaphore:
                return await self.run_task(task, agent)

        while self.queue or running:
            while self.queue and len(running) < self.concurrency:
                _, _, task_id = heapq.heappop(self.queue)
                task = self.graph.tasks[task_id]
                agent = self.agent_pool[len(running) % len(self.agent_pool)]
                running[task_id] = asyncio.create_task(launch(task, agent))
            if not running:
                break
            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for future in done:
                task = await future
                running.pop(task.task_id, None)
                self.metrics.record(task)
                if task.status == "completed":
                    for child in self.graph.release_children(task.task_id):
                        self.enqueue(child)
                else:
                    for child_id in self.graph.children.get(task.task_id, ()):
                        child = self.graph.tasks[child_id]
                        if child.status == "pending":
                            child.status = "skipped"
                            child.error = f"Dependency {task.task_id} did not complete"
                            child.finished_at = time.perf_counter()
                            self.metrics.record(child)
                            self.events.publish("task_skipped", child.task_id)
        return self.report()

    def report(self):
        return {
            "metrics": self.metrics.snapshot(),
            "cache": {
                "entries": len(self.cache.data),
                "hits": self.cache.hits,
                "misses": self.cache.misses,
            },
            "tools": {
                "calls": dict(self.tools.calls),
                "failures": dict(self.tools.failures),
            },
            "events": dict(self.events.counts),
            "tasks": [
                {
                    "id": task.task_id,
                    "name": task.name,
                    "status": task.status,
                    "attempts": task.attempts,
                    "result": task.result,
                    "error": task.error,
                }
                for task in self.graph.tasks.values()
            ],
        }


async def main():
    random.seed(7)
    engine = Orchestrator(concurrency=6)
    tasks = []
    for i in range(60):
        name = ["sum", "multiply", "transform", "analyze", "simulate"][i % 5]
        if name == "sum":
            payload = {"numbers": [i, i + 1, i + 2]}
        elif name == "multiply":
            payload = {"numbers": [max(1, i % 7), 2, 3]}
        elif name == "transform":
            payload = {"text": f"agent task payload number {i}"}
        elif name == "analyze":
            payload = {"values": [i % 9, (i + 2) % 11, (i + 4) % 13]}
        else:
            payload = {"seed": i, "iterations": 2000 + i * 10}
        dependencies = [tasks[-1].task_id] if i > 0 and i % 4 != 0 else []
        task = Task(
            name=name,
            payload=payload,
            dependencies=dependencies,
            priority=random.randint(0, 5),
            retries=1,
        )
        engine.add_task(task)
        tasks.append(task)
    print(json.dumps(await engine.run(), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
