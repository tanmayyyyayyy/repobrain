# Security

RepoBrain is a security tool, so its own attack surface is kept small. See "Security model" in the README.

Report vulnerabilities privately through GitHub Security Advisories on this repository. Please do not open public issues for security bugs.

Known limits (by design, not oversights): RepoBrain only guards changes that pass through it (CI, the local pre-commit hook, or the agent preflight API); it does not sandbox an agent that bypasses all three. The Optimizer executes the project's own tests (and, for pure-looking functions, generated inputs in a resource-limited subprocess) so run it on code you would run in CI anyway.
