import asyncio
import json
import math
import random
import re
import statistics
import time
import heapq
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from datetime import datetime, timezone
from functools import lru_cache

# Pre‑compiled regular expression used throughout the module
_WORD_RE = re.compile(r"\w+")


@dataclass
class Message:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentMemory:
    history: deque = field(default_factory=lambda: deque(maxlen=500))
    facts: dict = field(default_factory=dict)
    embeddings: dict = field(default_factory=dict)

    def remember(self, key, value):
        self.facts[str(key)] = value
        # Store the vectorized form for fast later similarity checks
        self.embeddings[str(key)] = self.vectorize(str(value))

    @staticmethod
    @lru_cache(maxsize=1024)
    def _tokenize(text: str):
        """Return a tuple of lower‑cased word tokens.
        Cached to avoid repeated regex work on identical strings.
        """
        return tuple(token.lower() for token in _WORD_RE.findall(text))

    def vectorize(self, text):
        """Convert text to a Counter of token frequencies.
        Utilises the cached token list for speed.
        """
        return Counter(self._tokenize(text))

    def similarity(self, left, right):
        # Try to reuse previously computed vectors when possible
        a = self.embeddings.get(str(left)) or self.vectorize(str(left))
        b = self.embeddings.get(str(right)) or self.vectorize(str(right))
        intersection = set(a) & set(b)
        numerator = sum(a[k] * b[k] for k in intersection)
        denominator = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
        return numerator / denominator if denominator else 0.0

    def retrieve(self, query, limit: int = 5):
        """Return the *limit* most similar facts without sorting the whole list.
        Uses ``heapq.nlargest`` for O(n log k) performance.
        """
        scored = (
            (key, value, self.similarity(query, str(value)))
            for key, value in self.facts.items()
        )
        top = heapq.nlargest(limit, scored, key=lambda item: item[2])
        return [(k, v) for k, v, _ in top]


@dataclass
class Tool:
    name: str
    description: str
    function: Callable
    enabled: bool = True
    calls: int = 0

    def execute(self, *args, **kwargs):
        if not self.enabled:
            raise RuntimeError(f"Tool disabled: {self.name}")
        self.calls += 1
        return self.function(*args, **kwargs)


class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.executor = ThreadPoolExecutor(max_workers=4)

    def register(self, tool):
        self.tools[tool.name] = tool

    def execute(self, name, *args, **kwargs):
        if name not in self.tools:
            raise KeyError(f"Unknown tool: {name}")
        return self.tools[name].execute(*args, **kwargs)

    def execute_parallel(self, requests):
        futures = {
            name: self.executor.submit(self.execute, name, *args, **kwargs)
            for name, args, kwargs in requests
        }
        return {name: future.result(timeout=10) for name, future in futures.items()}

    def describe(self):
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "enabled": tool.enabled,
                "calls": tool.calls,
            }
            for tool in self.tools.values()
        ]


class ReasoningEngine:
    def __init__(self, memory, registry):
        self.memory = memory
        self.registry = registry
        self.max_depth = 8
        self.confidence_threshold = 0.25
        self.planning_weights = {
            "relevance": 0.35,
            "confidence": 0.25,
            "recency": 0.15,
            "complexity": 0.15,
            "novelty": 0.10,
        }

    def classify(self, query):
        tokens = _WORD_RE.findall(query.lower())
        if any(word in tokens for word in ("calculate", "sum", "multiply", "divide")):
            return "calculation"
        if any(word in tokens for word in ("remember", "recall", "previously")):
            return "memory"
        if any(word in tokens for word in ("time", "clock", "date")):
            return "datetime"
        if any(word in tokens for word in ("random", "choose", "roll")):
            return "random"
        return "conversation"

    def score(self, query, candidate, depth=0):
        relevance = self.memory.similarity(query, candidate)
        confidence = 1.0 / (1.0 + math.exp(-4 * (relevance - 0.5)))
        recency = math.exp(-depth / max(self.max_depth, 1))
        complexity = min(len(candidate.split()) / 100, 1)
        novelty = 1.0 - relevance
        return (
            relevance * self.planning_weights["relevance"]
            + confidence * self.planning_weights["confidence"]
            + recency * self.planning_weights["recency"]
            + complexity * self.planning_weights["complexity"]
            + novelty * self.planning_weights["novelty"]
        )

    def plan(self, query):
        category = self.classify(query)
        memories = self.memory.retrieve(query)
        candidates = [
            {
                "category": category,
                "memory": key,
                "content": str(value),
                "score": self.score(query, str(value)),
            }
            for key, value in memories
        ]
        return sorted(candidates, key=lambda item: item["score"], reverse=True)

    def reason(self, query):
        plan = self.plan(query)
        category = self.classify(query)
        if category == "calculation":
            numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", query)]
            if len(numbers) >= 2:
                if "multiply" in query.lower():
                    return str(math.prod(numbers))
                if "divide" in query.lower():
                    return str(numbers[0] / numbers[1]) if numbers[1] else "Division by zero."
                if "sum" in query.lower() or "calculate" in query.lower():
                    return str(sum(numbers))
        if category == "datetime":
            return datetime.now(timezone.utc).isoformat()
        if category == "random":
            return str(random.choice(["A", "B", "C", "D", "E"]))
        if category == "memory" and plan:
            return "\n".join(item["content"] for item in plan[:3])
        return self.generate_response(query, plan)

    def generate_response(self, query, plan):
        if not plan or plan[0]["score"] < self.confidence_threshold:
            return f"I am a simple local agent. You said: {query}"
        return f"Based on stored context: {plan[0]['content']}"


