---
name: pr-manager
description: Review, test, lint, and prepare smart merges for all open and
  closed PRs, verifying features and documenting technical debt.
---

# PR Manager

This skill manages outstanding PRs, ensuring code quality, feature completeness, and smart merging without losing context or code.

## Core Workflows

### 1. PR Review and Merge Preparation
- We have a large amount of outstanding and open PRs.
- Use agentic orchestration to complete implementation of these items to prevent context rot.
- Provide agents with instructions and plans as needed, then dispose of the agent and use a fresh one.
- **Before Implementation**: Research and plan/architect all features. Coordinate analysis of current research and docs within the repo. If new research is done, save it to the `docs` folder.
- **Review Each PR**: Check for comments, test/lint, and prepare for merge. Address and fix comments as needed. Update the PR once complete.
- **Merge Smartly**: Analyze as you go, test final before the final merge to main. Do not lose any coding we have; be as safe as possible.
- **Tracking**: Keep track of the session log and agents' work so we can track and monitor. Post a PR update for each so we can review.

### 2. Verification of Phase Features and Wiring
- Examine the feature requirements for each OPEN PR AND CLOSED PR.
- Verify the features were implemented or appear to be fully wired and flushed out.
- Prevent inline failures not explicitly exposed by the agents or models that would cause extensive re-writes.
- Produce a report of findings based on severity. Use multiple agents and orchestrate as needed to expedite.

### 3. Verification of Technical Deferment
- Do a sweep using multiple agents on all closed PRs AND open PRs for:
  - Technical deferment
  - Technical debt
  - Features that were not implemented
  - Any other issues noted in PR comments
- Ensure each PR is reviewed by Gemini if it hasn't been.
- Add these findings to the Architecture & Planning findings so we can remediate and tackle them all at once.
