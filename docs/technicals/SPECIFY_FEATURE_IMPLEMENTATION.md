# SPECIFY an AI Context Feature - Implementation Summary

## Overview
Successfully implemented a new "SPECIFY an AI context" option in the Virtual Agents panel that helps users transform brief descriptions into detailed, actionable specifications for application modifications.

## Files Created

### 1. shared/SPECIFY_context.md
- AI prompt template for generating detailed specifications
- Transforms 1-2 sentence user requests into comprehensive technical specs
- Includes sections for: Objective, Scope, Technical Requirements, Implementation Details, Acceptance Criteria, and Constraints
- Uses template variables: {{MESSAGE}}, {{APPLICATION_NAME}}, {{APPLICATION_FOLDER}}, {{REPO_GITHUB_URL}}

### 2. shared/README_SPECIFY.md
- User documentation for the SPECIFY feature
- Step-by-step usage guide
- Benefits and use cases
- Integration with MODIFY action

## Files Modified

### 1. templates/dashboard.html
**Changes:**
- Added new option in Virtual Agents dropdown: `<option value="SPECIFY">{{ get_text('specify_context_option') }}</option>`
- Added JavaScript handler for SPECIFY action in `sendUnifiedMessageWithText()` function
- Added placeholder text logic in `updateUnifiedInputText()` function
- Streams response from `/api/request_dev_ai_for_app` endpoint with action_operation='SPECIFY'

**Location:** Lines 627, 2050-2135, 2436-2438

### 2. src/config_postgres.py
**Changes:**
- Added English translations:
  - `'specify_context_option': '📝 SPECIFY an AI context'`
  - `'specify_context_request1': 'I need help to write a detailed specification for modifying the application'`
  - `'specify_context_request2': 'Please, hereafter is my brief description of what needs to be changed:'`

- Added French translations:
  - `'specify_context_option': '📝 SPÉCIFIER un contexte IA'`
  - `'specify_context_request1': "J'ai besoin d'aide pour écrire une spécification détaillée pour modifier l'application"`
  - `'specify_context_request2': 'Veuillez trouver ci-dessous ma brève description de ce qui doit être modifié :'`

**Location:** Lines 360-362 (English), 586-588 (French)

## Backend Integration

### Existing Code Support
The backend already supports the SPECIFY action through:
- `src/routes/genai_routes.py` - `return_prompt_for_developer()` function
- Automatically loads context file: `/home/ubuntu/<PLTF_FOLDER>/shared/SPECIFY_context.md`
- Replaces template variables with actual values
- Streams response back to frontend

**No backend changes required** - the existing infrastructure handles any new action automatically by looking for the corresponding `{ACTION}_context.md` file.

## User Workflow

1. **Select Application**: User selects an application from the dropdown
2. **Choose SPECIFY**: User selects "📝 SPECIFY an AI context" from actions
3. **Enter Brief Description**: User types 1-2 sentences describing what they want
4. **Get Specification**: AI generates comprehensive specification with:
   - Clear objectives
   - Technical requirements
   - Implementation steps
   - Acceptance criteria
   - Risk assessment
5. **Copy & Use**: User copies the specification and uses it with "MODIFY the App" option

## Technical Details

### Frontend Flow
```
User Input → JavaScript Handler → POST /api/request_dev_ai_for_app
→ Backend loads SPECIFY_context.md → AI generates spec → Stream to frontend
```

### Context File Processing
```python
context_file = f"/home/ubuntu/<PLTF_FOLDER>/shared/{safe_action}_context.md"
# For SPECIFY action: /home/ubuntu/<PLTF_FOLDER>/shared/SPECIFY_context.md
```

### Template Variables Replaced
- `{{USER_ID}}` - Current user ID
- `{{USER_NAME}}` - User's full name
- `{{USER_EMAIL}}` - User's email
- `{{APPLICATION_FOLDER}}` - Application deployment path
- `{{APPLICATION_NAME}}` - Application name
- `{{REPO_GITHUB_URL}}` - GitHub repository URL
- `{{MESSAGE}}` - User's brief description

## Benefits

1. **Improved Specification Quality**: AI ensures comprehensive specs with all necessary details
2. **Time Savings**: Users don't need to write detailed technical specs manually
3. **Reduced Errors**: Structured approach reduces missing requirements
4. **Learning Tool**: Users can learn how to write better specs by example
5. **Seamless Integration**: Works with existing MODIFY action workflow

## Testing Recommendations

1. Test with various brief descriptions (features, bug fixes, enhancements)
2. Verify specification output is comprehensive and actionable
3. Test copy-paste workflow from SPECIFY to MODIFY
4. Verify both English and French translations work correctly
5. Test with different applications and user roles

## Future Enhancements

1. Add specification templates for common scenarios
2. Include code examples in generated specs
3. Add validation of generated specifications
4. Support for multi-step specifications
5. Integration with project management tools
