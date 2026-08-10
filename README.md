# Codex Project Hub

A local Windows desktop companion for organizing Codex projects, conversations, and daily tasks.

Codex remains the main interface for conversation and execution. This application provides project classification, task planning, status monitoring, and direct links back to the corresponding Codex conversation.

## Screenshots

### Daily tasks

![Daily task workspace](docs/images/daily-workspace.png)

### Quick open

![Keyboard-first project, task, conversation, and command search](docs/images/quick-open.png)

### Daily review

![Codex-generated daily review dialog](docs/images/daily-summary-dialog.png)

### Projects and conversations

![Projects and linked Codex conversations](docs/images/project-list.png)

### Project workbench

![Project goals, next action, tasks, and Codex conversations](docs/images/project-workbench.png)

### Running conversations

![Running Codex conversation manager](docs/images/running-conversations.png)

All screenshots use fictional sample data. They do not contain real project paths, account information, or Codex conversation IDs.

## Features

### Project management

- Organize work as **category → project → Codex conversation**.
- Press **Ctrl+K** from anywhere to search projects, current task records, Codex conversations, and common workspace commands in one keyboard-first palette. Search covers project objectives and next actions, task notes and outcomes, and conversation summaries; opening a result returns to the existing project workbench, task audit, or Codex conversation instead of creating a parallel workflow.
- Create, edit, archive, restore, and reorder projects.
- Create, rename, delete, and reorder categories.
- Move projects between categories.
- Treat category renames and deletions as portfolio-wide taxonomy migrations: active, archived, and locally retained projects move together with linked task labels, project snapshots, and saved ordering. Every affected project receives an auditable category decision, and rolling back a project-level category decision can safely restore a category that was previously removed.
- Give a Codex-synchronized project a local display name without changing its Codex source identity, folder, or conversations. The original Codex name remains recoverable from the editor, and every explicit rename or restore is recorded in project decision history and can be rolled back.
- Define a project objective, optional verifiable acceptance criteria, management priority, lifecycle state, execution stage, health, blocker, and concrete next action. Codex can propose the criteria from read-only project evidence, while legacy projects remain valid until the user chooses to strengthen their closeout contract.
- Keep the default project page simple: category cards contain project names, Codex conversation counts, and live state only. Open a project when its conversations or details are actually needed.
- Keep objectives, acceptance criteria, lifecycle state, health, blockers, and next actions inside the project workbench instead of turning the portfolio overview into a management cockpit.
- Retain focus calibration, risk handling, lifecycle review, and decision history as optional, auditable tools for users who need them; they do not create recurring chores on the default home or project pages.
- Keep the default home screen deliberately light: Codex quota and live status, yesterday's compact review, and one three-state daily task board. Portfolio calibration, risk handling, lifecycle decisions, and data repair remain available in project-specific or on-demand workflows instead of becoming recurring dashboard chores.
- Avoid duplicate home controls. Task history, the recycle bin, and rare association repair share one overflow menu; the visible board shows plain task counts rather than WIP ratios or management warnings.
- Detect quiet active projects from their latest task transition, Codex activity, or deliberate review. A compact batch summary separates projects that can be paused from those protected by unfinished tasks before the first decision. The neutral lifecycle queue can confirm the project remains active, pause it without deleting anything, defer the decision, or inspect the full workbench without abandoning the current calibration batch; inactivity never changes status automatically and is never labelled as project risk.
- Keep task links stable when Codex refreshes a project's current identifier.
- Promote a project's concrete next action into today's plan with one click, with duplicate protection and automatic handoff back to the next project decision when the task is completed.
- Enforce one live task per declared project next action across all dates. Scheduling an action that already exists navigates to its current record, while restoring an older rollover snapshot preserves history without reviving duplicate work.
- Detect when today's in-progress work diverges from the project's declared next action without mislabelling the difference as risk. The batch header states the number of candidate tasks and how many projects require a choice between several live directions. A guided reconciliation queue can adopt the live task as the new project direction—binding its completion to the next project handoff—or explicitly retain the existing direction; inspecting the project returns to the same calibration item, both choices remain human-controlled and auditable, and the reminder returns only when the underlying work changes again.
- Ask Codex to inspect a project in read-only, ephemeral mode and suggest its objective, stage, health, blocker, and next action; suggestions remain editable and require confirmation before saving.
- Run a portfolio-wide Codex governance pass over selected projects with missing decisions. Analysis is sequential and read-only, every proposed field is reviewed before application, existing human decisions are never overwritten, and gaps are rechecked at write time to reject stale suggestions.
- Resolve **Missing Next Action** as a guided decision queue instead of a project-list filter. Each batch focuses on at most five active projects, distinguishes folders that Codex can inspect from projects that need manual input, opens the existing review-before-write governance flow for one project at a time, and returns to the same batch after either Codex analysis or workbench editing. Saving a concrete action advances automatically; an empty path is never mistaken for the application working directory.
- Open one project workbench for conversations, the current next action, and optional project details. The category overview remains a neutral directory and never asks the user to interpret management commands while scanning projects.
- Keep a local, source-labelled history of real project-decision changes, including manual edits, Codex suggestions, category moves, and completed next-action handoffs.
- Use event-driven project review instead of calendar chores. A missing first baseline or an elapsed number of days never creates a task by itself; the queue appears only when necessary project information is missing or a comparable objective, acceptance criterion, stage, health, blocker, or next action actually changed.
- Establish the comparison baseline automatically on a complete project save or reviewed Codex update. Legacy projects without a baseline remain usable and do not generate setup work.
- Show the exact changed fields and current execution evidence before confirmation. Projects with a real task-to-direction conflict use the dedicated alignment flow; unchanged projects stay silent.
- Treat old unverified attention flags as neutral legacy data. Only a deliberately confirmed current risk is surfaced as an active warning.
- Track each blocker from first confirmation through resolution. Editing the reason keeps the original clock, project views show the live duration, and a guided resolution action restores normal health only after capturing a concise explanation of how the blocker was cleared. The original blocker, elapsed time, resolution note, and timestamp remain available for audit and daily review evidence.
- Restore any recorded project decision selectively: only fields touched by that event are rolled back, newer conflicting edits are disclosed before confirmation, and the rollback is preserved as a new audit event.
- Use a recoverable project archive for both Codex-synchronized and manually created projects, preserving management metadata, category placement, local files, and conversation links. Every new archive and restore action enters the unified decision history with its timestamp and a frozen snapshot of project status, stage, next action, blocker, and confirmed closeout outcome; the archive shows cycle counts while legacy records remain honestly marked as time unknown. Projects with unfinished tasks or running Codex conversations must close that live work first, preventing archived projects from leaving orphaned activity records.
- Close a project with an explicit, human-confirmed delivery outcome instead of a status flag alone. The closeout stores the original completion time, supports outcome revisions, appears in the project workbench and handoff context, and enters the unified audit history. Reopening retires the current completion claim while preserving the previous outcome as historical evidence.
- Confirm closeout against the project's stated objective and, when defined, its verifiable acceptance criteria. The completion record freezes the objective, acceptance criteria, acceptance time, and delivered outcome together, so later edits or a reopen cannot erase the basis on which the project was declared complete.
- Enforce coherent project decisions: blockers control health automatically, completed projects close their execution fields, linked open tasks remain untouched for deliberate follow-up, and completed projects cannot schedule new work until they are reopened.
- Search projects by name, category, path, objective, acceptance criteria, next action, conversation title, or conversation summary.
- Filter projects by running, completed, linked, or unlinked state.
- Expand a project to view its linked Codex conversations.
- Continue a project by copying its handoff context and opening the running or most recent Codex conversation.

