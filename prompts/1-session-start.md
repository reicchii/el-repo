# Prompt 1: start a session on any lane

Paste into a new session in the repository root or in the lane's worktree. Fill in the lane.

Your lane is <Engine | ML | Web>.

1. Run `date -u` and state the time.
2. Read AGENTS.md. Then read docs/PROJECT-CONTEXT.md sections 1, 4 and 12, and the sections AGENTS.md section 3 lists for your lane. Do not skim.
3. Answer each in one or two sentences, with the section you found it in:
   a. What is the one required objective of the challenge?
   b. Why can two raw SPHEREx frames of the same position not be blinked against each other?
   c. Why does WISE 0855 need per-detector visit stacks?
   d. Where is WISE 0855 now relative to the challenge's coordinates, and how do we handle it?
   e. What are the three values of source status?
   f. What are the four origin labels on a reading?
   g. When does a prediction count as held?
   h. Which words are reserved, and when is each allowed?
   i. What does the site do when the API is off?
   j. Which licences are forbidden and which tools does that rule out?
   k. Why do we not show a full molecule composition, and what do we show?
   l. What is the main type model, and what makes its percentages honest?
   m. Which three type results are stored for every source, and what does the input ladder publish?
4. Run `bash scripts/bootstrap.sh` and `bash scripts/check-network.sh`. Report anything missing or not reached. Engine and ML need git, uv and Python 3.12. Web needs git, node and pnpm. Install what is missing with uv or pnpm.
5. List the open checks (docs/PROJECT-CONTEXT.md section 16 and section 9.12) that block your lane's first tasks. Do them. Record each answer in docs/decisions.md with the command or URL used.
6. Take the first unticked task in your lane in docs/PROJECT-CONTEXT.md section 12 that no open pull request has claimed, and work the plan in order.

For every task:
- State the task ID and its acceptance check before you start.
- Claim it first: open a draft pull request named "<ID> <what it does>" (CONTRIBUTING.md).
- Write the test first where a test is possible.
- Keep the change to that one task, in that pull request.
- Paste the acceptance check output in the pull request.
- Tick the box in docs/PROJECT-CONTEXT.md section 12 and add your line to docs/ai-log.md.
- Report in three lines: what changed, the check output, the next task ID. Then continue with the next task.

If a fact is marked [TO CHECK] or [check], or is missing from the docs, check it. If it cannot be checked, record it and take the next task. Never guess and never use made-up data. If a step needs a login or a token, add it to "Needs outside action" in docs/decisions.md and continue.
