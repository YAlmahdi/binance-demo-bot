# Local migration verification — October 9, 2026

- Old location: C:\Users\yazan\OneDrive\Documents\New project\binance-demo-bot
- New location: C:\Users\yazan\Development\binance-demo-bot
- All 82 original files were copied, including hidden files, market data, tool dependencies and five custom skills.
- SHA-256 checksums matched for every original file before testing. Source checksums were rechecked before removing the old folder. Tests may regenerate Python bytecode caches; source and data files remained identical.
- 27 offline tests passed. The optional public-network smoke test was skipped. These tests use dummy credentials; no requests were made to order endpoints.
- All five SKILL.md files passed the official skill validator.
- A standalone local Git repository was initialized because the old project had no tracked files and previously inherited its parent's repository. No remote, commit or upload was created. `.env` and `data/` ignore rules were verified.
- After verification, the old OneDrive project folder was removed. The original parent repository and unrelated projects were not moved or changed. This does not remove any historical cloud backups managed by OneDrive.
- README and the Arabic setup guide now point to the local folder. Runtime source and test files were not changed.
- A blank .env was created from .env.example AFTER removal of the OneDrive copy. It contains no user credentials yet. The agent will not inspect its contents after configuration.
- Detailed original checksums are stored locally in data/migration-manifest.json (ignored by Git).
- Awaiting the user's confirmation that Demo HMAC credentials have been saved privately. Only read-only Demo connection and balance checks are authorized next. No orders and no Phase 2.

## Next step for the user

Open C:\Users\yazan\Development\binance-demo-bot\.env in your own local text editor. Fill BINANCE_DEMO_API_KEY and BINANCE_DEMO_API_SECRET with keys created inside Binance Demo. Leave BINANCE_ENV=demo. Save and close the file. Do not paste credentials into chat or shell commands. Reply only: Saved.

Open C:\Users\yazan\Development\binance-demo-bot as the project in Codex so future work and skill discovery use the new location.