Archiving a project removes it from the active portfolio without deleting its management record, folder, or Codex conversations. Archived projects can be restored from the project page.

### Daily tasks

- Create tasks for any date.
- Associate a task with a category, project, and optional Codex conversation.
- Use three task states: **Planned**, **In Progress**, and **Completed**.
- Create a task directly in any board column with that state preselected.
- Drag a task by its handle to prioritize it within a column or move it between Planned, In Progress, and Completed; the saved order survives refreshes and restarts, while the status selector remains an accessible fallback.
- Keep past planned work visible instead of silently rolling it forward or letting it disappear into history. Open the review from Ctrl+K, then deliberately reschedule, edit, or leave each item unchanged. A move to today offers a time-limited undo in both the review dialog and status bar, and the reversal is retained as a second auditable schedule event.
- Preserve every planned-date adjustment in a separate schedule audit. Rescheduling never fabricates a task-state transition, and Codex daily reviews receive the change only as planning evidence—not as completed work.
- Retain the configurable soft WIP analysis as an on-demand diagnostic, not a daily board requirement. It never blocks a legitimate manual or Codex transition; if opened, it protects running Codex work and explains reversible reduction suggestions from runtime state, project priority, and board order.
- Undo a recent manual status move from the status bar; reopening a completed project-next-action task restores the project handoff unless a newer next action already exists.
- Automatically move a linked task to **In Progress** when Codex starts working on its conversation.
- Keep a daily activity record.
- Record every real task-state transition with its source—manual selection, Kanban drag, task editing, Codex auto-start, project handoff, review suggestion, or daily rollover—and feed that evidence into daily reviews.
- Record a concise, verifiable completion outcome after a task is finished. Outcomes keep their own revision history, appear compactly on completed cards, feed Codex daily reviews as stronger evidence than planning notes, and follow project-next-action handoffs back into the project workbench.
- Keep completion lightweight without fabricating evidence: a task may move to **Completed** immediately, while Ctrl+K can surface completed work that still lacks an actual delivery, finding, or verification result.
- Preserve a project identity snapshot on every linked task. Current links display the latest project name; removed or changed links retain the name recorded with the task and are explicitly marked as historical instead of silently becoming "Unlinked". Resolvable legacy tasks are backfilled without altering their activity timestamps, while ambiguous records are never guessed and remain available for manual relinking.
- Persist the stable local project identity when tasks are created or edited, rather than a replaceable Codex sidebar identifier. If an older link still becomes orphaned, a compact data-integrity control can repair several tasks in one review; a unique current Codex-conversation match is recovered automatically, ambiguous links always require human confirmation, archived projects remain valid historical targets, and every repair gets its own audit event without changing task status or activity time.
- Treat a rolled-over task as one continuous work item: earlier daily snapshots remain available as read-only historical evidence, expose a direct jump to the latest record, and never count as unfinished work or trigger project handoffs in pause, archive, and closeout decisions.
- Open a read-only task record from the board, daily history, or recycle bin to inspect planning notes, source-labelled status transitions, the current completion outcome, and every outcome revision. Reopened tasks keep retired outcomes clearly historical instead of presenting them as current evidence.
- Move unwanted tasks to a recoverable recycle bin instead of deleting their daily record; archived tasks retain their original date, three-state status, ordering context, and complete transition history while remaining excluded from boards, workload counts, and generated reviews.
- Carry unfinished in-progress tasks to the next day while preserving previous records.
- Automatically summarize the previous day's tasks through a user-configured fixed Codex conversation.
- Include audited project reviews, direction reconciliations, closeouts, and real objective/stage/health/next-action changes in the daily evidence packet. Management decisions are counted separately from tasks and conversations; only a human-confirmed project closeout is accepted as project-level completion evidence.
- Keep the home review compact and open the full completed / in-progress / next-focus breakdown on click.
- Convert a Codex-generated next-focus suggestion into today's plan without blind automation: each suggestion opens the normal task editor for confirmation, preselects a project only when the name match is unambiguous, records the source summary date and original suggestion, and prevents the same review item from creating duplicate tasks even if its task title is later edited.
- Show immediate progress and failure feedback when a review is regenerated, then write the structured result back into the workspace.

