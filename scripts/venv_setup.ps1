#Requires -Version 5.1
<#
.SYNOPSIS
    Provision the prerequisite tooling and bootstrap the QGIS-aware development
    environment for the Stratified Packager plugin.

.DESCRIPTION
    Ensures git, just and (only when running under legacy Windows PowerShell) pwsh
    are installed and discoverable on PATH, then delegates the remaining setup to
    `just bootstrap`.

    On Windows the tools are provisioned with Scoop, which is installed first when
    missing; tools already discoverable on PATH are left untouched. On Linux and
    macOS (PowerShell Core) the script verifies git is present and installs just
    via its official installer when absent.

    Compatible with Windows PowerShell 5.1 through PowerShell 7.6+ on Windows, and
    with PowerShell Core on Linux and macOS.

.PARAMETER QgisPrefixPath
    Absolute path of the 'apps/qgis' or 'apps/qgis-ltr' folder inside the QGIS
    installation directory. Forwarded verbatim to `just bootstrap`.

.PARAMETER QgisProfilePath
    Absolute path of the QGIS profile folder holding the user settings and plugins.
    Forwarded to `just bootstrap`; leave empty to use the default profile.

.EXAMPLE
    pwsh -File scripts/venv_setup.ps1 'C:\Program Files\QGIS 3.40.15\apps\qgis-ltr'

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/venv_setup.ps1
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string] $QgisPrefixPath = '',

    [Parameter(Position = 1)]
    [string] $QgisProfilePath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:StepNumber = 0

# Windows PowerShell (<= 5.1) only ever runs on Windows; $IsWindows exists from 6.0.
$script:OnWindows = if ($PSVersionTable.PSVersion.Major -ge 6) { [bool] $IsWindows } else { $true }


function Write-Step {
    <# .SYNOPSIS Print a numbered section header. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $Message)

    $script:StepNumber++
    Write-Host ''
    Write-Host "[$($script:StepNumber)] $Message..." -ForegroundColor Cyan
}


function Test-CommandAvailable {
    <# .SYNOPSIS Return whether a command is discoverable on PATH. #>
    [CmdletBinding()]
    [OutputType([bool])]
    param([Parameter(Mandatory)][string] $Name)

    return [bool] (Get-Command -Name $Name -ErrorAction SilentlyContinue)
}


function Add-PathEntry {
    <# .SYNOPSIS Prepend a directory to the current session's PATH (idempotent). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $Directory)

    if (-not (Test-Path -LiteralPath $Directory)) { return }

    $resolved = (Resolve-Path -LiteralPath $Directory).Path
    $separator = [System.IO.Path]::PathSeparator
    $existing = $env:PATH -split [regex]::Escape($separator)
    if ($existing -notcontains $resolved) {
        $env:PATH = "$resolved$separator$env:PATH"
    }
}


function Invoke-Native {
    <# .SYNOPSIS Run an external command and throw on a non-zero exit code. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Executable,
        [string[]] $Arguments = @()
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Executable $($Arguments -join ' ')' exited with code $LASTEXITCODE."
    }
}


function Install-Scoop {
    <# .SYNOPSIS Install Scoop for the current user when it is not already present. #>
    [CmdletBinding()]
    param()

    if (Test-CommandAvailable -Name 'scoop') {
        Write-Host '[OK] Scoop already installed.' -ForegroundColor Green
        return
    }

    Write-Host '[..] Installing Scoop for the current user...'
    # Scoop's documented bootstrap pipes its installer straight into the session.
    Invoke-RestMethod -Uri 'https://get.scoop.sh' | Invoke-Expression

    Add-PathEntry -Directory (Join-Path -Path $env:USERPROFILE -ChildPath 'scoop\shims')

    Write-Host '[OK] Scoop ready.' -ForegroundColor Green
}


function Install-ScoopPackage {
    <# .SYNOPSIS Install a Scoop package unless its command is already on PATH. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Command,
        [Parameter(Mandatory)][string] $Package
    )

    if (Test-CommandAvailable -Name $Command) {
        Write-Host "[OK] '$Command' already on PATH; leaving it untouched." -ForegroundColor Green
        return
    }

    Write-Host "[..] Installing '$Package' via Scoop..."
    Invoke-Native -Executable 'scoop' -Arguments 'install', $Package
    Write-Host "[OK] '$Command' ready." -ForegroundColor Green
}


