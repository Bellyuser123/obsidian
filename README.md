# Obsidian

## Project Overview

**Obsidian** is a Django-based Competitive Programming / Online Judge platform. It is designed to host coding contests where users can solve problems, submit code, and view their rankings on a leaderboard.

---

## Core Components

### 1. Contest System

* Supports **Live**, **Upcoming**, and **Archived** contests
* Features a **Passkey system** for restricted contest entry
* Includes a **Leaderboard** that ranks users based on:

  * Problems solved
  * Time taken

---

### 2. Problem & Judging Data

* **Problem Models**

  * Contain detailed fields for:

    * Problem statements
    * Input/output formats
    * Constraints
    * Custom *Special Judge* scripts

* **TestCase Model**

  * Stores input/output pairs for validation
  * Supports:

    * Hidden test cases
    * Sample test cases

* **Problem Rules**

  * Allows defining constraints such as:

    * **"Must Use"** keywords
    * **"Forbidden"** keywords
  * Example:

    * Restricting `math.sqrt`
    * Disallowing auxiliary arrays

---

### 3. Advanced IDE Frontend

* A high-productivity **"Nether Forge" themed IDE** with a terminal-like aesthetic

* Supports multi-language syntax highlighting (Ace-like modes) for:

  * Python
  * C++
  * Java
  * Node.js
  * Rust

* Features:

  * Split-pane view for:

    * Problem description
    * Code editor & execution

---

### 4. User Profiles

* Extends the default Django user model
* Includes:

  * Academic metadata (e.g., `roll_no`)
  * `total_score` tracking across the platform

---

## Current Status

The project has a strong structural and aesthetic foundation, but some core backend logic is still in the **mockup phase**:

* **Judging Logic**

  * Code execution in a secure sandbox
  * Validation against test cases
  * ❌ *Not yet implemented*

* **IDE Interactivity**

  * `runCode` and `submitCode` currently return simulated results
  * ❌ *No real backend integration yet*

---

## Summary

Obsidian is a **well-designed and feature-rich shell** for a competitive programming platform. It is fully prepared for the integration of a backend code execution and judging engine.