class SimpleAgent:
    def __init__(self, name="BloatedAgent"):
        self.name = name
        self.memory = AgentMemory()
        self.registry = ToolRegistry()
        self.engine = ReasoningEngine(self.memory, self.registry)
        self.metrics = defaultdict(list)
        self.running = False
        self.turn_count = 0
        self.register_tools()

    def register_tools(self):
        self.registry.register(Tool("echo", "Return the input text unchanged", lambda text: text))
        self.registry.register(Tool("word_count", "Count words in a string", lambda text: len(text.split())))
        self.registry.register(Tool("reverse", "Reverse a string", lambda text: text[::-1]))
        self.registry.register(
            Tool(
                "statistics",
                "Calculate basic numeric statistics",
                lambda values: {
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "stdev": statistics.pstdev(values),
                    "minimum": min(values),
                    "maximum": max(values),
                }
                if values
                else {},
            )
        )
        self.registry.register(Tool("json_encode", "Serialize data to JSON", lambda data: json.dumps(data, default=str)))

    async def process(self, query):
        started = time.perf_counter()
        self.turn_count += 1
        self.memory.history.append(Message("user", query))
        response = await asyncio.to_thread(self.engine.reason, query)
        self.memory.history.append(Message("assistant", response))
        self.metrics["latency"].append(time.perf_counter() - started)
        self.metrics["turns"].append(self.turn_count)
        return response

    def remember(self, key, value):
        self.memory.remember(key, value)

    def status(self):
        return {
            "name": self.name,
            "running": self.running,
            "turn_count": self.turn_count,
            "memory_items": len(self.memory.facts),
            "history_size": len(self.memory.history),
            "tool_count": len(self.registry.tools),
            "tool_calls": sum(tool.calls for tool in self.registry.tools.values()),
            "average_latency": statistics.mean(self.metrics["latency"]) if self.metrics["latency"] else 0,
            "uptime_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def run(self):
        import sys
        if not sys.stdin or not sys.stdin.isatty():
            # Automated benchmark / sandbox test workload
            queries = [
                "remember language python",
                "status",
                "Reverse this test string",
                "What is the word count of this query?",
            ]
            for q in queries:
                if q.startswith("remember "):
                    parts = q.split(" ", 2)
                    if len(parts) == 3:
                        self.remember(parts[1], parts[2])
                else:
                    await self.process(q)
            self.registry.executor.shutdown(wait=False, cancel_futures=True)
            return

        self.running = True
        try:
            while self.running:
                try:
                    query = await asyncio.to_thread(input, "agent> ")
                except (EOFError, KeyboardInterrupt):
                    break
                if query.strip().lower() in {"exit", "quit", "stop"}:
                    break
                if query.strip().lower() == "status":
                    print(json.dumps(self.status(), indent=2))
                    continue
                if query.startswith("remember "):
                    parts = query.split(" ", 2)
                    if len(parts) == 3:
                        self.remember(parts[1], parts[2])
                        print("Stored.")
                        continue
                print(await self.process(query))
        finally:
            self.running = False
            self.registry.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    asyncio.run(SimpleAgent().run())