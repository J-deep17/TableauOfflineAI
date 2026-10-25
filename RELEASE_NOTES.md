## 🚀 Tableau Offline AI v1.0.0 — Exam Helper Edition (Windows)

Tableau Offline AI is an offline AI assistant, practical exam guide, and schema relationship builder for Tableau Desktop using local LLMs (LM Studio / Ollama).

### 🎓 What's New in This Release

#### 1. Multi-Turn Exam Chat & Follow-Up Assistant
- **Continuous Conversation**:
  - Ask exam questions and continue chatting if you get stuck on a step, formula, or filter.
  - Full multi-turn context retention allows follow-up questions like *"Where do I drag this in Rows?"*, *"Show the exact formula"*, or *"How do I fix this error?"*.
  - Quick-action follow-up chips for one-click prompts.
- **🗑️ Clear Conversation**:
  - Easily reset conversation history and verified facts with a single click when starting a new exam question.
- **💾 Save Chat Transcript**:
  - Export your entire exam conversation and steps to Markdown/Text.

#### 2. Reliable One-Click Formula Copying
- **Always Copies the Exact Formula**:
  - `🧮 Copy Formula` extracts formulas directly from latest responses across code blocks, inline definitions, or multiline calculations.
  - Also supports highlighting any formula or text in the chatbox and clicking `Copy Formula` to copy the selected text immediately.
  - Guaranteed Windows OLE clipboard registration via forced event pump commits.
- **Formula Cheat Sheet**:
  - 27 curated exam formulas (LOD expressions, Table Calculations, Date functions, Conditional logic).
  - Copy formula syntax or complete step-by-step calculated field creation instructions with one click.

#### 3. Deterministic 100% Offline Schema & Drag Guide
- **Fast, Instant Schema Mapping**:
  - Generates table relationship graphs and Tableau drag guides instantly using deterministic profiling rules without waiting on LLMs.
  - Highlights confirmed vs. uncertain relationships, union candidates, and bridge tables.
  - Interactive diagram with Fit to Screen, Zoom In/Out, and panning.

#### 4. Smart Multi-Sheet Data Cleaning
- Automatically cleans multi-sheet Excel files (.xlsx, .xlsm, .xls) and CSVs.
- Detects genuine header rows below title blocks, drops empty columns/rows, and trims whitespace.
- Filters out summary/total rows to avoid skewing aggregations.
- Audits and displays a full cleaning log for all loaded sheets.

#### 5. Exact Fact Verification & 100% Offline Privacy
- Runs mathematical computations and aggregations in `pandas` first to ensure 0% hallucination.
- 100% offline — works seamlessly with LM Studio or Ollama on your local machine with zero external network access.

---

### 📦 How to Run
1. Download **`TableauOfflineAI.exe`** from the Assets below.
2. Double-click `TableauOfflineAI.exe` (no Python or package installation required).
3. (Optional) Run LM Studio or Ollama on `localhost:1234` for AI-assisted exam guidance.
