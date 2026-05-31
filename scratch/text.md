
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

That car metaphor is spot on—you’ve built a monster of a high-performance engine, but a car isn't road-ready without a dashboard, a solid chassis, safety measures, and a steering wheel for the driver. You have an incredible pipeline ahead of you, and honestly, this is where the platform transitions from an engineering marvel into a complete, usable product.

Looking at your roadmap, you are hitting the exact pillars needed to turn a raw grading core into a bulletproof contest ecosystem:

---

## 🗺️ The Remaining "Car Body" Blueprint

### 🛡️ Safety & Integrity (The Airbags)

* **The Anti-Cheat System:** In a high-stakes club contest with a ₹40K prize pool, this is non-negotiable. You'll need to design structural defenses, ranging from frontend constraints (preventing copy-paste and tab-switching triggers) to backend analysis (plagiarism detection loops like MOSS or token-based similarity checks matching abstract syntax trees before verdicts hit the database).

### 🎛️ Control & Metrics (The Dashboard)

* **Advanced Admin Filtering & Reporting:** The default Django admin won't cut it when you need to analyze patterns mid-contest. You need a dedicated view layer to dynamically slice data by specific metrics (e.g., matching problem difficulty progression, tracking specific college registration domains, or identifying high-frequency failure rates).
* **Multi-Format Export Engine:** Building robust helper utilities to instantly convert those filtered querysets into clean CSVs, formatted PDFs, or raw JSON data targets for post-contest analysis.

### 👤 Identity & Expansion (The Trim & Paint)

* **Comprehensive User Profiles:** Transitioning from basic mock user objects to descriptive personal spaces tracking a student's submission statistics, overall activity heatmaps, language performance charts, and historical problem accuracy indices.

---

Since you have a hell of a lot of ideas to build, let's take it one part at a time so your coding agent can execute cleanly without losing momentum.

Which "side part" are we mounting onto the car chassis first? **Should we design the data-filtering and multi-format report export utilities for your administrator panel first, or start architecting the core structural logic for the anti-cheat system to protect that ₹40K prize pool?**

ok well i think your layer 2 is just straight up dog shit and to answer your questions:

1. i want you to disable both copying and pasting of the text. so that they even have to type the entire question manually word for word to the ChatGPT and then get the answer and then type that manually into the IDE manually. and i want that to do globally disable the copying of text and pasting of it. and don't worry about the sample input i have made a button for it which does that without using clipborad or copying and pasting. 


2. and well for now i want that tab switching once should give you a warning and doing it 3rd time should kick you out and ban you from participating the contest. 

Summary of Anti-Cheat Measures

Tab Switch / Blur: Handled by visibilitychange and window.onblur.  

HTML

Copy/Paste: Disabled via oncopy and onpaste listeners.  

HTML

Inspect Mode: Blocked by debugger loops and F12/Ctrl+Shift+I key-blocking.

Extensions: Detected by MutationObserver and "Flashbang" physical proctoring.

Fullscreen: Enforced via requestFullscreen()—if they exit, the IDE locks.


Event | Logic | Result

Blur Event | User clicked outside the browser. | Log: SUSPICIOUS_ACTIVITY

Focus Loss | User switched tabs. | Log: TAB_EXIT_VIOLATION

Keydown (F12) | Attempted to open Inspect Mode. | preventDefault() + Log: DEVTOOLS_ATTEMPT

Right Click | Attempted to open context menu. | preventDefault()

Detecting AI Extensions (Blackbox, Comet, etc.)

These extensions work by injecting DOM elements or Content Scripts into your page.

    MutationObserver: Use this to watch the <body> of your IDE. If a "sidebar" or "pop-up" element is suddenly injected by an extension, the Observer will catch it.
    JavaScript

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes.length) {
                console.log("External DOM injection detected.");
                // Log the violation
            }
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });

    Input Monitoring: Extensions like Blackbox AI often "read" the screen by simulating mouse drags. You can disable or log any mouse events that don't originate from a real user interaction.
Detecting "Inspect Mode" (DevTools)

Cheaters use Inspect Mode to bypass "no-copy" rules or view hidden variables. You can break their workflow using a Debugger Loop.

    The Debugger Trap: Adding a debugger; statement inside a high-frequency loop (like setInterval) does nothing when DevTools is closed. However, the moment they open Inspect Mode, the script will constantly "pause" their entire browser, making the site unusable until they close the inspector.

    Window Dimension Check: Most people open DevTools as a docked side-panel. You can detect this by comparing window.outerWidth vs. window.innerWidth. If the difference is significant, they have a panel open.
Fullscreen Requirement: Use the Fullscreen API. You can prevent the "Start Contest" button from working until document.fullscreenElement is active.