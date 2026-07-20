# https://just.systems

set dotenv-load
set lazy
set script-interpreter := ['pwsh', '-ExecutionPolicy', 'ByPass', '-File']
set shell := ['pwsh', '-ExecutionPolicy', 'ByPass', '-Command']

project_folder := "stratified_packager"
qgis_python := `if (Test-Path .venv/pyvenv.cfg) { uv run python -c "import sys; print(sys._base_executable)" }`
error := "Write-Host -ForegroundColor Red"
title := "Write-Host -ForegroundColor Cyan"

# Running just without specifying a recipe lists all available recipes
_default:
    @just --list --unsorted

[confirm('This will remove the virtual environment and other files ignored by git. Do you want to continue? [y/N])')]
[doc('Clean environment artifacts (removes everything in .gitignore, including .venv)')]
clean-all:
    @{{ title }} "Removing all files and folders ignored by git..."
    "n" | git clean -fdX

[doc('Remove build, test and cache artifacts (keeps the virtual environment)')]
[script]
clean:
    $ErrorActionPreference = 'Stop'
    {{ title }} "Removing build, test and cache artifacts..."
    $targets = @(
        'build', 'dist', 'htmlcov', 'docs/_build', 'docs/api/generated', '.coverage',
        '.hypothesis', '.pytest_cache', '.mypy_cache', '.ruff_cache',
        '{{ project_folder }}.*.zip', '{{ project_folder }}/resources/i18n/*.qm'
    )
    foreach ($t in $targets) {
        if (Test-Path $t) { Remove-Item -Recurse -Force $t }
    }
    Get-ChildItem -Path . -Recurse -Force -Directory -Filter '__pycache__' `
        | Where-Object { $_.FullName -notmatch '\.venv' } `
        | Remove-Item -Recurse -Force
    Get-ChildItem -Path . -Recurse -Force -Directory -Filter '*.egg-info' `
        | Where-Object { $_.FullName -notmatch '\.venv' } `
        | Remove-Item -Recurse -Force

[doc('Create the virtual environment and perform all setup needed from a freshly cloned repository')]
[group('Environment setup')]
@bootstrap qgis_prefix_path="" profile_path="": install-uv && customize-pth install-hooks
    just create-venv "{{ qgis_prefix_path }}"
    just setup-env-vars{{ if profile_path != "" { " --qgis-settings-dir " + profile_path } else { "" } }}
    just install-debugpy

