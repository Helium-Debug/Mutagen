import asyncio
import hashlib
import json
import math
import random
import re
import statistics
import time
import tracemalloc
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MemoryRecord:
    record_id: str
    text: str
    tokens: list
    vector: dict
    created: float
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentTask:
    task_id: str
    prompt: str
    priority: int
    dependencies: list = field(default_factory=list)
    status: str = "pending"
    result: object = None
    attempts: int = 0


class DeliberatelyWastefulMemory:
    def __init__(self, capacity=12000):
        self.capacity = capacity
        self.records = []
        self.index = defaultdict(list)
        self.query_log = []
        self.access_log = []
        self.snapshots = []
        self.cache = {}
        self.cache_order = []

    def tokenize(self, text):
        return [piece.lower() for piece in re.findall(r"\b\w+\b", text)]

    def vectorize(self, tokens):
        result = {}
        for token in tokens:
            if token not in result:
                result[token] = 0
            result[token] += 1
        return result

    def store(self, text, metadata=None):
        tokens = self.tokenize(text)
        vector = self.vectorize(tokens)
        record = MemoryRecord(
            str(uuid.uuid4()),
            text,
            tokens,
            vector,
            time.time(),
            metadata or {},
        )
        self.records.append(record)
        for token in tokens:
            self.index[token].append(record.record_id)
        if len(self.records) > self.capacity:
            removed = self.records.pop(0)
            for token in removed.tokens:
                if removed.record_id in self.index[token]:
                    self.index[token].remove(removed.record_id)
        self.snapshots.append({
            "time": time.time(),
            "record_count": len(self.records),
            "token_count": sum(len(item.tokens) for item in self.records),
            "digest": hashlib.sha256(text.encode()).hexdigest(),
        })
        return record.record_id

    def similarity(self, left, right):
        left_tokens = self.tokenize(left)
        right_tokens = self.tokenize(right)
        left_vector = self.vectorize(left_tokens)
        right_vector = self.vectorize(right_tokens)
        all_tokens = list(set(list(left_vector.keys()) + list(right_vector.keys())))
        left_expanded = [left_vector.get(token, 0) for token in all_tokens]
        right_expanded = [right_vector.get(token, 0) for token in all_tokens]
        numerator = 0
        for i in range(len(all_tokens)):
            numerator += left_expanded[i] * right_expanded[i]
        left_norm = math.sqrt(sum(value * value for value in left_expanded))
        right_norm = math.sqrt(sum(value * value for value in right_expanded))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    def retrieve(self, query, limit=8):
        self.query_log.append({
            "query": query,
            "timestamp": time.time(),
            "query_length": len(query),
        })
        ranked = []
        for record in self.records:
            score = self.similarity(query, record.text)
            self.access_log.append((record.record_id, score, time.time()))
            ranked.append((score, record))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "id": record.record_id,
                "text": record.text,
                "score": score,
                "metadata": record.metadata,
            }
            for score, record in ranked[:limit]
        ]


class WastefulToolBox:
    def __init__(self):
        self.tools = {}
        self.call_history = []
        self.tool_statistics = defaultdict(list)

    def register(self, name, function):
        self.tools[name] = function

    async def invoke(self, name, payload):
        started = time.perf_counter()
        if name not in self.tools:
            raise KeyError(f"Unknown tool: {name}")
        result = await asyncio.to_thread(self.tools[name], payload)
        elapsed = time.perf_counter() - started
        self.tool_statistics[name].append(elapsed)
        self.call_history.append({
            "name": name,
            "payload": json.dumps(payload, default=str),
            "result": json.dumps(result, default=str),
            "elapsed": elapsed,
            "timestamp": time.time(),
        })
        return result


