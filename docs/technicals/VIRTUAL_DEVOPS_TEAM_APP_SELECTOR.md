# Virtual DevOps Team - Application Selector Implementation

## Summary

Added application selector to Virtual DevOps Team dialog to ensure actions are executed in the correct user environment for the specific selected application.

## Changes Made

### 1. Dashboard HTML (`templates/dashboard.html`)

#### Added Application Selector
```html
<select id="virtualAdvisorAppSelect">
  <option value="">-- Select Application --</option>
  {% for app in applications %}
  <option value="{{ app[1] }}">{{ app[1] }}</option>
  {% endfor %}
</select>
```

**Layout**: Application selector + Action selector + USER_ID display

#### Updated JavaScript Function
Modified `sendVirtualAdvisorMessage()` to:
- Require application selection before sending
- Calculate application deployment path: `/home/ubuntu/deployments/{username}/{app-name}`
- Include application context in message: `[ACTION] [APP:name] [PATH:path] message`
- Pass `application_name` and `application_folder` to backend API

### 2. Backend API (`src/routes/api_routes.py`)

#### Updated `/api/qchat_devops` Endpoint
- Accepts `application_name` and `application_folder` parameters
- Builds description with application context
- Passes to `process_qchat_devops()` function

### 3. Processing Function (`src/automorph_application.py`)

#### Enhanced `process_qchat_devops()`
- Extracts application folder from description
- Includes folder path in prompt for AI Chat
- Ensures commands execute in correct application directory

## User Flow

### Before
1. User selects action (PS/START/STOP/etc.)
2. User types message
3. System tries to determine which application

### After
1. User selects **application** from dropdown
2. User selects **action** (PS/START/STOP/etc.)
3. User sees **USER_ID**
4. User types message
5. System executes in: `/home/ubuntu/deployments/{username}/{selected-app}/`

## Visual Layout

```
┌──────────────────────────────────────────────────┐
│ 💡 Virtual DevOps Team                       ✕   │
├──────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────┐ │
│ │ Application: [Select App ▼]                 │ │
│ │ Action: [PS ▼]        USER_ID: 5            │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ [Chat Messages Area]                             │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ Ask your question...                         │ │
│ └──────────────────────────────────────────────┘ │
│ [Send Request]                                   │
└──────────────────────────────────────────────────┘
```

## Message Format

### Frontend to Backend
```json
{
  "message": "[PS] [APP:MyApp] [PATH:/home/ubuntu/deployments/john/myapp] check status",
  "application_name": "MyApp",
  "application_folder": "/home/ubuntu/deployments/john/myapp"
}
```

### Backend Processing
```python
description = "Application: MyApp, Path: /home/ubuntu/deployments/john/myapp"
process_qchat_devops(
    message=full_message,
    user_id="5",
    user_name="John Doe",
    user_email="john@example.com",
    description=description
)
```

### AI Chat Prompt
```
You are an autonomous DevOps agent...

User Request: [PS] [APP:MyApp] [PATH:/home/ubuntu/deployments/john/myapp] check status

Application Folder: /home/ubuntu/deployments/john/myapp

Follow the instructions below to execute the PS action:
[Context from PS_context.md]

IMPORTANT: Execute all commands in the application folder: /home/ubuntu/deployments/john/myapp
```

## Benefits

✅ **User-Specific Execution** - Commands run in user's deployment folder
✅ **Application Isolation** - Each app has its own environment
✅ **Clear Context** - No ambiguity about which app to manage
✅ **Consistent Paths** - Uses same path structure as deployment system
✅ **Error Prevention** - Can't execute without selecting app

## Example Usage

### Check Status
```
Application: AI-HACCP
Action: PS
Message: "What's the current status?"
→ Executes in: /home/ubuntu/deployments/john/ai-haccp/
```

### Start Application
```
Application: MyWebApp
Action: START
Message: "Deploy the application"
→ Executes in: /home/ubuntu/deployments/john/mywebapp/
```

### View Logs
```
Application: Dashboard
Action: LOGS
Message: "Show me the last 100 lines"
→ Executes in: /home/ubuntu/deployments/john/dashboard/
```

## Path Calculation

```javascript
const username = '{{ username }}';  // From session
const selectedApp = 'MyApp';        // From dropdown
const appFolder = `/home/ubuntu/deployments/${username}/${selectedApp.toLowerCase().replace(/\s+/g, '-')}`;
// Result: /home/ubuntu/deployments/john/myapp
```

## Validation

### Frontend Validation
- Application must be selected before sending
- Shows error if no application selected
- Displays selected app in chat

### Backend Validation
- Receives application_name and application_folder
- Logs application context
- Passes to processing function

## Testing

### Test Application Selection
1. Open Virtual DevOps Team
2. Try to send without selecting app → Error message
3. Select application → Enabled
4. Send message → Success

### Test Path Calculation
1. Select "AI-HACCP" → Path: `/home/ubuntu/deployments/john/ai-haccp/`
2. Select "My Web App" → Path: `/home/ubuntu/deployments/john/my-web-app/`
3. Verify paths in logs

### Test Actions
For each action (PS/START/STOP/RESTART/LOGS):
1. Select application
2. Select action
3. Send request
4. Verify execution in correct folder

## Comparison with Virtual Developer

| Feature | Virtual Developer | Virtual DevOps Team |
|---------|------------------|---------------------|
| Purpose | Code modifications | App management |
| App Selector | ✅ Yes | ✅ Yes (NEW) |
| Action Selector | ❌ No | ✅ Yes |
| USER_ID Display | ❌ No | ✅ Yes |
| Auto-approve | ✅ Yes | ✅ Yes (implicit) |
| Git Integration | ✅ Yes | ❌ No |

## Files Modified

1. `/templates/dashboard.html` - Added app selector, updated JS
2. `/src/routes/api_routes.py` - Accept app context parameters
3. `/src/automorph_application.py` - Use app folder in prompt

## Documentation

- Main implementation: `VIRTUAL_ADVISOR_CHANGES.md`
- UI changes: `VIRTUAL_ADVISOR_UI_CHANGES.md`
- This document: Application selector specifics

## Next Steps

Possible enhancements:
- Show application status in selector (running/stopped)
- Filter applications by deployment status
- Add "All Applications" option for batch operations
- Remember last selected application
- Show deployment path in UI

## Rollback

If issues occur:
```bash
git checkout templates/dashboard.html
git checkout src/routes/api_routes.py
git checkout src/automorph_application.py
```
