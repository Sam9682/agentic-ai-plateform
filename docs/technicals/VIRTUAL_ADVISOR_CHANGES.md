# Virtual Advisor - Application Management Integration

## Summary of Changes

The Virtual Advisor has been enhanced to handle application management actions (STOP/START/RESTART/PS/LOGS) by integrating with AI Chat and using context prompts from the `./shared/` folder.

## Modified Files

### 1. `/src/automorph_application.py`

**Function**: `process_qchat_devops()`

**Changes**:
- Added parameters: `user_id`, `user_name`, `user_email`, `description`
- Implemented action keyword detection for: START, STOP, RESTART, PS, LOGS
- Loads context from `./shared/{ACTION}_context.md` files
- Replaces placeholders: `{USER_ID}`, `{USER_NAME}`, `{USER_EMAIL}`, `{DESCRIPTION}`, `{TAIL_LINES}`
- Uses `--trust-all-tools` flag when action detected (enables command execution)
- Falls back to simple Q&A mode if no action detected

**Action Detection Keywords**:
```python
action_keywords = {
    'start': ['start', 'deploy', 'launch', 'run'],
    'stop': ['stop', 'shutdown', 'halt', 'terminate'],
    'restart': ['restart', 'reboot', 'reload'],
    'ps': ['status', 'ps', 'check', 'running'],
    'logs': ['logs', 'log', 'output', 'console']
}
```

### 2. `/src/routes/api_routes.py`

**Endpoint**: `/api/qchat_devops`

**Changes**:
- Retrieves user details from database (username, email, full name)
- Passes user context to `process_qchat_devops()` function
- Enables proper parameter substitution in context templates

## Context Files Used

Located in `./shared/` folder:
- `START_context.md` - Application deployment and startup
- `STOP_context.md` - Stop running containers
- `RESTART_context.md` - Restart services without rebuild
- `PS_context.md` - Check deployment status (JSON output)
- `LOGS_context.md` - Display container logs

## How It Works

```
User Message → Keyword Detection → Load Context → Replace Params → AI Chat Execution → Response
```

### Example Flow:

1. **User asks**: "What's the status of my application?"
2. **Detection**: Keyword "status" matches PS action
3. **Load**: Reads `./shared/PS_context.md`
4. **Replace**: 
   - `{USER_ID}` → "5"
   - `{USER_NAME}` → "John Doe"
   - `{USER_EMAIL}` → "john@example.com"
5. **Execute**: AI Chat runs with `--trust-all-tools` flag
6. **Response**: Returns JSON with deployment status

## Benefits

✅ **Unified Interface**: Single Virtual Advisor handles both Q&A and app management
✅ **Context-Aware**: Uses detailed prompts from shared folder
✅ **User-Specific**: Automatically injects user information
✅ **Extensible**: Easy to add new actions by creating new context files
✅ **Safe Execution**: Only enables command execution for detected actions

## Usage Examples

### Via Dashboard
1. Click "Virtual Advisor" button
2. Type natural language commands:
   - "Start my application"
   - "Show me the logs"
   - "What's the status?"
   - "Restart the service"

### Via API
```bash
curl -X POST https://localhost:5000/api/qchat_devops \
  -H "Content-Type: application/json" \
  -H "Cookie: session=YOUR_SESSION" \
  -d '{"message":"Check application status"}'
```

## Testing

Run the application and test:
```bash
cd /home/ubuntu/<PLTF_FOLDER>
python3 ControlPlanFlaskApp_postgres.py
```

Monitor logs:
```bash
tail -f /var/log/<PLTF_FOLDER>.log | grep "VIRTUAL ADVISOR"
```

## Next Steps

To add new actions:
1. Create `./shared/NEWACTION_context.md` with instructions
2. Add keywords to `action_keywords` dict in `automorph_application.py`
3. Test with Virtual Advisor interface

## Rollback

If issues occur, revert changes:
```bash
git checkout src/automorph_application.py
git checkout src/routes/api_routes.py
```
