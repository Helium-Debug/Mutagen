# MUTAGEN: The Experimental Evolution Engine for Code

> **AI proposes. MUTAGEN experiments. Memory makes it evolve.**

MUTAGEN is an AI-powered code optimization and evolutionary experimentation platform. Rather than trusting raw generative output or relying on speculative suggestions, MUTAGEN treats code mutation as a scientific, experimental evolution process. 

Every proposed candidate is statically analyzed, isolated in a secured execution sandbox, subjected to automated correctness test gates, statistically benchmarked, scored across multi-objective fitness dimensions, and recorded into persistent evolutionary memory.

---

## ⚡ Core Philosophy & Architecture

```
                                  MUTAGEN EVOLUTION LOOP
  ┌────────────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                        │
  │   [ 1. Analyze Source ] ───► [ 2. Retrieve Memory ] ───► [ 3. AI Mutation Engine ]     │
  │          │                           │                            │                    │
  │          ▼                           ▼                            ▼                    │
  │     AST Complexity             3-Layer Patterns            Gemini 2.5 / Providers      │
  │                                                                   │                    │
  │   [ 6. Multi-Objective ] ◄── [ 5. Benchmark Engine ] ◄── [ 4. Isolated Sandbox ]       │
  │         Fitness                      │                     (Docker / Test Gates)       │
  │          │                    Warmup + Reps                       │                    │
  │          ▼                                                        ▼                    │
  │   [ 7. Tournament Selection & Memory Persist ] ──► [ 8. Verifiable Certificate ]       │
  │                                                                                        │
  └────────────────────────────────────────────────────────────────────────────────────────┘
```

### Key Pillars

1. **Strict Sandboxing & Defense in Depth**: Code executions run in isolated Docker containers with non-root privileges, read-only root filesystems, dropped capabilities (`CAP_DROP=ALL`), disabled networking, and strict memory/CPU quotas.
2. **Mandatory Correctness Gate**: Speed and memory gains mean nothing if correctness tests fail. Passing tests is a mandatory binary precondition for candidate eligibility.
3. **Three-Layer Evolutionary Memory**:
   - **Project Memory**: Interface contracts, type requirements, and structural rules.
   - **Evolution Memory**: Past mutation attempts, failure logs, and stagnation lessons.
   - **Semantic Memory**: Searchable cross-project algorithmic optimization patterns.
4. **Verifiable Optimization Certificates**: Cryptographic SHA-256 fingerprinting guarantees that exported code matches tested benchmarks and prevents tampered metrics.
5. **Terminal-First Developer Experience**: Powered by Typer and Rich with real-time spinners, syntax-highlighted diffs, and benchmark comparison panels.

---

## 🚀 Quick Start

### Installation

Clone the repository and install with development dependencies:

```bash
# Clone the repository
git clone https://github.com/mutagen-engine/mutagen.git
cd Mutagen

# Install dependencies in editable mode
pip install -e ".[dev]"
```

### Environment Setup

Initialize your local configuration:

```bash
# Generate .env configuration file
mutagen init

# Check system dependencies and environment
mutagen doctor
```

Configure your `.env` file:
```dotenv
MUTAGEN_AI_PROVIDER=gemini
MUTAGEN_AI_MODEL=gemini-2.5-flash
GEMINI_API_KEY=your-gemini-api-key-here
MUTAGEN_DATABASE_URL=postgresql+psycopg://mutagen:mutagen@localhost:5432/mutagen
MUTAGEN_REDIS_URL=redis://localhost:6379/0
MUTAGEN_LOG_LEVEL=INFO
MUTAGEN_ARTIFACT_DIR=./artifacts
```

> **Note**: For zero-config local testing without external servers, `MUTAGEN_DATABASE_URL=sqlite:///mutagen.db` and `MUTAGEN_AI_PROVIDER=fake` work out of the box!

### Infrastructure (PostgreSQL & Redis)

Start the backing services using Docker Compose:

```bash
docker compose up -d
```

---

## 🛠️ CLI Command Reference

MUTAGEN provides an intuitive, rich terminal command interface:

