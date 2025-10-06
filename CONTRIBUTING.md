# Contributing to Scanshelf

Thank you for your interest in contributing to Scanshelf! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/scanshelf`
3. Set up development environment:
   ```bash
   cd scanshelf
   uv venv
   source .venv/bin/activate
   uv pip install -e .
   ```

## Development Workflow

### Branching Strategy

- `main` - Production-ready code
- `feature/*` - New features
- `fix/*` - Bug fixes
- `docs/*` - Documentation updates
- `refactor/*` - Code improvements

### Making Changes

1. Create a feature branch from `main`:
   ```bash
   git checkout main
   git pull
   git checkout -b feature/your-feature-name
   ```

2. Make your changes following the code style guidelines

3. Test your changes:
   ```bash
   # Run tests
   pytest tests/

   # Test CLI commands
   uv run python ar.py --help
   ```

4. Commit with descriptive messages:
   ```bash
   git add <files>
   git commit -m "feat: add new feature"
   ```

   Use conventional commit prefixes:
   - `feat:` - New features
   - `fix:` - Bug fixes
   - `docs:` - Documentation changes
   - `refactor:` - Code refactoring
   - `test:` - Test additions/changes
   - `chore:` - Maintenance tasks

### Submitting Pull Requests

1. Push your branch to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

2. Create a Pull Request on GitHub with:
   - Clear title describing the change
   - Description of what changed and why
   - Link to related issues (if any)
   - Confirmation that tests pass

3. Wait for review and address any feedback

## Code Style

- Follow PEP 8 guidelines for Python code
- Use type hints where appropriate
- Keep functions focused and well-documented
- Add docstrings to public functions and classes

## Testing

- Add tests for new features
- Ensure existing tests pass
- Test with real PDFs when modifying pipeline stages

## Documentation

- Update README.md if adding new features
- Update relevant docs/ files for changes
- Keep examples current and working

## Questions?

Open an issue on GitHub or reach out to the maintainers.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
