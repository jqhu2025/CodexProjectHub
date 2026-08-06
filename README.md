# Codex Project Hub

A local Windows desktop companion for organizing Codex projects, conversations, and daily tasks.

Codex remains the main interface for conversation and execution. This application provides project classification, task planning, status monitoring, and direct links back to the corresponding Codex conversation.

## Screenshots

### Daily tasks

![Daily task workspace](docs/images/daily-workspace.png)

### Projects and conversations

![Projects and linked Codex conversations](docs/images/project-list.png)

All screenshots use fictional sample data. They do not contain real project paths, account information, or Codex conversation IDs.

## Features

### Project management

- Organize work as **category → project → Codex conversation**.
- Create, edit, remove, and reorder projects.
- Create, rename, delete, and reorder categories.
- Move projects between categories.
- Search projects by name, category, path, or next action.
- Expand a project to view its linked Codex conversations.

Removing a project from the application does not delete its folder or Codex conversations.

### Daily tasks

- Create tasks for any date.
- Associate a task with a category, project, and optional Codex conversation.
- Use three task states: **Planned**, **In Progress**, and **Completed**.
- Automatically move a linked task to **In Progress** when Codex starts working on its conversation.
- Keep a daily activity record.
- Carry unfinished in-progress tasks to the next day while preserving previous records.

### Codex integration

- Read active, non-archived conversations from the local Codex state.
- Match conversations to projects using Codex metadata and working-directory paths.
- Display the saved Codex conversation title and current run state.
- Open a conversation with the `codex://threads/<id>` desktop deep link.
- Show running, completed, and linked states.
- Read Codex quota usage and reset time.
- Estimate current-day tokens from local session logs when the official daily bucket is delayed.

The application only reads Codex metadata and session activity. It does not modify Codex conversations or databases.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- PyQt5 5.15
- Codex Desktop for conversation synchronization and deep links

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

Double-click `启动项目中心.cmd`, or run:

```powershell
python app_qt.pyw
```

The Windows launcher uses `pythonw.exe` when available so the application can run without an additional console window.

## Sample data

The repository does not include personal runtime data. To load the fictional data used in the screenshots:

```powershell
Copy-Item data\categories.example.json data\categories.json
Copy-Item data\projects.example.json data\projects.json
Copy-Item data\project_layout.example.json data\project_layout.json
Copy-Item data\today_tasks.example.json data\today_tasks.json
```

The sample project paths do not need to exist unless you use the **Open Folder** action.

## Task and conversation states

| State | Description |
| --- | --- |
| Running | Codex is currently processing the linked conversation. |
| Completed | The latest Codex run has stopped or completed. |
| Linked | The conversation belongs to the project but is not currently running. |

## Local data and privacy

Runtime data is stored in the `data` directory:

| File | Contents |
| --- | --- |
| `data/projects.json` | Project names, categories, local paths, and status. |
| `data/categories.json` | Custom category names and order. |
| `data/today_tasks.json` | Daily tasks and optional conversation references. |
| `data/project_layout.json` | Project order and hidden-project settings. |

These files may contain local paths or Codex conversation IDs and are excluded by `.gitignore`. Only fictional `*.example.json` files are committed.

The application does not start a web server, listen on a network port, or upload local project data.

## Project structure

```text
CodexProjectHub/
├─ app_qt.pyw
├─ assets/
├─ data/
├─ docs/images/
├─ requirements.txt
└─ 启动项目中心.cmd
```

## Development

Check the Python source before committing changes:

```powershell
python -m py_compile app_qt.pyw
```

The application currently targets Windows and the local storage format used by Codex Desktop. A Codex update may require adjustments to local metadata readers.

## License

No open-source license has been selected. The repository is all-rights-reserved unless a license file is added.