[doc('Install or update uv')]
[group('Environment setup')]
install-uv:
    @{{ title }} "Updating uv to the latest version..."
    if ($IsWindows) { irm https://astral.sh/uv/install.ps1 | iex } else { curl -LsSf https://astral.sh/uv/install.sh | sh }

[doc('Create the virtual environment using qgis-venv-creator')]
[group('Environment setup')]
[script]
create-venv qgis_prefix_path="":
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $true
    {{ title }} "Creating virtual environment using qgis-venv-creator..."
    if (Test-Path .venv) {
        {{ error }} "[ERROR] The virtual environment folder '.venv' already exists."
        {{ error }} "        Remove it first and run this script again."
        exit 1
    }
    if ("{{ qgis_prefix_path }}" -eq "") {
        # No installation given: qgis-venv-creator uses the current interpreter or
        # prompts for one (how the QGIS Docker images and system installs are used).
        uvx --from git+https://github.com/nicogodet/qgis-venv-creator@qt6 create-qgis-venv
    } elseif ($IsWindows) {
        # OSGeo4W/standalone layout: the bundled Python lives in an 'apps/Python*'
        # folder beside the 'apps/qgis(-ltr)' installation. Run the creator under that
        # interpreter so the venv matches the QGIS Python version exactly.
        $qgisPython = Get-ChildItem -Path "$(Split-Path -Path `"{{ qgis_prefix_path }}`" -Parent)" -Directory -Filter "Python*" `
            | Select-Object -First 1 -ExpandProperty FullName
        if (-not $qgisPython) {
            {{ error }} "No Python* folder was found next to {{ qgis_prefix_path }}"
            {{ error }} "Expected a folder such as Python39 or Python312 next to the qgis(-ltr) folder under apps."
            exit 1
        }
        uvx --python "$qgisPython" --from git+https://github.com/nicogodet/qgis-venv-creator@qt6 create-qgis-venv --qgis-installation "{{ qgis_prefix_path }}"
    } else {
        # Non-Windows: qgis-venv-creator accepts a QGIS installation path only on
        # Windows. Its Linux backend builds the venv from `python3` (with
        # --system-site-packages) and ignores any path; macOS is unsupported upstream.
        Write-Host -ForegroundColor Yellow "Ignoring QGIS path '{{ qgis_prefix_path }}': qgis-venv-creator builds the venv from python3 on this platform."
        uvx --from git+https://github.com/nicogodet/qgis-venv-creator@qt6 create-qgis-venv
    }

[doc('Configure .env with git-ignored environment variables (`just setup-env-vars --help` for details)')]
[group('Environment setup')]
setup-env-vars *args:
    @{{ title }} "Configuring development environment variables..."
    uv run ./scripts/setup_env_vars.py {{ args }}

[doc('Append to qgis.pth the paths the venv needs to find the processing and GRASS modules')]
[group('Environment setup')]
customize-pth:
    @{{ title }} "Adding paths to qgis.pth..."
    uv run ./scripts/customize_qgis_pth.py

[doc('Update uv.lock to reflect the latest compatible versions of dependencies listed in pyproject.toml')]
[group('Dependencies')]
lock:
    @{{ title }} "Updating uv.lock to the latest compatible versions of dependencies..."
    uv lock --upgrade

[doc('Install project dependencies, ensuring that installed versions are compatible with uv.lock')]
[group('Dependencies')]
[script]
sync:
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $true
    {{ title }} "Synchronizing development dependencies..."
    if (Test-Path .venv) {
        uv sync --frozen
    } else {
        {{ error }} "Directory .venv not found."
        {{ error }} "Run 'just create-venv \"\<qgis_prefix_path\>\"' first to create the workspace virtual environment using the QGIS Python."
        exit 1
    }

# --break-system-packages: on Linux the QGIS Python is the OS-managed system Python
# (PEP 668 "externally managed"), which blocks pip even with --user. Paired with --user
# the install still targets ~/.local only, touching nothing system-wide; the flag is a
# harmless no-op on the self-contained Windows QGIS Python.
[doc('Install or update debugpy in the user site-packages used by the QGIS Python')]
[group('Dependencies')]
install-debugpy:
    @{{ title }} "Installing/updating debugpy visible to the QGIS Python ({{ qgis_python }})..."
    & "{{ qgis_python }}" -m pip install --upgrade --user --break-system-packages debugpy

[arg('builder', pattern='html|latexpdf')]
[doc('Build documentation')]
[group('Documentation')]
build-docs builder="html":
    @{{ title }} "Building Sphinx documentation..."
    uv run --group doc --exact sphinx-build -M {{ builder }} docs docs/_build -j auto -W --keep-going $env:SPHINXOPTS $env:O

[arg('port', pattern='102[4-9]|10[3-9]\d|1[1-9]\d{2}|[2-9]\d{3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5]', help='From 1024 to 65535')]
[doc('Serve documentation locally for development (available at http://localhost:PORT)')]
[group('Documentation')]
serve-docs port="8000":
    @{{ title }} "Starting documentation development server..."
    uv run -m http.server --directory docs/_build/html {{ port }}

[arg('port', pattern='102[4-9]|10[3-9]\d|1[1-9]\d{2}|[2-9]\d{3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5]', help='From 1024 to 65535')]
[doc('Open documentation in the browser (development server must be running)')]
[group('Documentation')]
browse-docs port="8000":
    @{{ title }} "Opening documentation in the default browser..."
    uv run -m webbrowser -t http://localhost:{{ port }}

[arg('port', pattern='102[4-9]|10[3-9]\d|1[1-9]\d{2}|[2-9]\d{3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5]', help='From 1024 to 65535')]
[doc('Build and serve documentation with live reload (available at http://localhost:PORT)')]
[group('Documentation')]
autobuild-docs port="8000":
    @{{ title }} "Starting Sphinx live-reload server..."
    uv run --group doc --exact sphinx-autobuild docs docs/_build/html --watch {{ project_folder }} --port {{ port }} --open-browser -j auto

[doc('Update translations')]
[group('i18n')]
lupdate:
    @{{ title }} "Updating translation files..."
    just prek pylupdate

[doc('Compile translation .ts files into .qm')]
[group('i18n')]
lrelease:
    @{{ title }} "Compiling translation files..."
    uv run --with pyside6-essentials pyside6-lrelease @(Get-ChildItem stratified_packager/resources/i18n/*.ts).FullName

[doc('Install the prek-managed pre-commit hooks into the local git repository')]
[group('Pre-commit hooks')]
install-hooks:
    @{{ title }} "Installing pre-commit hooks..."
    uv run prek -C '{{ justfile_directory() }}' install --overwrite

[doc('Run pre-commit hooks (examples: `just prek` or `just prek sync-with-uv`)')]
[group('Pre-commit hooks')]
[script]
prek hook="":
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $true
    if ("{{ hook }}" -eq "") {
        {{ title }} "Running pre-commit hooks..."
        uv run prek run --all-files --verbose
    } else {
        {{ title }} "Running pre-commit hook {{ hook }}..."
        uv run prek run --all-files --verbose --hook-stage manual {{ hook }}
    }

[doc('Run only the pre-commit hooks from the `qgis-venv` group')]
[group('Pre-commit hooks')]
prek-qgis:
    {{ title }} "Running pre-commit hooks that require a QGIS-enabled venv..."
    uv run prek run --group qgis-venv --verbose

[doc('Run the Bandit security scan that plugins.qgis.org applies to submitted plugins')]
[group('Publishing')]
bandit:
    @{{ title }} "Running Bandit security scan (mirrors plugins.qgis.org moderation)..."
    uvx bandit -r {{ project_folder }} -q

[doc('Generate plugins.xml from metadata.txt and command-line options (`just build-xml --help` for details)')]
[group('Publishing')]
build-xml *args:
    @{{ title }} "Generating plugins.xml..."
    uv run --group pack ./scripts/build_qgis_repo_xml.py --timezone America/Sao_Paulo {{ args }}

[doc('Package plugin for distribution (`just package --help` for usage details)')]
[group('Publishing')]
package *qgis-plugin-ci_args:
    @{{ title }} "Generating plugin package..."
    uv run --group pack --exact qgis-plugin-ci package {{ qgis-plugin-ci_args }}

[doc('Print current plugin basic info (parsed from metadata.txt)')]
[group('Publishing')]
@info:
    uv run -m stratified_packager.__about__

[doc('Print the current plugin version (from metadata.txt)')]
[group('Publishing')]
@version:
    uv run python -c "from stratified_packager.__about__ import __version__; print(__version__)"

[confirm('This will tag the current commit and push main + tag to origin, triggering the release workflow (GitHub release + OSGeo deploy). Continue? [y/N]')]
[doc('Verify branch/tree/version/Bandit, then tag the release and push it')]
[group('Publishing')]
[script]
release version:
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $true
    if ((git branch --show-current) -ne 'main') {
        {{ error }} "Releases are tagged on main; current branch is '$(git branch --show-current)'."
        exit 1
    }
    if (git status --porcelain) {
        {{ error }} "Working tree is not clean. Commit or stash changes first."
        exit 1
    }
    $metadataVersion = uv run python -c "from stratified_packager.__about__ import __version__; print(__version__)"
    if ($metadataVersion -ne '{{ version }}') {
        {{ error }} "metadata.txt version ($metadataVersion) does not match tag '{{ version }}'."
        {{ error }} "Add the version to CHANGELOG.md and commit (the update-metadata hook syncs metadata.txt)."
        {{ error }} "Note: a version rejected by plugins.qgis.org gets a SemVer bump, never a re-tag."
        exit 1
    }
    just bandit
    {{ title }} "Tagging and pushing {{ version }}..."
    git tag '{{ version }}'
    git push origin main '{{ version }}'

[doc('Format code automatically')]
[group('QA')]
format:
    @{{ title }} "Running automatic formatting/cleanup..."
    -uv run ty check --fix
    -uv run ruff check --fix
    uv run ruff format

[doc('Static code analysis (runs every linter; exits non-zero if any of them fails)')]
[group('QA')]
[script]
lint:
    $ErrorActionPreference = 'Continue'
    {{ title }} "Running linting tools..."
    $failed = $false
    uv run ruff check; if ($LASTEXITCODE -ne 0) { $failed = $true }
    uv run flake8; if ($LASTEXITCODE -ne 0) { $failed = $true }
    uv run pylint .; if ($LASTEXITCODE -ne 0) { $failed = $true }
    if ($failed) { exit 1 }

[doc('Static type checking (runs every type checker; exits non-zero if any of them fails)')]
[group('QA')]
[script]
type-check:
    $ErrorActionPreference = 'Continue'
    {{ title }} "Running static type checking..."
    $failed = $false
    uv run ty check; if ($LASTEXITCODE -ne 0) { $failed = $true }
    uv run mypy .; if ($LASTEXITCODE -ne 0) { $failed = $true }
    if ($failed) { exit 1 }

[doc('Run all QA checks')]
[group('QA')]
qa: format lint type-check

alias ci := check

[doc('Run the full local gate: all QA checks followed by the test suite')]
[group('QA')]
check: qa test

# Depends on lrelease: .qm files are git-ignored and removed by `just clean`, so a deploy
# without them mirrors a plugin whose translator never installs (main.py skips a missing .qm).
[doc('Deploy the local code into the QGIS plugins directory (compiles translations first)')]
[group('QGIS')]
[script]
deploy profile='': lrelease
    $ErrorActionPreference = 'Stop'
    if (-not $env:QGIS_PROFILES_DIR) {
        {{ error }} "Error: environment variable QGIS_PROFILES_DIR is not set."
        exit 1
    }
    $p = if ('{{ profile }}') { '{{ profile }}' } else { "$env:DEVELOPMENT_PROFILE_NAME" ?? 'default' }
    $dest = Join-Path $env:QGIS_PROFILES_DIR $p | Join-Path -ChildPath "python/plugins/{{ project_folder }}"
    {{ title }} "Mirroring into $dest..."
    if ($IsWindows) {
        # robocopy mirrors incrementally; exit codes 0-7 are success, 8+ are failures.
        robocopy ./{{ project_folder }} "$dest" /MIR
        if ($LASTEXITCODE -gt 7) { exit $LASTEXITCODE } else { exit 0 }
    } else {
        # No robocopy on Unix: recreate the destination so files removed from the
        # source don't linger, then copy the source contents into it.
        if (Test-Path "$dest") { Remove-Item -Recurse -Force "$dest" }
        New-Item -ItemType Directory -Force -Path "$dest" | Out-Null
        Copy-Item -Path "./{{ project_folder }}/*" -Destination "$dest" -Recurse -Force
    }

[doc('Open QGIS using the development profile configured for this project')]
[group('QGIS')]
[script]
qgis profile='':
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $true
    $p = if ('{{ profile }}') { '{{ profile }}' } else { "$env:DEVELOPMENT_PROFILE_NAME" ?? $null }
    {{ title }} "Opening QGIS$(if ($p) { `" (Profile: $p)`" })..."
    $params = @()
    if ($env:QGIS_PROFILES_DIR) { $params += "--profiles-path", "$(Split-Path `"$env:QGIS_PROFILES_DIR`" -Parent)" }
    if ($p) { $params += "--profile", "$p" }
    & "$env:QGIS_EXECUTABLE_PATH" $params

[doc('Run qgis_process against the development profile (deploy first with `just deploy`). Examples: `just qgis-process plugins`, `just qgis-process run stratified_packager:package -- --PROJECT_PATH=tests/fixtures/e2e/project.qgs --STRATIFICATION_LAYER=strata --OUTPUT_DIRECTORY=out`')]
[group('QGIS')]
[script]
qgis-process *args:
    $ErrorActionPreference = 'Stop'
    $PSNativeCommandUseErrorActionPreference = $true
    if (-not $env:QGIS_EXECUTABLE_PATH) {
        {{ error }} "Error: environment variable QGIS_EXECUTABLE_PATH is not set."
        exit 1
    }
    $binDir = Split-Path "$env:QGIS_EXECUTABLE_PATH" -Parent
    # qgis_process sits next to the QGIS binary (Windows/Linux) or in a `bin`
    # subdirectory (macOS app bundle), and carries an extension on Windows only.
    $searchDirs = @("$binDir")
    $binSub = Join-Path "$binDir" 'bin'
    if (Test-Path $binSub -PathType Container) { $searchDirs += $binSub }
    $candidates = Get-ChildItem -Path $searchDirs -Filter 'qgis_process*' -File -ErrorAction SilentlyContinue
    if ($IsWindows) {
        $candidates = $candidates | Where-Object Extension -in '.exe', '.bat', '.cmd'
    }
    $exe = $candidates | Select-Object -First 1 -ExpandProperty FullName
    if (-not $exe) {
        {{ error }} "Could not find a qgis_process executable near $env:QGIS_EXECUTABLE_PATH"
        exit 1
    }
    if ($env:QGIS_PROFILES_DIR) {
        # qgis_process resolves the profile itself (profiles.ini defaultProfile) under
        # <QGIS_CUSTOM_CONFIG_PATH>/profiles/, so pass the *parent* of the profiles dir —
        # the same location the `qgis` recipe hands to --profiles-path. Passing the profile
        # dir itself makes qgis_process double the path and miss every profile plugin.
        $env:QGIS_CUSTOM_CONFIG_PATH = Split-Path "$env:QGIS_PROFILES_DIR" -Parent
        Write-Host "Using QGIS config root $env:QGIS_CUSTOM_CONFIG_PATH (profile comes from its profiles.ini)"
    }
    # just only accepts dashed tokens (e.g. --PROJECT_PATH) after a `--`, but qgis_process
    # ignores dashed arguments placed after one. Calling through a function makes the
    # PowerShell command parser consume that first `--` and hand every remaining token to
    # $args verbatim (a second `--` passes through for qgis_process's bare KEY=VALUE form;
    # pwsh -File / [positional-arguments] would split `-name:value` tokens at the colon).
    function Invoke-QgisProcess {
        {{ title }} "Running $exe $args..."
        & "$exe" @args
    }
    Invoke-QgisProcess {{ args }}

[doc('Shortcut to run deploy and qgis in sequence')]
[group('QGIS')]
@run profile='':
    just deploy '{{ profile }}'
    just qgis '{{ profile }}'

[doc('Run tests')]
[group('Testing')]
test *pytest_args:
    @{{ title }} "Running tests..."
    uv run --group test --exact pytest {{ pytest_args }}

[arg('port', pattern='102[4-9]|10[3-9]\d|1[1-9]\d{2}|[2-9]\d{3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5]', help='From 1024 to 65535')]
[doc('Serve test coverage reports locally (available at http://localhost:PORT)')]
[group('Testing')]
serve-cov port="8080":
    @{{ title }} "Starting test coverage server..."
    uv run -m http.server --directory htmlcov {{ port }}

[arg('port', pattern='102[4-9]|10[3-9]\d|1[1-9]\d{2}|[2-9]\d{3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d{2}|655[0-2]\d|6553[0-5]', help='From 1024 to 65535')]
[doc('Open test coverage reports in the default browser (development server must be running)')]
[group('Testing')]
browse-cov port="8080":
    @{{ title }} "Opening test coverage reports..."
    uv run -m webbrowser -t http://localhost:{{ port }}