function Confirm-GitAvailable {
    <# .SYNOPSIS Ensure git is on PATH, otherwise fail with install guidance. #>
    [CmdletBinding()]
    param()

    if (Test-CommandAvailable -Name 'git') {
        Write-Host '[OK] git already available.' -ForegroundColor Green
        return
    }

    throw @'
git was not found on PATH and cannot be installed automatically on this platform.
Install it with your system package manager and re-run this script, e.g.:
  Debian/Ubuntu : sudo apt-get install -y git
  Fedora/RHEL   : sudo dnf install -y git
  Arch          : sudo pacman -S --noconfirm git
  macOS         : xcode-select --install   (or: brew install git)
'@
}


function Install-JustOnUnix {
    <# .SYNOPSIS Install just into ~/.local/bin via its official installer when absent. #>
    [CmdletBinding()]
    param()

    if (Test-CommandAvailable -Name 'just') {
        Write-Host '[OK] just already available.' -ForegroundColor Green
        return
    }

    $installDir = Join-Path -Path $HOME -ChildPath '.local/bin'
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null

    Write-Host "[..] Installing just into '$installDir' via the official installer..."
    Invoke-Native -Executable 'bash' -Arguments '-c', `
        "curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to '$installDir'"

    Add-PathEntry -Directory $installDir

    Write-Host '[OK] just ready.' -ForegroundColor Green
}


function Invoke-Setup {
    <# .SYNOPSIS Orchestrate the prerequisite checks and run `just bootstrap`. #>
    [CmdletBinding()]
    param()

    Write-Host '============================================' -ForegroundColor Cyan
    Write-Host '  QGIS virtual environment setup' -ForegroundColor Cyan
    Write-Host '============================================' -ForegroundColor Cyan

    if ($QgisPrefixPath) { Write-Host "[..] QGIS installation path: $QgisPrefixPath" }
    if ($QgisProfilePath) { Write-Host "[..] QGIS profile path: $QgisProfilePath" }

    # `just` resolves the justfile relative to the working directory, so run from
    # the repository root regardless of where this script was invoked from.
    $repoRoot = Split-Path -Parent $PSScriptRoot
    Push-Location -LiteralPath $repoRoot
    try {
        if ($script:OnWindows) {
            # The justfile interpreter (pwsh) is only missing under legacy Windows
            # PowerShell; on PowerShell Core it is already running this script.
            $required = [ordered]@{ git = 'git'; just = 'just' }
            if ($PSVersionTable.PSVersion.Major -lt 6) { $required['pwsh'] = 'pwsh' }

            $missing = @($required.GetEnumerator() |
                Where-Object { -not (Test-CommandAvailable -Name $_.Key) })

            if ($missing.Count -eq 0) {
                Write-Step -Message 'Verifying prerequisites'
                Write-Host "[OK] $($required.Keys -join ', ') already on PATH; skipping Scoop." `
                    -ForegroundColor Green
            }
            else {
                # Scoop is only a delivery mechanism, so install it solely to provide
                # the tools that are actually missing.
                Write-Step -Message 'Ensuring Scoop is installed'
                Install-Scoop

                foreach ($tool in $missing) {
                    Write-Step -Message "Ensuring $($tool.Key) is installed"
                    Install-ScoopPackage -Command $tool.Key -Package $tool.Value
                }
            }
        }
        else {
            Write-Step -Message 'Ensuring git is installed'
            Confirm-GitAvailable

            Write-Step -Message 'Ensuring just is installed'
            Install-JustOnUnix
            # pwsh is already running this script on PowerShell Core; nothing to do.
        }

        # Add the folder where uv executables will be to the PATH
        $env:Path = $env:Path + [IO.Path]::PathSeparator + "$HOME\.local\bin"

        Write-Step -Message 'Running `just bootstrap`'
        # Preserve positional order: the profile path is the second argument, so the
        # prefix placeholder must precede it whenever a profile path is supplied.
        $bootstrapArgs = @('bootstrap')
        if ($QgisProfilePath) {
            $bootstrapArgs += $QgisPrefixPath, $QgisProfilePath
        }
        elseif ($QgisPrefixPath) {
            $bootstrapArgs += $QgisPrefixPath
        }
        Write-Host "[..] just $($bootstrapArgs -join ' ')"
        Invoke-Native -Executable 'just' -Arguments $bootstrapArgs
    }
    finally {
        Pop-Location
    }

    Write-Host ''
    Write-Host '============================================' -ForegroundColor Green
    Write-Host '  All set. The environment is configured.' -ForegroundColor Green
    Write-Host '============================================' -ForegroundColor Green
}


try {
    Invoke-Setup
    exit 0
}
catch {
    Write-Host ''
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
