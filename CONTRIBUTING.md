# Contributing to Rehau Nea Smart Home Assistant Integration

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## Code of Conduct

Be respectful, inclusive, and considerate of others. We aim to maintain a welcoming community.

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check if the issue already exists.

**When creating a bug report, include:**

- Home Assistant version
- Integration version
- Detailed description of the issue
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output (with sensitive data removed)

### Suggesting Enhancements

Enhancement suggestions are welcome! Please provide:

- Clear description of the enhancement
- Use case / motivation
- Examples of how it would work
- Any potential drawbacks

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Make your changes** following the coding standards below
3. **Test your changes** thoroughly
4. **Update documentation** if needed
5. **Submit a pull request** with a clear description

## Development Setup

### Prerequisites

- Python 3.11+
- Home Assistant development environment (optional but recommended)
- Rehau Nea Smart account for testing

### Local Development

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/rehau-neasmart-ha.git
cd rehau-neasmart-ha

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt

# Run testing scripts
cd testing
python auth_client.py
python mqtt_client.py
```

### Testing with Home Assistant

1. Copy `custom_components/rehau_neasmart` to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via UI
4. Test all functionality

## Coding Standards

### Python Style

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- Use type hints where appropriate
- Maximum line length: 120 characters
- Use descriptive variable names

### Code Organization

```python
# Imports order:
# 1. Standard library
# 2. Third-party libraries
# 3. Home Assistant core
# 4. Integration modules

import asyncio
import logging

import aiohttp

from homeassistant.core import HomeAssistant

from .auth import RehauAuthClient
```

### Documentation

- Add docstrings to all classes and functions
- Use clear, descriptive comments for complex logic
- Update README.md for user-facing changes
- Update PROJECT_SUMMARY.md for technical changes

### Example Docstring

```python
async def set_temperature(self, zone_number: int, temperature: float) -> None:
    """Set the target temperature for a zone.

    Args:
        zone_number: The zone identifier (0-based)
        temperature: Target temperature in Celsius

    Raises:
        ValueError: If temperature is outside valid range
        ConnectionError: If MQTT connection is not established
    """
```

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>: <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**

```
feat: add support for cooling mode

Implement cooling mode for zones that support it.
Adds new HVAC mode and temperature control logic.

Closes #123
```

```
fix: handle token refresh errors gracefully

Previously, token refresh failures would crash the integration.
Now it logs the error and attempts re-authentication.
```

## Testing Guidelines

### Manual Testing Checklist

Before submitting a PR, verify:

- [ ] Integration loads without errors
- [ ] Config flow works correctly
- [ ] MFA authentication succeeds
- [ ] Climate entities are created
- [ ] Temperature readings update
- [ ] Temperature setting works
- [ ] Entity attributes are correct
- [ ] MQTT connection is stable
- [ ] Token refresh works
- [ ] Integration can be reloaded
- [ ] Integration can be removed

### Automated Tests (Future)

We plan to add automated tests. When available:

```bash
pytest tests/
```

## Security

### Reporting Security Issues

**Do not** open public issues for security vulnerabilities.

Instead, email: cedric.kring@gmail.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Handling Sensitive Data

- Never commit tokens, passwords, or API keys
- Use `.env.example` for configuration examples
- Sanitize logs in bug reports
- Use environment variables for testing

## Documentation

### User Documentation

Update `README.md` for:
- New features visible to users
- Configuration changes
- New requirements
- Breaking changes

### Developer Documentation

Update `PROJECT_SUMMARY.md` for:
- Technical architecture changes
- New API discoveries
- Protocol changes
- Development process notes

## Release Process

Maintainers will:

1. Update version in `manifest.json`
2. Update CHANGELOG in `README.md`
3. Create a git tag (`v0.x.x`)
4. Create a GitHub release
5. (Future) Publish to HACS

## Questions?

Feel free to:
- Open a [GitHub Discussion](https://github.com/cedrickring/rehau-neasmart-ha/discussions)
- Ask in the [Home Assistant Community](https://community.home-assistant.io/)
- Open an issue for clarification

## Recognition

Contributors will be recognized in:
- GitHub contributors page
- Release notes
- README acknowledgments

Thank you for contributing! 🎉
