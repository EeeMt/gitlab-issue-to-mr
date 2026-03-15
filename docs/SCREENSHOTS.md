# Dashboard Screenshots

This document provides a visual overview of the GIMR dashboard interface.

## Login Page

![Login](screenshots/login.png)

The login page supports GitLab OIDC authentication for secure dashboard access.

---

## Task Dashboard

![Task Dashboard](screenshots/task%20dashboard.png)

The main task dashboard displays all code generation tasks with filtering by project, priority, and status. Tasks are organized into P0, P1, and P2 priority tabs.

---

## Create Task

![Create Task](screenshots/create%20task.png)

Manual task creation page allows operators to create code generation tasks without GitLab issue association. Supports priority, target branch, and scheduled execution time configuration.

---

## Schedule Overview

![Schedule Overview](screenshots/schedule%20overview.png)

Visual timeline showing scheduled tasks and their execution windows. Allows operators to preview and manage upcoming task executions.

---

## Sessions Management

![Sessions](screenshots/sessions.png)

Active session management with login history and session lifecycle controls.

---

## Configuration

![Configuration](screenshots/configuration.png)

Runtime configuration page for managing:
- GitLab connection settings
- AI model parameters
- Worker concurrency limits
- OIDC authentication settings

---

## System Monitor

![System Monitor](screenshots/system%20monitor.png)

Real-time monitoring of:
- Active containers
- System resources
- Task execution status

---

## Access Management

![Access Management](screenshots/access%20management.png)

User access control interface for managing:
- User roles (admin, operator, viewer)
- Project-level permissions
- Shared page access

---

## Analytics

![Analytics](screenshots/ayalytics.png)

Task analytics dashboard showing:
- Task completion rates
- Execution time trends
- Success/failure statistics
