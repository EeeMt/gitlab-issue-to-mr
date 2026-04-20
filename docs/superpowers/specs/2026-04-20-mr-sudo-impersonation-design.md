# MR Sudo Impersonation + Codify Label — Design Spec

## Problem Statement

All Merge Requests in Codify are created using a shared GitLab bot token. This means every MR is owned by the same bot user, and the actual task initiator (the developer who created the issue/task) cannot operate on the MR — they can't merge, close, or approve it without project-level permission overrides.

## Solution

Use the existing `gitlab_admin_token` with GitLab's `sudo` parameter to create and manage MRs as the initiating user. Additionally, label all Codify-created MRs with a "Codify" label for easy identification.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sudo scope | MR create + update + remove draft | Notes stay as bot (system notification feel) |
| No gitlab_user_id fallback | Use bot token (current behavior) | Backward-compatible for local-auth users |
| Label | Fixed "Codify", blue #6699cc | Simple, no config needed |
| Label missing | Auto-create in project | Seamless first-run experience |
| Sudo GL lifecycle | One per task execution, reused within task | Lightweight (no network on construct), no cache staleness |
| Label create failure | Log warning, don't block MR creation | Non-critical feature shouldn't fail the task |

## Architecture

### Sudo Flow

```
execute_task()
  ├─ task.initiator_gitlab_user_id exists?
  │   ├─ YES: sudo_gl = gitlab_client.create_sudo_gl(user_id)
  │   └─ NO:  sudo_gl = None (fallback to self.gitlab.gl)
  │
  ├─ ensure_project_label(project_id, "Codify", "#6699cc")
  │
  ├─ _create_mr_if_needed(task, issue, ..., sudo_gl=sudo_gl)
  │     └─ project = (sudo_gl or self.gitlab.gl).projects.get(project_id)
  │        project.mergerequests.create({..., labels: ["Codify"]})
  │
  ├─ _update_mr_description_for_issue(task, issue, db, sudo_gl=sudo_gl)
  │     └─ mr.title = ...; mr.description = ...; mr.save()
  │
  └─ _remove_mr_draft_status_for_issue(task, issue, sudo_gl=sudo_gl)
        └─ mr.title = mr.title.replace("Draft: ", ""); mr.save()
```

### New Methods in GitLabClient

```python
def create_sudo_gl(self, gitlab_user_id: int) -> Gitlab:
    """Create a Gitlab instance with admin token + sudo for impersonation.
    
    Args:
        gitlab_user_id: The GitLab user ID to impersonate.
    
    Returns:
        A Gitlab instance configured with sudo.
    """
    if not self.settings.gitlab_admin_token:
        raise ValueError("gitlab_admin_token is required for sudo operations")
    return gitlab.Gitlab(
        self.base_url,
        private_token=self.settings.gitlab_admin_token,
        sudo=str(gitlab_user_id),
        ssl_verify=get_ssl_verify(self.settings),
        keep_base_url=True,
    )

def ensure_project_label(self, project_id: int, label_name: str, color: str) -> None:
    """Ensure a label exists in the project, creating it if necessary.
    
    Args:
        project_id: GitLab project ID
        label_name: Label name (e.g., "Codify")
        color: Label color (e.g., "#6699cc")
    """
    project = self.get_project(project_id)
    try:
        project.labels.get(label_name)
    except GitlabGetError:
        try:
            project.labels.create({"name": label_name, "color": color})
            logger.info(f"Created label '{label_name}' in project {project_id}")
        except Exception as e:
            logger.warning(f"Failed to create label '{label_name}': {e}")
```

### Worker Changes

In `_create_mr_if_needed()`:
```python
def _create_mr_if_needed(self, task, issue, mr_iid, mr_web_url, *, sudo_gl=None):
    # ... existing logic ...
    
    # Use sudo GL if available, otherwise default
    gl = sudo_gl or self.gitlab.gl
    project = gl.projects.get(task.project_id)
    
    mr_response = project.mergerequests.create({
        "source_branch": issue.branch_name,
        "target_branch": target_branch,
        "title": mr_title,
        "description": initial_mr_desc,
        "remove_source_branch": True,
        "labels": ["Codify"],  # NEW
    })
```

Similar pattern for `_update_mr_description_for_issue()` and `_remove_mr_draft_status_for_issue()`.

### Ensure Label Timing

`ensure_project_label()` is called once per task execution, before MR creation, using the bot token (not sudo). This ensures the label exists regardless of the impersonated user's permissions.

## Compatibility

- **No migration needed** — no DB schema changes
- **No config changes** — uses existing `gitlab_admin_token`
- **Backward-compatible** — tasks without `initiator_gitlab_user_id` continue working as before
- **No frontend changes** — transparent to the UI

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `gitlab_admin_token` empty | Log warning, fall back to bot token |
| Sudo user doesn't exist in GitLab | GitLab returns 403/404, log error, fall back to bot token |
| Label creation fails | Log warning, create MR without label |
| Sudo GL MR creation fails | Log error, retry with bot token as fallback |

## Testing

- Unit tests for `create_sudo_gl()` — verify correct Gitlab config
- Unit tests for `ensure_project_label()` — existing + create + failure cases
- Modify existing worker tests to verify sudo is used when `initiator_gitlab_user_id` is present
- Verify fallback when `initiator_gitlab_user_id` is None
