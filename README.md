@'
# AgentWasp AI

A GitHub App that gives pull requests long-term memory. It ingests PR diffs, commits and review discussion into a Cognee knowledge graph and answers questions about them from PR comments.

## Commands
- `@agentwaspai /review` stores the PR (files, commits, diff, comments, reviews) in memory
- `@agentwaspai /ask <question>` recalls relevant context from stored PRs

## Architecture
Node.js (Probot) bot receives GitHub webhooks and calls a FastAPI service in `/memory`, backed by Cognee Cloud.

## Run locally
```bash
npm install && npm start                      # bot (copy .env.example to .env)
cd memory && pip install -r requirements.txt  # memory service (copy memory/.env.example to memory/.env)
uvicorn api.main:app --port 8001
```
