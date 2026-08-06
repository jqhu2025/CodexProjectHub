# Codex Project Hub

A local-first desktop workspace for organizing Codex projects, conversations, and daily work without replacing Codex itself.

Codex Project Hub gives you a visual control layer for project classification and task planning. It reads local Codex metadata to show which conversations are active, then sends you back to the corresponding Codex conversation for the actual interaction and execution.

> **Platform:** Windows 10/11
>
> **UI:** PyQt5 desktop application
>
> **Network model:** local application; no web server and no listening port

## Preview

The screenshots below were rendered from the real application with isolated fictional demo data. They do not contain personal projects, file paths, account identifiers, or real Codex conversation IDs.

### Daily workspace

![Daily workspace with planned, active, and completed tasks](docs/images/daily-workspace.png)

### Projects and linked Codex conversations

![Project list with categories, linked conversations, and live status](docs/images/project-list.png)

## Why this project exists

Codex is the primary place for conversations and execution, but a growing set of folders and conversations can become difficult to scan as a portfolio. Codex Project Hub adds a lightweight organizational layer while preserving Codex as the final interaction surface.

The application focuses on four questions:

1. What projects do I currently have?
2. Which category does each project belong to?
3. What should I work on today?
4. Which Codex conversation is running, ready, or already completed?

## Features

### Project organization

- Three-level workflow: **category → project → Codex conversation**.
- Create, edit, hide, or remove project records without deleting folders from disk.
- Create, rename, delete, and reorder project categories.
- Move projects between categories at any time.
- Reorder projects inside a category.
- Search by project name, category, path, or next action.
- View all projects in a compact category-based overview.
- Expand an individual project only when conversation details are needed.

### Codex conversation awareness

- Reads active, non-archived Codex conversations from the local Codex state.
- Matches conversations to projects using Codex project metadata and working-directory paths.
- Displays the durable Codex conversation title instead of deriving a name from arbitrary message text.
- Uses three clear project/conversation states:

| State | Meaning |
| --- | --- |
| **Running** | Codex is currently processing work for the conversation. |
| **Completed** | The latest Codex run has stopped or completed. |
| **Linked** | The conversation is associated with the project but is not currently executing. |

- Opens a linked conversation through the `codex://threads/<id>` desktop deep link.
- Never writes to the Codex conversation database or modifies conversation content.

### Daily task planning

- Create tasks manually or plan them while working with Codex.
- Assign a task through the full hierarchy: category, project, and conversation.
- Organize the day into **Planned**, **In Progress**, and **Completed** columns.
- Automatically move a linked planned task to **In Progress** when Codex starts processing its conversation.
- Keep a daily activity record of planned, started, and completed work.
- Carry unfinished in-progress work to the next day while preserving the original day's record.
- Browse a different date without losing today's board.
- Edit, move, complete, or delete tasks directly from the board.

### Usage telemetry

- Shows the current Codex quota window, used percentage, remaining percentage, and reset time.
- Reads the official daily token bucket when it is available.
- Falls back to a local real-time token estimate when the official daily bucket is delayed.
- Marks estimated values with `*` and explains the source in a tooltip.

Local token estimates are derived from cumulative `token_count` events in Codex session logs. They are intended as a live operational indicator, not a billing statement.

### Desktop experience

- Native PyQt5 window with no browser shell.
- Light, high-contrast technical visual system.
- Responsive project cards and task columns.
- Fluent-style icons and keyboard-focus states.
- Periodic background refresh without blocking the main interface.

## Privacy and data boundaries

Codex Project Hub is designed to keep project-management data on the local machine.

It may read:

- local Codex project metadata;
- the local Codex thread index;
- local session logs needed to determine run state and estimate tokens;
- the project folders explicitly registered in the application.

It does **not**:

- upload project or conversation data;
- start a web server;
- listen on a network port;
- modify Codex threads or message content;
- delete project folders when a project is removed from the hub.

The following runtime files are deliberately excluded from Git because they may contain absolute paths, task notes, or Codex conversation IDs:

```text
data/projects.json
data/categories.json
data/today_tasks.json
data/project_layout.json
```

Only fictional `*.example.json` files are included in the repository.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- Codex Desktop for conversation synchronization and deep links
- PyQt5 5.15

## Installation

```powershell
git clone https://github.com/jqhu2025/CodexProjectHub.git
cd CodexProjectHub

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

Double-click:

```text
启动项目中心.cmd
```

Or launch it from PowerShell:

```powershell
python app_qt.pyw
```

The launcher looks for `pythonw.exe` first so the desktop window can run without an additional console window.

## Try the fictional sample data

The repository starts without personal project data. To populate it with the same fictional content used for the screenshots:

```powershell
Copy-Item data\categories.example.json data\categories.json
Copy-Item data\projects.example.json data\projects.json
Copy-Item data\project_layout.example.json data\project_layout.json
Copy-Item data\today_tasks.example.json data\today_tasks.json
```

The sample Windows paths do not need to exist for the project map and task board to render. Opening a folder naturally requires a valid local path.

## How synchronization works

1. The application reads the Codex Desktop project list and active thread index from the local Codex directory.
2. It builds a project catalog from Codex projects plus manually registered folders.
3. It associates each non-archived conversation with a project using Codex metadata and normalized working-directory paths.
4. It inspects recent local session events to determine whether a conversation is running, completed, or simply linked.
5. It refreshes the interface in the background and updates linked daily tasks when a run begins.
6. When you choose **Open Codex**, the application launches the corresponding `codex://threads/<id>` deep link.

Codex remains the source of truth for conversations. The hub stores only its own classification, ordering, and planning metadata.

## Local data files

| File | Purpose |
| --- | --- |
| `data/projects.json` | Project names, folders, categories, state, and next-action metadata. |
| `data/categories.json` | Editable category names and display order. |
| `data/today_tasks.json` | Daily tasks, status history, and optional project/conversation references. |
| `data/project_layout.json` | Project order and hidden-project settings. |

Files are written atomically through a temporary file and replacement step to reduce the risk of partial JSON writes.

## Repository layout

```text
CodexProjectHub/
├─ app_qt.pyw                 # Main PyQt5 application
├─ assets/                    # Visual assets used by the interface
├─ data/                      # Local runtime data and fictional examples
├─ docs/images/               # Sanitized README screenshots
├─ requirements.txt           # Python dependency declaration
└─ 启动项目中心.cmd             # Windows launcher
```

## Verification

Run a syntax check before committing changes:

```powershell
python -m py_compile app_qt.pyw
```

## Current limitations

- The application targets Windows and Codex Desktop's current local storage layout.
- Codex metadata formats may change between desktop releases.
- The official daily usage bucket can arrive later than real-time session activity.
- Token estimates from local logs can differ from official accounting.
- Deep-link navigation requires the Codex Desktop protocol handler to be registered.

## License

No open-source license has been selected yet. The repository remains all-rights-reserved unless a license file is added.
