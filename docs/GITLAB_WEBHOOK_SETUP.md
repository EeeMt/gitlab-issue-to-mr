# Codify

## GitLab Webhook Configuration

To receive `@ai-bot` commands from GitLab Issue comments, you need to configure a webhook.

### Steps to Configure

1. **Navigate to your GitLab project**
   - Go to your GitLab instance
   - Select the project you want to enable the bot for

2. **Create a webhook**
   - Go to **Settings** > **Webhooks**
   - Click **Add webhook**

3. **Configure the webhook**
   - **URL**: `https://your-backend-url/api/webhook/gitlab`
   - **Secret token**: Enter a secure token (will be used as `GITLAB_WEBHOOK_SECRET`)
   - **Trigger**: Select **Comments**
   - Check the following comment events:
     - [x] Issue comments
     - [ ] Merge request comments
     - [ ] Snippet comments

4. **Save the webhook**
   - Click **Add webhook**
   - Test the webhook with the "Test" button

### Required Environment Variables

In your `.env` file, set:

```bash
# GitLab Configuration
GITLAB_URL=https://gitlab.example.com
GITLAB_BOT_TOKEN=glpat-your-personal-access-token
GITLAB_WEBHOOK_SECRET=your-webhook-secret-token
```

### GitLab Bot Token Permissions

The bot token needs the following scopes:
- `api` - Full API access
- `read_repository` - Read repository
- `write_repository` - Write to repository

### Testing the Webhook

After configuring, test by adding a comment to an issue:

```
@ai-bot create a hello world function
```

The bot should:
1. Create a task in the database
2. Spawn a worker container to process the request
3. Create a branch and push code
4. Create a Merge Request
5. Reply to the issue with the MR link