### 1. Source Code Analysis
Analyze AST metrics, cyclomatic complexity, halstead metrics, and interfaces:
```bash
mutagen analyze examples/fibonacci.py
```

### 2. Evolutionary Code Optimization
Run multi-generation evolutionary optimization on a target file:
```bash
mutagen evolve examples/fibonacci.py \
  --objective speed \
  --generations 5 \
  --population 4 \
  --repetitions 5
```

### 3. Project Management
Group related source versions and experiments under projects:
```bash
# Create a project
mutagen project create my-optimizer --description "Core algorithms" --source examples/matrix_multiply.py

# List all projects
mutagen project list

# View project details
mutagen project show <project_id>
```

### 4. Experiment & Mutation Inspection
Inspect generations, diffs, and candidates:
```bash
# List experiments
mutagen experiment list

# View experiment details
mutagen experiment show <experiment_id>

# View syntax-highlighted diff of a candidate
mutagen mutation diff <candidate_id>

# Show best candidate result
mutagen results best <experiment_id>
```

### 5. Evolutionary Memory
Query and inspect the 3-layer memory system:
```bash
# View memory statistics
mutagen memory stats

# Search memory for patterns
mutagen memory search "memoization cache"
```

### 6. Optimization Certificates & Export
Export the best candidate and verify cryptographic integrity:
```bash
# Generate optimization certificate
mutagen certificate <experiment_id>

# Verify certificate authenticity
mutagen verify <experiment_id>

# Export the winning candidate source file
mutagen export <experiment_id> --output ./optimized_fibonacci.py
```

---

## 🧬 Benchmark Target Examples

MUTAGEN includes ready-to-evolve sample algorithms in the [`examples/`](file:///c:/Users/User/Desktop/Mutagen/examples) directory:

| Example | Baseline Algorithm | Evolutionary Target |
|---|---|---|
| [`examples/fibonacci.py`](file:///c:/Users/User/Desktop/Mutagen/examples/fibonacci.py) | Exponential recursive $O(2^n)$ | Linear iterative $O(n)$ / Matrix exponentiation $O(\log n)$ |
| [`examples/matrix_multiply.py`](file:///c:/Users/User/Desktop/Mutagen/examples/matrix_multiply.py) | Naive triple loop $O(n^3)$ | Transposed cache-friendly loop / Vectorization |
| [`examples/bubble_sort.py`](file:///c:/Users/User/Desktop/Mutagen/examples/bubble_sort.py) | Quadratic bubble sort $O(n^2)$ | Adaptive / Timsort / Quicksort $O(n \log n)$ |
| [`examples/prime_sieve.py`](file:///c:/Users/User/Desktop/Mutagen/examples/prime_sieve.py) | Trial division prime test | Sieve of Eratosthenes |

---

## 🧪 Testing & Verification

MUTAGEN comes with a complete unit, integration, security, and CLI test suite:

```bash
# Run all tests
pytest tests/ -v

# Run with test coverage report
pytest tests/ --cov=mutagen --cov-report=term-missing
```

Test categories include:
- `test_analysis.py`: AST static analysis and language detection
- `test_fitness.py`: Multi-objective scoring, tournament selection, correctness gating
- `test_ai.py`: FakeProvider, GeminiProvider parsing, output recovery
- `test_security.py`: Content hashing, input bounds, certificate tamper proofing
- `test_memory.py`: 3-layer evolutionary memory context retrieval
- `test_db.py`: Repositories and relational database persistence
- `test_benchmarking.py`: Statistical aggregation and comparison
- `test_cli.py`: Typer commands and Rich UI output
- `test_evolution.py`: Multi-generation end-to-end evolution engine integration

---

## 🔒 Security Model

- **No Arbitrary Host Execution**: Untrusted AI-generated code is never executed directly in the host environment.
- **Resource Hardening**: Process quotas for CPU time, memory limits, and process limits are enforced on all sandbox executions.
- **Path Sanitization**: Source paths are checked against directory traversal patterns.
- **Immutable Hashes**: All candidates and original code versions are indexed by SHA-256 digests.

---

## 📄 License

MIT License. Built with ❤️ for AI-assisted engineering and evolutionary computing.
