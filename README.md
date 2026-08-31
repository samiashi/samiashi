## Selected work

### [chrono24-mcp](https://github.com/samiashi/chrono24-mcp)

An MCP server for researching watches on Chrono24 without leaving an AI client. It lets Claude, Codex, Cursor, Windsurf, and other MCP-compatible tools search the marketplace, compare listings, and retrieve detailed information about a watch—including its reference, movement, caliber, condition, box and papers, dealer, price, and photos.

Run it directly from npm without cloning the repository:

```bash
npx -y chrono24-mcp
```

**Built with:** TypeScript, Model Context Protocol, Playwright, persistent browser sessions, response caching, automated tests, and CI.

### [pytest-fahhh](https://github.com/samiashi/pytest-fahhh)

A deliberately tiny pytest plugin that plays the `fahhh` meme sound whenever a test fails. It installs from PyPI, works without changing the way you run pytest, supports macOS and common Linux audio players, and can be disabled per run or through project configuration.

```bash
pip install pytest-fahhh
pytest
```

**Built with:** Python, pytest's plugin system, cross-platform process handling, packaged audio assets, automated tests, and CI.

### [django-migration-checker](https://github.com/samiashi/django-migration-checker)

A lightweight guard against conflicting Django migration numbers. It recursively scans the apps in a Django project, finds duplicate migration prefixes created across parallel branches, and reports the exact files that would conflict before they are merged or deployed.

It can be run locally or added to a pull-request workflow as an early CI check:

```bash
python migration_checker.py
```

**Built with:** Python, Django project conventions, recursive filesystem inspection, readable terminal output, and GitHub Actions integration.
