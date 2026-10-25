# Tableau Offline AI (Windows)

An offline AI assistant for analyzing Tableau data sources and Excel/CSV files using local LLMs (via LM Studio or local OpenAI-compatible endpoints).

## 🚀 Quick Start

### Option 1: Run Without Building
Double-click `RUN_WITHOUT_BUILDING.bat` or run:
```bash
pip install -r requirements.txt
python TableauOfflineAI.py
```

### Option 2: Build Executable (.exe)
1. Double-click `BUILD_EXE.bat` (requires Python installed and an internet connection for dependencies, takes ~3 minutes).
2. The standalone app will appear in the `dist` folder: `TableauOfflineAI.exe`.
3. That single file is your standalone application—copy it anywhere and double-click to launch.

---

## 🛠️ How to Use

1. **Start Local LLM**:
   - Open [LM Studio](https://lmstudio.ai/) (or Ollama/LocalAI).
   - Load any model of your choice.
   - Start the **Local Server** (default port `1234`).
2. **Launch Tableau Offline AI**:
   - Open `TableauOfflineAI.exe` (or run `python TableauOfflineAI.py`).
   - Add your CSV or Excel files.
   - Enter your prompt or question, then click **Solve**.

---

## 📋 Requirements
- Python 3.10+
- Dependencies listed in `requirements.txt`:
  - `pandas`
  - `openpyxl`
  - `requests`
  - `pyinstaller` (for building)

---

## 🪵 Troubleshooting & Logs
Errors and diagnostic messages are logged directly to:
```
%USERPROFILE%\TableauOfflineAI_error.log
```