### Codex integration

- Read active, non-archived user conversations from the local Codex state.
- Exclude Codex subagent and guardian threads from the project list.
- Match conversations to projects using Codex metadata and working-directory paths.
- Display the saved Codex conversation title and current run state.
- Click the global workspace status to inspect every running conversation and open it in Codex.
- Open a conversation with the `codex://threads/<id>` desktop deep link.
- Show running, completed, and linked states.
- Read the supported Codex quota endpoint for used capacity, remaining capacity, plan type, and reset time without waiting on retired App Server methods.
- Estimate current-day tokens from local session logs by walking backward only through that day's token events, then tail only newly appended records on later refreshes instead of rescanning multi-gigabyte conversations.
- Keep quota and token provenance explicit: a temporary quota failure retains the last successful capacity snapshot, still refreshes locally estimated Tokens, and exposes the actual retry reason instead of presenting missing data as zero usage.
- Generate the previous day's review through a configured Codex conversation and store its structured response locally.
- Send manual regeneration requests visibly through Codex Desktop, then write the reply back into the dashboard.
- Include completed work, active work, and concrete next-step evolution suggestions in every review.
- Treat a human-recorded task outcome as primary completion evidence while keeping plans and notes clearly separated from actual results.
- Combine dated planning records with every user Codex conversation that was actually active that day, using per-record timestamps instead of a conversation's latest-modified date.
- Show the number of covered work items, planning tasks, Codex conversations, and user turns before the review.

### Local reliability

- Save every project, task, layout, review, and decision document with an atomic same-directory replacement, so an interrupted write never leaves a half-written primary file.
- Keep the previous valid version as a rolling local safety copy under `data/.backups`.
- Fall back to that known-good copy when a primary JSON document is missing or malformed, and show one concise recovery notice in the application.
- Surface an explicit data warning when neither copy is readable instead of silently presenting an empty workspace.