class WastefulAgent:
    def __init__(self, name="MemoryMonster", memory_capacity=12000, workers=4):
        self.name = name
        self.memory = DeliberatelyWastefulMemory(memory_capacity)
        self.tools = WastefulToolBox()
        self.executor = ThreadPoolExecutor(max_workers=workers)
        self.conversation = []
        self.reasoning_traces = []
        self.task_history = []
        self.metrics = defaultdict(list)
        self.running = False
        self.max_reasoning_rounds = 4
        self.max_conversation = 5000
        self.register_tools()

    def register_tools(self):
        self.tools.register("hash", lambda payload: hashlib.sha512(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest())
        self.tools.register("calculate", lambda payload: sum(
            math.sqrt(abs(number) + 1) * math.log(abs(number) + 2)
            for number in payload.get("numbers", [])
            for _ in range(80)
        ))
        self.tools.register("analyze", lambda payload: {
            "mean": statistics.mean(payload["values"]) if payload.get("values") else 0,
            "median": statistics.median(payload["values"]) if payload.get("values") else 0,
            "distribution": dict(Counter(payload.get("values", []))),
            "checksum": hashlib.sha256(
                repr(sorted(payload.get("values", []))).encode()
            ).hexdigest(),
        })
        self.tools.register("text_transform", lambda payload: {
            "normalized": re.sub(r"\s+", " ", payload.get("text", "").lower()).strip(),
            "tokens": re.findall(r"\b\w+\b", payload.get("text", "").lower()),
            "reversed": payload.get("text", "")[::-1],
        })

    def seed_memory(self, count=400):
        vocabulary = [
            "agent", "memory", "planning", "reasoning", "context", "retrieval",
            "runtime", "scheduler", "execution", "tool", "task", "cache",
            "latency", "throughput", "dependency", "worker", "trace", "state",
            "vector", "token", "analysis", "decision", "queue", "result",
        ]
        for number in range(count):
            words = [
                random.choice(vocabulary)
                for _ in range(random.randint(20, 65))
            ]
            self.memory.store(
                " ".join(words),
                {"sequence": number, "category": random.choice(vocabulary)},
            )

    async def think(self, prompt):
        started = time.perf_counter()
        traces = []
        context = []
        current = prompt
        for round_number in range(self.max_reasoning_rounds):
            memories = await asyncio.to_thread(self.memory.retrieve, current, 8)
            context.extend(memories)
            candidates = [
                self.memory.similarity(current, item["text"])
                for item in memories
            ]
            candidates.extend(
                self.memory.similarity(prompt, item["text"])
                for item in memories
            )
            score = statistics.mean(candidates) if candidates else 0
            traces.append({
                "round": round_number,
                "input": current,
                "score": score,
                "retrieved": len(memories),
                "context_copy": list(context),
                "timestamp": time.time(),
            })
            current = (
                current + " " +
                " ".join(item["text"] for item in memories[:3]) +
                f" round {round_number} confidence {score:.6f}"
            )
        response = (
            f"{self.name} processed {len(prompt)} characters, "
            f"retrieved {len(context)} memory entries, "
            f"reasoning score {score:.4f}"
        )
        self.reasoning_traces.extend(traces)
        self.metrics["reasoning_seconds"].append(time.perf_counter() - started)
        return response

    async def process(self, prompt):
        started = time.perf_counter()
        self.conversation.append({
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "id": str(uuid.uuid4()),
        })
        self.memory.store(prompt, {"kind": "user_input"})
        response = await self.think(prompt)
        self.conversation.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "id": str(uuid.uuid4()),
        })
        if len(self.conversation) > self.max_conversation:
            self.conversation = self.conversation[-self.max_conversation:]
        self.metrics["process_seconds"].append(time.perf_counter() - started)
        return response

    async def run_workload(self, task_count=80):
        tasks = []
        for number in range(task_count):
            task = AgentTask(
                task_id=str(uuid.uuid4()),
                prompt=f"Evaluate task {number} with context memory retrieval planning",
                priority=random.randint(1, 10),
            )
            tasks.append(task)
        tasks.sort(key=lambda task: task.priority, reverse=True)
        semaphore = asyncio.Semaphore(4)

        async def run_one(task):
            async with semaphore:
                task.status = "running"
                task.attempts += 1
                try:
                    task.result = await self.process(task.prompt)
                    task.status = "completed"
                except Exception as error:
                    task.status = "failed"
                    task.result = f"{type(error).__name__}: {error}"
                self.task_history.append({
                    "task": task.task_id,
                    "prompt": task.prompt,
                    "status": task.status,
                    "result": task.result,
                    "attempts": task.attempts,
                    "finished": time.time(),
                })
                return task.status

        return await asyncio.gather(*(run_one(task) for task in tasks))

    def report(self):
        memory_tokens = sum(len(record.tokens) for record in self.memory.records)
        return {
            "agent": self.name,
            "memory_records": len(self.memory.records),
            "stored_tokens": memory_tokens,
            "index_terms": len(self.memory.index),
            "query_log_entries": len(self.memory.query_log),
            "access_log_entries": len(self.memory.access_log),
            "snapshot_entries": len(self.memory.snapshots),
            "conversation_entries": len(self.conversation),
            "reasoning_trace_entries": len(self.reasoning_traces),
            "task_history_entries": len(self.task_history),
            "tool_calls": len(self.tools.call_history),
            "mean_reasoning_ms": round(
                statistics.mean(self.metrics["reasoning_seconds"]) * 1000, 2
            ) if self.metrics["reasoning_seconds"] else 0,
            "mean_process_ms": round(
                statistics.mean(self.metrics["process_seconds"]) * 1000, 2
            ) if self.metrics["process_seconds"] else 0,
            "python_traced_memory": tracemalloc.get_traced_memory(),
        }

    async def interactive(self):
        self.running = True
        while self.running:
            try:
                prompt = await asyncio.to_thread(input, "monster> ")
            except (EOFError, KeyboardInterrupt):
                break
            if prompt.strip().lower() in {"exit", "quit"}:
                break
            if prompt.strip().lower() == "status":
                print(json.dumps(self.report(), indent=2, default=str))
                continue
            print(await self.process(prompt))
        self.running = False


async def main():
    random.seed(41)
    tracemalloc.start()
    agent = WastefulAgent(memory_capacity=12000, workers=4)
    agent.seed_memory(400)
    await agent.run_workload(80)
    print(json.dumps(agent.report(), indent=2, default=str))
    await agent.interactive()
    agent.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    asyncio.run(main())
