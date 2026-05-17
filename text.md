
---

### 1. The Current Core Architecture

Your submission engine has transitioned from a hardcoded Python script into a production-ready, language-agnostic **Universal Evaluation Engine**:

* **The Dual-Handshake Protocol**: The system explicitly splits user actions at the gate. **Run Code** is volatile, testing code strictly against sample or custom inputs without modifying the database. **Submit Code** is permanent, creating an initially `PENDING` record in the database for a comprehensive hidden test evaluation.
* **Time-Tracking Isolation**: By utilizing a `UserProblemSession` model, the engine logs the `first_opened_at` timestamp the millisecond a student initializes a task. This accurately tracks individual time-to-solve data without creating phantom penalties if a user abandons a problem.
* **Database-Driven Language Configuration**: Execution profiles (`docker_image`, `compile_command`, `run_command`) reside entirely within your database using `{filename}` placeholders. This structure allows you to support multi-language environments (C++, Java, Rust, Go, JS) natively through the admin panel without modifying backend Python files.
* **Single-Container Batching**: Rather than spawning a heavy container for every individual test case, your backend dynamically creates a `runner.sh` script. It boots Docker **once**, compiles **once**, and runs all test cases sequentially inside a secure, isolated sandbox, dropping processing times from 10+ seconds to under 1 second.
* **Immutable Admin Vault**: The `SubmissionAdmin` interface is locked into a strict read-only audit configuration, ensuring that once a student hits submit, the records are entirely tamper-proof against any manual backend modifications.

---

### 2. The Three TLE Latency Optimization Methods

When code with infinite loops runs sequentially against multiple test cases, a basic runner stacks up severe execution delays (e.g., 5 test cases $\times$ 5-second limits = 25+ seconds). We mapped out three architectural remedies to resolve this bottleneck:

* **Method 1: Cumulative (Global) Timeout Capping**: Imposes a strict overarching time boundary (e.g., 10–12 seconds max) across the entire container run. Once the total clock pool is exhausted, the engine forcefully cuts execution, protecting your worker threads from hanging indefinitely.
* **Method 2: Parallel Process Execution**: Runs all test cases concurrently inside the sandboxed pod or runtime environment. This reduces total clock wait time to the duration of your longest single test case (~5 seconds), but introduces heavy CPU and RAM hardware spikes under high-concurrency conditions (such as 400–700 live users).
* **Method 3: Short-Circuiting (Early Abort)**: Implements a "fail-fast" policy inside your sequential execution scripts. The moment a submission fails or TLEs on any individual test case, the loop terminates immediately, throwing the final verdict and liberating system compute capacity.

---

### 3. Your Long-Term Roadmap & Structural Connections

Everything you are building feeds into a highly logical, multi-tiered pipeline:

1. **The Gatekeeper (Problem Rules / AST)**: Runs lightning-fast static analysis on the bare-metal server using parsers like Tree-sitter to reject illegal code structures before hitting the execution queue.
2. **The Forge (Docker / k3s Orchestration)**: Processes valid code inside lightweight, resource-constrained sandboxes using a fast asynchronous queue (Celery/Redis) to keep the primary web infrastructure responsive.
3. **The Vault (The Immutability Layer)**: Evaluates outcomes sequentially using the Verdict Engine, scoring against test cases or custom Special Judges, and records immutable values to the ledger.
4. **The Interface (Submission History & Live Leaderboards)**: Pulls data directly from the immutable submission tables to update user tracking HUDs and aggregate real-time leaderboard positions.
5. **The Analytics Suite (After-Event Reports)**: Collects metrics logged across execution logs and student sessions to compile automated event efficiency reports for your ACM club management.
6. **The Ecosystem (Community Forum & Daily Newsletters)**: Drives post-contest engagement and student profile personalization across the campus network.

---

### Current Scenario Verdict & Next Action

Following your strict architectural discipline of making a feature entirely feature-complete before shifting focus to the next component, you are currently positioned at the intersection of the **Engine Room** and the **User Interface**.

Your core multi-test case batch engine is officially complete, secure, and processing accurately in the background. The absolute best choice in the current scenario is to bridge this backend success directly out to your students.

**What is our immediate next move?** 1. Should we wire up the front-end **User Submission History Tracker view** so students can fully track, view, and read their real-time execution verdicts directly from their IDE workspace?
2. Or, before building that front-end view, do you want to inject the **Short-Circuiting (Early Abort)** logic directly into your backend execution loops to permanently fix the TLE latency behavior first?