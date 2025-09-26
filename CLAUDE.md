# AI Assistant Workflow Guide

## First Things First

When starting any session:
1. Run `tree -L 2` to see current repo structure
2. Check `git status` for current state
3. Review open issues on GitHub
4. Check the project board for priorities

## Core Workflow Principles

### Git as Source of Truth
- **Current state**: Lives on main branch only
- **History**: Lives in git commits
- **Planning**: Lives in GitHub issues/projects
- **Never**: Keep old versions, drafts, or outdated docs

### Work Progression
```
Issue → Branch → Code → Test → Doc → Commit → PR → Merge
```

Every piece of work should:
1. Start with a GitHub issue
2. Happen on a feature branch
3. Include tests
4. Update relevant docs
5. Use atomic commits (logical chunks)
6. Go through PR review

## Git Operations

### Branching
```bash
# Always from main
git checkout main
git pull
git checkout -b <type>/<description>

# Types:
# - feature/ (new functionality)
# - fix/ (bug fixes)
# - docs/ (documentation only)
# - refactor/ (code improvements)
```

### Committing
```bash
# Atomic commits after logical sections
git add <files>
git commit -m "<type>: <present-tense-description>"

# Types: feat, fix, docs, refactor, test, chore
```

Examples:
- `feat: add quote extraction for biographies`
- `fix: handle empty source documents`
- `docs: update setup instructions`

### Pull Requests
When creating PRs:
1. Link to the issue: "Fixes #123"
2. Describe what changed and why
3. Confirm tests pass
4. Confirm docs updated

## GitHub Organization

### Issue Creation
Every issue should have:
- Clear title
- Labels (at minimum one of: `development`, `documentation`, `bug`, `enhancement`)
- For research items add: `person:<name>` or `topic:<topic>`
- Assignment to project board
- Milestone if applicable

### Issue Labels
Core labels:
- `development` - Code work
- `documentation` - Docs updates
- `bug` - Something broken
- `enhancement` - Improvements
- `research` - Research tasks

Entity labels:
- `person:<lastname>` - For biographical work
- `topic:<keyword>` - For thematic research

## Testing Discipline

Before any commit:
```bash
# Run tests if they exist
pytest tests/  # or appropriate test command

# Check for syntax errors
python -m py_compile src/**/*.py

# Verify documentation is current
# (Manually check if automated check doesn't exist)
```

## Documentation Updates

When code changes:
1. Update relevant docs immediately
2. Never create "v2" docs - update in place
3. Remove outdated sections
4. Keep examples current

## Working with Existing Files

Before modifying:
1. Understand current patterns
2. Follow existing conventions
3. Don't introduce new patterns without discussion
4. Check git history if unclear: `git log -p <file>`

## Environment Setup

Never commit secrets:
```bash
# Check .env.example for required variables
cp .env.example .env
# Edit .env with actual values
# Ensure .env is in .gitignore
```

## Automation Triggers

GitHub Actions will run on:
- Push to any branch (tests)
- PR creation/update (full checks)
- Merge to main (deployment/updates)

## Quick Decision Guide

**Starting work?**
- Check issues first
- Create branch from main
- Run tree to see structure

**Making changes?**
- Test locally first
- Commit logical chunks
- Update docs immediately

**Stuck or unsure?**
- Check existing patterns
- Look at git history
- Review similar PRs

**Ready to merge?**
- Tests passing
- Docs updated
- PR approved
- Linked issue closed

## Remember

1. **One source of truth** - Main branch is reality
2. **Issues before code** - Plan in GitHub
3. **Test everything** - No untested code
4. **Commit often** - Logical, atomic chunks
5. **Docs stay current** - Update or delete

---

*This workflow ensures consistent, trackable progress. All work flows through GitHub issues and PRs, creating a complete audit trail.*