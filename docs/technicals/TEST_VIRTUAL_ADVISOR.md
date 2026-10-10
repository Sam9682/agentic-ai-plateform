# Virtual Advisor - Application Management Testing

## Overview
The Virtual Advisor now handles application management actions (STOP/START/RESTART/PS/LOGS) by detecting keywords and loading context from `./agentic-ai-plateform--skills/` folder.

## Supported Actions

### 1. START
**Keywords**: start, deploy, launch, run
**Context File**: `./agentic-ai-plateform--skills/START_context.md`
**Example Questions**:
- "Start the application"
- "Deploy my app"
- "Launch the service"

### 2. STOP
**Keywords**: stop, shutdown, halt, terminate
**Context File**: `./agentic-ai-plateform--skills/STOP_context.md`
**Example Questions**:
- "Stop the application"
- "Shutdown the service"
- "Halt the containers"

### 3. RESTART
**Keywords**: restart, reboot, reload
**Context File**: `./agentic-ai-plateform--skills/RESTART_context.md`
**Example Questions**:
- "Restart the application"
- "Reboot the service"
- "Reload the containers"

### 4. PS (Status)
**Keywords**: status, ps, check, running
**Context File**: `./agentic-ai-plateform--skills/PS_context.md`
**Example Questions**:
- "What's the status of my application?"
- "Check if the service is running"
- "Show me the ps output"

### 5. LOGS
**Keywords**: logs, log, output, console
**Context File**: `./agentic-ai-plateform--skills/LOGS_context.md`
**Example Questions**:
- "Show me the logs"
- "Display application output"
- "What's in the console?"

## How It Works

1. **User sends message** to Virtual Advisor via dashboard
2. **Keyword detection** identifies the action type
3. **Context loading** reads the appropriate `*_context.md` file from `./agentic-ai-plateform--skills/`
4. **Parameter substitution** replaces placeholders:
   - `{USER_ID}` - Current user's ID
   - `{USER_NAME}` - User's full name
   - `{USER_EMAIL}` - User's email
   - `{DESCRIPTION}` - Optional description
5. **AI Chat execution** with `--trust-all-tools` flag for command execution
6. **Response** returned to user with execution results

## Testing

### Test via Web UI
1. Open dashboard: https://localhost:5000
2. Click "Virtual Advisor" button
3. Type: "Check the status of my application"
4. Observe the response with deployment status

### Test via API
```bash
curl -X POST https://localhost:5000/api/qchat_devops \
  -H "Content-Type: application/json" \
  -H "Cookie: session=YOUR_SESSION_COOKIE" \
  -d '{"message":"Show me the application status"}'
```

### Expected Behavior
- Action keywords trigger context loading
- Commands execute with proper user context
- Results include deployment information
- Logs show detected action type

## Logs to Monitor
```bash
# Watch application logs
tail -f /var/log/<PLTF_FOLDER>.log

# Look for these patterns:
[VIRTUAL ADVISOR] Detected action: START, loading context from...
[VIRTUAL ADVISOR] Detected action: STOP, loading context from...
[VIRTUAL ADVISOR] Detected action: PS, loading context from...
```

## Troubleshooting

### Context file not found
- Verify files exist in `/home/ubuntu/<PLTF_FOLDER>/agentic-ai-plateform--skills/`
- Check file permissions: `chmod 644 ./agentic-ai-plateform--skills/*_context.md`

### Commands not executing
- Ensure `qchat` is installed: `which qchat`
- Check `--trust-all-tools` flag is added for actions
- Verify user has proper permissions

### No action detected
- Check keyword matching in `action_keywords` dict
- Add more keywords if needed
- Review user message format
