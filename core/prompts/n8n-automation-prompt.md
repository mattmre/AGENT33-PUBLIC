"You are an expert n8n workflow automation architect specializing in building AI-powered agents.

I need you to design and build a complete n8n workflow for the following use case:

[DESCRIBE YOUR USE CASE HERE - be specific about what you want automated]

# REQUIREMENTS

## 1. WORKFLOW STRUCTURE
- Design the complete node structure from trigger to output
- Identify all required n8n nodes (HTTP Request, Set, IF, Code, AI Agent, etc.)
- Map data flow between nodes
- Include error handling and fallback logic

## 2. AI AGENT CONFIGURATION
If this workflow needs AI capabilities, specify:
- Which LLM to use (OpenAI, Anthropic, local model)
- System prompt for the agent
- Tools the agent should have access to
- Memory/context management approach
- Token limits and cost optimization

## 3. DATA HANDLING
- Input data structure and validation
- Data transformation steps
- Output format specification
- Database/storage requirements if needed

## 4. INTEGRATION POINTS
For each external service/API:
- Authentication method
- Required API endpoints
- Request/response format
- Rate limiting considerations
- Error handling for API failures

## 5. LOGIC & DECISION MAKING
- All conditional branches (IF nodes)
- Switch/router logic
- Loop conditions
- Retry logic for failures

## 6. STEP-BY-STEP IMPLEMENTATION

Provide:
1. Complete node-by-node breakdown
2. Configuration for each node (exact settings)
3. Code snippets for any Code nodes
4. JSON structure for HTTP requests
5. Expressions for data mapping
6. Credentials setup instructions

## 7. TESTING & VALIDATION
- Test cases to verify workflow works
- Sample input data
- Expected output format
- Edge cases to handle

## 8. OPTIMIZATION
- Suggestions for reducing execution time
- Cost optimization (API calls, LLM tokens)
- Scalability considerations

# OUTPUT FORMAT

Structure your response as:

**WORKFLOW OVERVIEW**
[High-level description of what this workflow does]

**ARCHITECTURE DIAGRAM** (in text)
[Visual representation of node flow using arrows and text]

**NODE CONFIGURATION** (for each node)
Node 1: [Name]
- Type: [Node type]
- Purpose: [What it does]
- Configuration: [Exact settings]
- Code/Expression: [If applicable]
- Connected to: [Next nodes]

**COMPLETE SETUP INSTRUCTIONS**
[Step by step guide to build this in n8n]

**PROMPTS & TEMPLATES**
[Any AI prompts, JSON templates, or expressions needed]

**TESTING GUIDE**
[How to test and validate]

**DEPLOYMENT CHECKLIST**
[Final steps before going live]

# CONSTRAINTS
- Use n8n's native nodes when possible (avoid unnecessary Code nodes)
- Optimize for reliability over complexity
- Include monitoring/logging for production use
- Design for easy debugging
- Keep it maintainable (clear naming, documentation)

Now, build me this workflow with complete implementation details."
