## 🚀 Tableau Offline AI v1.0.0 — Exam Helper Edition (Windows)

Tableau Offline AI is an offline AI assistant, practical exam guide, and schema relationship builder for Tableau Desktop using local LLMs (LM Studio / Ollama).

### 🎓 What's New in This Release

#### 1. Step-by-Step Practical Exam Helper
- **Concise, Structured Exam Answers**:
  - **FIELDS TO USE**: Explicitly categorizes required fields into `Dimension` (text, dates, IDs) and `Measure` (numbers with aggregations).
  - **STEP-BY-STEP SOLUTION**: Single-action numbered instructions detailing exact Tableau shelf placement (Rows, Columns, Color, Size, Label, Detail, Filters shelf).
  - **FINAL RESULT**: Clear visual description of the resulting chart or table for quick cross-checking during exams.
  - **CALCULATED FIELD / EXAM TIP**: Ready-to-paste Tableau formulas and exam-oriented tips for common pitfalls.
- **Quick Action Bar**:
  - `📋 Copy Full Answer`
  - `🔢 Copy Steps Only`
  - `⚡ Copy Formula`
  - `💾 Save Guide (.md)`
  - `🔍 Show Exact Facts`

#### 2. Interactive Tableau Formula Cheat Sheet
- **27 Curated Formulas Across 5 Categories**:
  - Level of Detail (LOD) Expressions (`FIXED`, `INCLUDE`, `EXCLUDE`)
  - Table Calculations (`RUNNING_SUM`, `PERCENT_OF_TOTAL`, `RANK`, `WINDOW_AVG`, `INDEX`)
  - String & Date Functions (`DATEPART`, `DATEDIFF`, `DATETRUNC`, `SPLIT`, `TRIM`, `UPPER`)
  - Conditional & Logical (`IF/THEN/ELSE`, `CASE/WHEN`, `ZN`, `IFNULL`)
  - Advanced Filtering & Top N (`RANK() <= 5`, `ISNULL`)
- **Dynamic Dataset Compatibility**:
  - Automatically compares formula field requirements against your loaded tables/sheets.
  - Displays instant visual badges: `✓ Ready to use` or `⚙️ Needs field mapping`.
  - Copy ready-to-paste formulas and implementation steps with one click.

#### 3. Smart Multi-Sheet Data Cleaning
- Automatically cleans multi-sheet Excel files (.xlsx, .xlsm, .xls) and CSVs.
- Detects genuine header rows below titles, drops empty columns/rows, and trims whitespace.
- Filters out bottom summary/total rows to avoid skewing sums and aggregations.
- Auto-derives essential business metrics like `Total Sales = quantity * unit_price` when missing.

#### 4. Relational Schema Modeling
- Automatically identifies primary keys and foreign keys across all loaded sheets.
- Generates loop-free relationship tree diagrams matching Tableau's logical data model.
- Provides copyable drag-and-drop relationship mapping instructions.

#### 5. Exact Fact Verification & 100% Offline Privacy
- Runs mathematical computations and aggregations in `pandas` first to ensure 0% hallucination.
- 100% offline — works seamlessly with LM Studio or Ollama on your local machine with zero external network access.

---

### 📦 How to Run
1. Download **`TableauOfflineAI.exe`** from the Assets below.
2. Double-click `TableauOfflineAI.exe` (no Python or package installation required).
3. (Optional) Run LM Studio or Ollama on `localhost:1234` for AI-assisted exam guidance.
