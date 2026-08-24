# Publishing VoiceTalk to PyPI

This guide explains how to publish VoiceTalk to the Python Package Index (PyPI).

## Prerequisites

1. **PyPI Account** — Create one at https://pypi.org/account/register/
2. **GitHub Actions** — Set up trusted publishing (no API tokens needed)

## Setup (One-time)

### 1. Create PyPI API Token

1. Go to https://pypi.org/account/
2. Click "Account settings" → "API tokens"
3. Click "Add API token"
4. Name it `github-voicetalk`
5. Set scope to "Entire account"
6. Copy the token

### 2. Configure GitHub Trusted Publishing (Recommended)

This is more secure than API tokens and requires no secrets:

1. Go to https://pypi.org/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name**: `voicetalk`
   - **GitHub Repository Owner**: `Vaithorat`
   - **GitHub Repository Name**: `voicetalk`
   - **GitHub Workflow Name**: `publish.yml`
   - **GitHub Environment Name**: `pypi`
4. Click "Add"
5. Go to your GitHub repo → Settings → Environments → Create environment `pypi`
6. No secrets needed!

Alternatively, if you prefer API tokens:

1. Go to your GitHub repo → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `PYPI_API_TOKEN`
4. Value: Paste the token from PyPI
5. Click "Add secret"

## Publishing a Release

### Automated (Recommended)

1. **Update version** in `pyproject.toml`
   ```toml
   [project]
   version = "3.1.0"
   ```

2. **Create a git tag**
   ```bash
   git tag v3.1.0
   git push origin v3.1.0
   ```

3. **Create a GitHub release**
   - Go to https://github.com/Vaithorat/voicetalk/releases
   - Click "Draft a new release"
   - Tag: select the tag you just created (e.g., `v3.1.0`)
   - Title: `VoiceTalk v3.1.0`
   - Description: Write release notes
   - Click "Publish release"

The GitHub Actions workflow (`.github/workflows/publish.yml`) will automatically:
- Build the distribution
- Publish to PyPI
- No manual steps needed after this point

**Status**: Check the Actions tab for build progress.

### Manual Publishing (if needed)

1. **Build locally**
   ```bash
   python -m pip install --upgrade build
   python -m build
   ```

2. **Upload**
   ```bash
   python -m pip install --upgrade twine
   twine upload dist/*
   ```

## Verification

After publishing, verify the package is live:

```bash
pip install --upgrade voicetalk
```

Check PyPI: https://pypi.org/project/voicetalk/

## Versioning

Follow [Semantic Versioning](https://semver.org/):

- **MAJOR.MINOR.PATCH** (e.g., `3.1.0`)
- Increment MAJOR for breaking changes
- Increment MINOR for new features
- Increment PATCH for bug fixes

Git tags should match the version: `v3.1.0` (with leading `v`).

## Troubleshooting

**"Project already registered"** — The project name is taken on TestPyPI. Use a different test name or go straight to PyPI.

**"Failed to authenticate"** — Check that:
- API token is correctly set in GitHub secrets (if using tokens)
- Trusted publisher is configured (if using trusted publishing)
- The token hasn't expired

**Build fails in Actions** — Check the Actions log for details. Common issues:
- Missing `build` module: install it
- `pyproject.toml` syntax error: validate it locally

## Testing (Optional)

Before publishing to PyPI, test on TestPyPI:

1. Create a TestPyPI account: https://test.pypi.org/account/register/
2. Add to `pyproject.toml`:
   ```toml
   [project]
   version = "3.1.0rc1"  # Pre-release version
   ```
3. Create a release on GitHub
4. After it's published to TestPyPI (not PyPI), test:
   ```bash
   pip install -i https://test.pypi.org/simple/ voicetalk==3.1.0rc1
   ```
