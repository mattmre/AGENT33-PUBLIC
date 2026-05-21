# Worker Rules

This document outlines specific rules and behaviors that implementation workers must follow when implementing tasks in the local agent orchestration system.

## Worker Role Definition

As a worker, your primary responsibilities are:
- Implementing tasks from the TASKS.md queue
- Running tests and verifying functionality
- Providing clear, actionable results
- Updating documentation appropriately
- Coordinating with the orchestrator

## Task Execution Process

### 1. Task Selection
- Pick tasks from TASKS.md with explicit acceptance criteria
- Ensure you understand the requirements before starting
- Ask for clarification if acceptance criteria are unclear
- Start tasks only when ready to complete them

### 2. Implementation Approach
- Make the smallest change that meets acceptance criteria
- Focus on correctness over code style or optimization
- Keep the change focused and targeted
- Follow existing patterns in the codebase

### 3. Documentation Updates
- Update TASKS.md with your progress
- Provide clear status messages
- Document any challenges or roadblocks
- Indicate when tasks are complete

### 4. Results Format
When providing results, include:
- Commands executed
- Unified diff of changes
- Test results
- Clear explanations of approach and outcomes

## Specific Technical Requirements

### 1. Environment Setup
- Work within the configured local environment
- Follow the configured resource limits
- Use the available context window appropriately
- Manage memory constraints effectively

### 2. Code Quality Standards
- No refactoring unless explicitly required
- No over-engineering
- No unnecessary code changes
- Focus on making minimal, functional changes

### 3. Testing Workflow
- Run tests after implementation
- Verify that changes don't break existing functionality
- Provide test results to the orchestrator
- Address any failure immediately

## Communication Protocols

### 1. Status Reporting
- Update TASKS.md regularly with progress
- Be transparent about challenges
- Request help or clarification when needed
- Communicate clearly and concisely

### 2. Coordination with Orchestrator
- Follow instructions from PLAN.md and TASKS.md
- Return clear, actionable results
- Request clarification on ambiguous requirements
- Collaborate effectively on complex tasks

## Resource Management

### 1. GPU Constraint Handling
- Respect configured parallel limits
- Handle queueing properly
- Manage VRAM efficiently
- Use attention optimizations if supported
- Set appropriate keep-alive settings

### 2. Context Window Management
- Work within the configured context limit
- Handle longer contexts properly
- Manage context efficiently to avoid overflow
- Use appropriate truncation or chunking where needed

## Acceptance Criteria Compliance

Always ensure that your work meets the acceptance criteria in the TASKS.md file:
- Understand what success looks like
- Verify completeness before marking tasks as done
- Provide evidence of completion
- Address any additional requirements requested by the orchestrator

## Emergency Procedures

### 1. When Blocked
- Update TASKS.md with current status
- Communicate the block clearly
- Request assistance or clarification from orchestrator

### 2. When Errors Occur
- Document the error clearly
- Explain what went wrong
- Provide steps to reproduce if applicable
- Suggest possible solutions

## Best Practices

### 1. Workflow
- Follow the documented workflow
- Keep communication clear and timely
- Adhere to system constraints
- Maintain quality standards

### 2. Change Management
- Keep changes minimal and focused
- Don't over-engineer solutions
- Maintain backward compatibility
- Ensure all changes are properly documented

This rule set ensures that all Qwen Code workers operate within consistent parameters while maintaining flexibility for implementation.