The application reads Codex metadata and session activity. It never edits Codex databases directly. The optional daily-summary feature sends one prompt to the conversation ID configured by the user.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- PyQt5 5.15
- Codex Desktop for conversation synchronization and deep links
- A current Codex CLI installation for automatic background daily summaries
- A running Codex Desktop window for visible manual regeneration

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

If Codex is installed in a custom location, set `CODEX_EXECUTABLE` before launching:

```powershell
$env:CODEX_EXECUTABLE = "C:\path\to\codex.exe"
python app_qt.pyw
```

### Configure the fixed daily-summary conversation

Copy the local settings template and place the ID of the Codex conversation that should generate daily reviews:

```powershell
Copy-Item data\settings.example.json data\settings.json
```

```json
{
  "dailySummaryThreadId": "your-codex-thread-id",
  "portfolioFocusCapacity": 3,
  "portfolioInactivityDays": 14,
  "taskWipLimit": 3
}
```

The conversation ID can also be provided through `CODEX_HUB_SUMMARY_THREAD_ID`. Runtime settings and generated summaries are ignored by Git.

## Sample data

The repository does not include personal runtime data. To load the fictional data used in the screenshots:

```powershell
Copy-Item data\categories.example.json data\categories.json
Copy-Item data\projects.example.json data\projects.json
Copy-Item data\project_layout.example.json data\project_layout.json
Copy-Item data\project_decisions.example.json data\project_decisions.json
Copy-Item data\today_tasks.example.json data\today_tasks.json
Copy-Item data\settings.example.json data\settings.json
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
| `data/projects.json` | Project identity, local paths, objective, acceptance criteria, management state, and current closeout evidence. |
| `data/categories.json` | Custom category names and order. |
| `data/today_tasks.json` | Daily tasks and optional conversation references. |
| `data/daily_summaries.json` | Codex-generated reviews for previous workdays. |
| `data/settings.json` | Local configuration, including the optional summary conversation ID, strategic-focus capacity, active-portfolio inactivity threshold, and daily task WIP limit. |
| `data/project_layout.json` | Project order and recoverable archive settings. |
| `data/project_decisions.json` | Local audit trail for real project-name, objective, acceptance-criteria, stage, health, blocker, category, next-action, lifecycle, and project-closeout events. |

These files may contain local paths or Codex conversation IDs and are excluded by `.gitignore`. Only fictional `*.example.json` files are committed.

Before replacing an existing valid document, the application stores its previous version in `data/.backups`. These safety copies are local, ignored by Git, and intended for single-file recovery rather than cloud synchronization or long-term version history.

The application does not start a web server or listen on a network port. When daily summaries are enabled, the previous day's task packet is sent to the user-selected Codex conversation; other runtime data remains local.

## Project structure

```text
CodexProjectHub/
├─ app_qt.pyw
├─ assets/
├─ codex_hub/
│  ├─ management.py
│  ├─ navigation.py
│  ├─ portfolio.py
│  ├─ runtime.py
│  ├─ desktop_bridge.py
│  └─ storage.py
├─ data/
├─ docs/images/
├─ tests/
├─ requirements.txt
└─ 启动项目中心.cmd
```

## Development

Check the Python source before committing changes:

```powershell
python -m py_compile app_qt.pyw
python -m unittest discover -s tests -v
```

Project decisions, task transitions, daily rollover, and next-action handoffs are isolated in the Qt-independent `codex_hub/management.py` domain module. Global project, task, and conversation search ranking lives in the Qt-independent `codex_hub/navigation.py` module. Portfolio focus, next-action commitment, lifecycle activity evidence, stable task-to-project matching, and task WIP capacity live in the separate Qt-independent `codex_hub/portfolio.py` module. Codex session discovery and state classification live in `codex_hub/runtime.py`; unchanged session-log tails are cached, and periodic refreshes use indexed user threads instead of recursively scanning the complete Codex session directory. Quota protocol handling and incremental local token telemetry live in the Qt-independent `codex_hub/usage.py` module. Desktop deep-link handling is separated in `codex_hub/desktop_bridge.py`. Atomic JSON persistence and rolling recovery copies live in the Qt-independent `codex_hub/storage.py` module.

The 15-second local synchronization loop is incremental. An unchanged Codex session scan no longer triggers a second workspace refresh; unchanged project and task signatures repaint no pages; and real changes coalesce navigation, portfolio, project-map, and task-board updates into one render pass. The signature also carries an hourly time bucket so duration- and review-sensitive management signals still advance without unnecessary continuous repainting.

The application currently targets Windows and the local storage format used by Codex Desktop. A Codex update may require adjustments to the local metadata readers.

## License

No open-source license has been selected. The repository is all-rights-reserved unless a license file is added.
