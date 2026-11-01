param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('install','restore')]
    [string]$Action
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PatchRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$GameRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PatchRoot))
$StateDir = [IO.Path]::Combine($PatchRoot, 'state')
$ActivePath = [IO.Path]::Combine($StateDir, 'active.json')
$ReceiptPath = [IO.Path]::Combine($StateDir, 'last-restored.json')
$BackupRoot = [IO.Path]::Combine($PatchRoot, 'backup')
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Get-ShaBytes([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Get-ShaFile([string]$Path) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}
function Assert-Sha([string]$Value) {
    if ($Value -notmatch '^[0-9a-fA-F]{64}$') { throw 'Invalid SHA-256 in manifest.' }
}
function Assert-NoReparse([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if ([IO.File]::Exists($current) -or [IO.Directory]::Exists($current)) {
            if (([IO.File]::GetAttributes($current) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Link or reparse point is not supported: $current" }
        }
        $parent = [IO.Directory]::GetParent($current)
        if ($null -eq $parent) { break }
        $current = $parent.FullName
    }
}
function Resolve-Relative([string]$Root, [string]$Relative, [bool]$GameTarget) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative) -or $Relative.Contains('\')) { throw "Invalid relative path: $Relative" }
    $segments = $Relative.Split('/')
    foreach ($segment in $segments) {
        if ([string]::IsNullOrEmpty($segment) -or $segment -eq '.' -or $segment -eq '..' -or $segment -match '[<>:"|?*\x00-\x1f]' -or $segment.EndsWith('.') -or $segment.EndsWith(' ') -or $segment -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$') { throw "Invalid Windows path: $Relative" }
    }
    if ($GameTarget -and [StringComparer]::OrdinalIgnoreCase.Equals($segments[0], 'KoreanPatch')) { throw 'Manifest target overlaps KoreanPatch.' }
    $native = $Relative.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $full = [IO.Path]::GetFullPath([IO.Path]::Combine($Root, $native))
    $prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Path is outside its root: $Relative" }
    Assert-NoReparse $full
    return $full
}
function Read-Json([string]$Path) {
    if (-not [IO.File]::Exists($Path)) { throw "Missing JSON file: $Path" }
    return ([IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json)
}
function Save-Json([string]$Path, $Value) {
    $dir = [IO.Path]::GetDirectoryName($Path)
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    $temp = [IO.Path]::Combine($dir, '.state-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $json = $Value | ConvertTo-Json -Depth 30
        [IO.File]::WriteAllText($temp, $json, $Utf8)
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temp, $Path, [System.Management.Automation.Language.NullString]::Value) }
        else { [IO.File]::Move($temp, $Path) }
    } finally { if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) } }
}
function Save-Active($State) { Save-Json $ActivePath $State }
function Check-Manifest($Manifest) {
    if ($Manifest.format -ne 'koreanpatch-windows-v2/manifest-v1' -or [string]::IsNullOrWhiteSpace([string]$Manifest.game_id) -or [string]::IsNullOrWhiteSpace([string]$Manifest.patch_id)) { throw 'Unsupported manifest or missing identity.' }
    if (@($Manifest.requirements).Count -lt 1 -or @($Manifest.operations).Count -lt 1) { throw 'At least one game identity requirement and operation are required.' }
    foreach ($req in @($Manifest.requirements)) {
        if ($null -eq $req) { throw 'Null requirement.' }
        Assert-Sha ([string]$req.sha256)
        $null = Resolve-Relative $GameRoot ([string]$req.path) $true
    }
    $seen = New-Object 'System.Collections.Generic.List[string]'
    foreach ($op in @($Manifest.operations)) {
        if ($null -eq $op -or $op.kind -notin @('add','replace')) { throw 'Invalid file operation.' }
        $relative = [string]$op.path
        $null = Resolve-Relative $GameRoot $relative $true
        foreach ($prior in $seen) {
            if ([StringComparer]::OrdinalIgnoreCase.Equals($relative,$prior) -or $relative.StartsWith($prior+'/',[StringComparison]::OrdinalIgnoreCase) -or $prior.StartsWith($relative+'/',[StringComparison]::OrdinalIgnoreCase)) { throw "Duplicate or overlapping paths: $relative" }
        }
        $seen.Add($relative)
        if ($op.kind -eq 'replace') { Assert-Sha ([string]$op.before_sha256) }
        elseif ($null -ne $op.before_sha256) { throw 'Add operation must expect absence.' }
        Assert-Sha ([string]$op.payload_sha256); Assert-Sha ([string]$op.after_sha256)
        if ([string]$op.payload_sha256 -ine [string]$op.after_sha256) { throw 'Payload and installed hash must match for a direct file operation.' }
        if (-not ([string]$op.payload).StartsWith('payload/',[StringComparison]::OrdinalIgnoreCase)) { throw 'Payload must be under payload/.' }
        $null = Resolve-Relative $PatchRoot ([string]$op.payload) $false
    }
}
function Check-Requirements($Manifest) {
    foreach ($req in @($Manifest.requirements)) {
        $p = Resolve-Relative $GameRoot ([string]$req.path) $true
        if (-not [IO.File]::Exists($p) -or (Get-ShaFile $p) -ine [string]$req.sha256) { throw "Unsupported game or changed requirement: $($req.path)" }
    }
}
function Check-NewInstall($Manifest) {
    Check-Requirements $Manifest
    [long]$space = 1048576
    foreach ($op in @($Manifest.operations)) {
        $target = Resolve-Relative $GameRoot ([string]$op.path) $true
        $payload = Resolve-Relative $PatchRoot ([string]$op.payload) $false
        if (-not [IO.File]::Exists($payload) -or (Get-ShaFile $payload) -ine [string]$op.payload_sha256) { throw "Payload missing or changed: $($op.payload)" }
        $space += (New-Object IO.FileInfo($payload)).Length
        if ($op.kind -eq 'add') {
            if ([IO.File]::Exists($target) -or [IO.Directory]::Exists($target)) { throw "Add target already exists: $($op.path)" }
        } else {
            if (-not [IO.File]::Exists($target) -or (Get-ShaFile $target) -ine [string]$op.before_sha256) { throw "Original missing or changed: $($op.path)" }
            $space += (New-Object IO.FileInfo($target)).Length
            $open = [IO.File]::Open($target,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); $open.Dispose()
        }
    }
    $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($GameRoot))
    if ($drive.AvailableFreeSpace -lt $space) { throw 'Insufficient free space for payload and backups.' }
    if ([IO.Directory]::Exists($BackupRoot)) { throw 'Untracked backup directory exists; no files were removed.' }
}
function Read-State([string]$Path) {
    $s = Read-Json $Path
    if ($s.format -ne 'koreanpatch-windows-v2/state-v1' -or -not [StringComparer]::OrdinalIgnoreCase.Equals([string]$s.game_root,$GameRoot) -or [string]$s.id -notmatch '^[a-f0-9]{32}$') { throw 'State belongs to another root or is invalid.' }
    if ([string]$s.status -notin @('preparing','applying','installed','restored_cleanup_pending','restored')) { throw 'Unknown installation state.' }
    if ($Path -eq $ActivePath -and $s.status -eq 'restored') { throw 'Active state conflicts with restored status.' }
    if ($Path -eq $ReceiptPath -and $s.status -ne 'restored') { throw 'Restored receipt has an invalid status.' }
    Assert-Sha ([string]$s.manifest_sha256)
    Check-Manifest $s.manifest
    return $s
}
function Backup-Path($State,[int]$Index) { return [IO.Path]::Combine($BackupRoot, [string]$State.id, ($Index.ToString('D4')+'.bin')) }
function Verify-Original($State) {
    foreach ($op in @($State.manifest.operations)) {
        $target = Resolve-Relative $GameRoot ([string]$op.path) $true
        if ($op.kind -eq 'replace') {
            if (-not [IO.File]::Exists($target) -or (Get-ShaFile $target) -ine [string]$op.before_sha256) { throw "Original not restored: $($op.path)" }
        } elseif ([IO.File]::Exists($target) -or [IO.Directory]::Exists($target)) { throw "Added file still exists: $($op.path)" }
    }
}
function Verify-Installed($State) {
    foreach ($req in @($State.manifest.requirements)) {
        $expected = [string]$req.sha256
        foreach ($op in @($State.manifest.operations)) {
            if ([StringComparer]::OrdinalIgnoreCase.Equals([string]$req.path,[string]$op.path)) {
                if ($op.kind -ne 'replace' -or $expected -ine [string]$op.before_sha256) { throw "Identity requirement conflicts with operation: $($req.path)" }
                $expected = [string]$op.after_sha256
                break
            }
        }
        $identity = Resolve-Relative $GameRoot ([string]$req.path) $true
        if (-not [IO.File]::Exists($identity) -or (Get-ShaFile $identity) -ine $expected) { throw "Unsupported game or changed requirement: $($req.path)" }
    }
    $index = 0
    foreach ($op in @($State.manifest.operations)) {
        $target = Resolve-Relative $GameRoot ([string]$op.path) $true
        if (-not [IO.File]::Exists($target) -or (Get-ShaFile $target) -ine [string]$op.after_sha256) { throw "Installed file changed: $($op.path)" }
        $payload = Resolve-Relative $PatchRoot ([string]$op.payload) $false
        if (-not [IO.File]::Exists($payload) -or (Get-ShaFile $payload) -ine [string]$op.payload_sha256) { throw "Payload missing or changed: $($op.payload)" }
        if ($op.kind -eq 'replace') {
            $backup = Backup-Path $State $index
            if (-not [IO.File]::Exists($backup) -or (Get-ShaFile $backup) -ine [string]$op.before_sha256) { throw "Backup missing or changed: $($op.path)" }
        }
        $index++
    }
}
function Ensure-Parents([string]$Target,$State) {
    $missing = New-Object 'System.Collections.Generic.List[string]'
    $p = [IO.Path]::GetDirectoryName($Target)
    while (-not [IO.Directory]::Exists($p)) {
        $missing.Add($p)
        $p = [IO.Path]::GetDirectoryName($p)
        if (-not $p) { throw 'Cannot locate target parent.' }
    }
    for ($i=$missing.Count-1; $i -ge 0; $i--) {
        $dir = $missing[$i]; Assert-NoReparse $dir
        $State.created_dirs = @($State.created_dirs) + @($dir)
        Save-Active $State
        [IO.Directory]::CreateDirectory($dir) | Out-Null
    }
}
function Copy-IntoTarget([string]$Source,[string]$Target,[string]$Hash,[bool]$Replace,$State) {
    $tmp = [IO.Path]::Combine([IO.Path]::GetDirectoryName($Target), '.koreanpatch-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    if ([IO.File]::Exists($tmp) -or [IO.Directory]::Exists($tmp)) { throw 'Temporary path already exists.' }
    $State.temp_files = @($State.temp_files) + @($tmp)
    Save-Active $State
    try {
        [IO.File]::Copy($Source,$tmp,$false)
        if ((Get-ShaFile $tmp) -ine $Hash) { throw 'Temporary file hash mismatch.' }
        if ($Replace) { [IO.File]::Replace($tmp,$Target,[System.Management.Automation.Language.NullString]::Value) }
        else { [IO.File]::Move($tmp,$Target) }
    } finally { if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) } }
}
function Cleanup-Restored($State) {
    Verify-Original $State
    foreach ($temp in @($State.temp_files)) {
        $temp = [string]$temp
        if ([IO.Path]::GetFileName($temp) -notmatch '^\.koreanpatch-[a-f0-9]{32}\.tmp$') { throw 'Invalid recorded temporary file.' }
        $validParent = $false
        foreach ($op in @($State.manifest.operations)) {
            $target = Resolve-Relative $GameRoot ([string]$op.path) $true
            if ([StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetDirectoryName($temp),[IO.Path]::GetDirectoryName($target))) { $validParent = $true; break }
        }
        if (-not $validParent) { throw 'Temporary file is outside its target directory.' }
        Assert-NoReparse $temp
        if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
        if ([IO.Directory]::Exists($temp)) { throw 'Temporary path is a directory.' }
    }
    $index = 0
    foreach ($op in @($State.manifest.operations)) {
        if ($op.kind -eq 'replace') {
            $backup = Backup-Path $State $index
            if ([IO.File]::Exists($backup)) {
                if ((Get-ShaFile $backup) -ine [string]$op.before_sha256) { throw "Backup changed; cleanup refused: $($op.path)" }
                [IO.File]::Delete($backup)
            }
        }
        $index++
    }
    $own = [IO.Path]::Combine($BackupRoot,[string]$State.id)
    if ([IO.Directory]::Exists($own)) { [IO.Directory]::Delete($own,$false) }
    if ([IO.Directory]::Exists($BackupRoot)) { [IO.Directory]::Delete($BackupRoot,$false) }
    $dirs = @($State.created_dirs)
    for ($i=$dirs.Count-1; $i -ge 0; $i--) {
        $dir = [string]$dirs[$i]
        Assert-NoReparse $dir
        if ([IO.Directory]::Exists($dir) -and [IO.Directory]::GetFileSystemEntries($dir).Length -eq 0) { [IO.Directory]::Delete($dir,$false) }
    }
    $State.status = 'restored'
    Save-Json $ReceiptPath $State
    [IO.File]::Delete($ActivePath)
}
function Restore-State($State) {
    if ($State.status -eq 'restored_cleanup_pending') { Cleanup-Restored $State; return }
    $index = 0
    foreach ($op in @($State.manifest.operations)) {
        $target = Resolve-Relative $GameRoot ([string]$op.path) $true
        if ($op.kind -eq 'replace') {
            if (-not [IO.File]::Exists($target)) { throw "Restore conflict; file missing: $($op.path)" }
            $actual = Get-ShaFile $target
            if ($actual -ine [string]$op.before_sha256 -and $actual -ine [string]$op.after_sha256) { throw "Restore conflict; file changed: $($op.path)" }
            if ($actual -ieq [string]$op.after_sha256 -and $actual -ine [string]$op.before_sha256) {
                $backup = Backup-Path $State $index
                if (-not [IO.File]::Exists($backup) -or (Get-ShaFile $backup) -ine [string]$op.before_sha256) { throw "Restore backup missing or changed: $($op.path)" }
            }
        } elseif ([IO.File]::Exists($target)) {
            if ((Get-ShaFile $target) -ine [string]$op.after_sha256) { throw "Restore conflict; added file changed: $($op.path)" }
        } elseif ([IO.Directory]::Exists($target)) { throw "Restore conflict; target is a directory: $($op.path)" }
        $index++
    }
    $index = 0
    foreach ($op in @($State.manifest.operations)) {
        $target = Resolve-Relative $GameRoot ([string]$op.path) $true
        if ($op.kind -eq 'replace') {
            if ((Get-ShaFile $target) -ine [string]$op.before_sha256) { Copy-IntoTarget (Backup-Path $State $index) $target ([string]$op.before_sha256) $true $State }
        } elseif ([IO.File]::Exists($target)) { [IO.File]::Delete($target) }
        $index++
    }
    Verify-Original $State
    $State.status = 'restored_cleanup_pending'
    Save-Active $State
    Cleanup-Restored $State
}
function Install-Patch {
    $manifestPath = [IO.Path]::Combine($PatchRoot,'manifest.json')
    $manifest = Read-Json $manifestPath
    Check-Manifest $manifest
    $manifestHash = Get-ShaFile $manifestPath
    if ([IO.File]::Exists($ActivePath)) {
        $active = Read-State $ActivePath
        if ($active.status -eq 'installed') {
            if ([string]$active.manifest_sha256 -ine $manifestHash) { throw 'Another patch snapshot is active; restore it first.' }
            Verify-Installed $active
            Write-Host 'This patch is already installed and verified.'
            return
        }
        Restore-State $active
    }
    Check-NewInstall $manifest
    $state = [pscustomobject]@{format='koreanpatch-windows-v2/state-v1'; id=[Guid]::NewGuid().ToString('N'); game_root=$GameRoot; manifest_sha256=$manifestHash; manifest=$manifest; status='preparing'; created_dirs=@(); temp_files=@()}
    Save-Active $state
    try {
        $index=0
        foreach ($op in @($manifest.operations)) {
            if ($op.kind -eq 'replace') {
                $target = Resolve-Relative $GameRoot ([string]$op.path) $true
                $backup = Backup-Path $state $index
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($backup)) | Out-Null
                [IO.File]::Copy($target,$backup,$false)
                if ((Get-ShaFile $backup) -ine [string]$op.before_sha256) { throw "Backup hash mismatch: $($op.path)" }
            }
            $index++
        }
        $state.status='applying'; Save-Active $state
        foreach ($op in @($manifest.operations)) {
            $target = Resolve-Relative $GameRoot ([string]$op.path) $true
            $payload = Resolve-Relative $PatchRoot ([string]$op.payload) $false
            Ensure-Parents $target $state
            Copy-IntoTarget $payload $target ([string]$op.after_sha256) ($op.kind -eq 'replace') $state
        }
        Verify-Installed $state
        $state.status='installed'; Save-Active $state
        Write-Host 'Installation completed.'
    } catch {
        $reason = $_.Exception.Message
        try { Restore-State $state } catch { throw "Install failed: $reason. Rollback failed; backup and state retained: $($_.Exception.Message)" }
        throw "Install failed and changes were restored: $reason"
    }
}
function Restore-Patch {
    if ([IO.File]::Exists($ActivePath)) {
        $state = Read-State $ActivePath
        Restore-State $state
        Write-Host 'Restore and backup cleanup completed.'
    } elseif ([IO.File]::Exists($ReceiptPath)) {
        $receipt = Read-State $ReceiptPath
        Verify-Original $receipt
        Write-Host 'Already restored; original state verified.'
    } else {
        $manifest = Read-Json ([IO.Path]::Combine($PatchRoot,'manifest.json'))
        Check-Manifest $manifest
        Verify-Original ([pscustomobject]@{manifest=$manifest})
        Write-Host 'No active installation; original state verified.'
    }
}

$mutex=$null; $locked=$false
try {
    Assert-NoReparse $GameRoot
    $rootBytes = [Text.Encoding]::UTF8.GetBytes($GameRoot.ToUpperInvariant())
    $lockName = 'Global\KoreanPatch-' + (Get-ShaBytes $rootBytes)
    $mutex = New-Object Threading.Mutex($false,$lockName)
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { throw 'Another KoreanPatch operation is running for this game folder.' }
    Write-Host 'WARNING: Close the game, launcher updates, mod managers, and programs that may change game files.'
    Write-Host 'Do not close this window or turn off the computer until the operation finishes.'
    $answer = Read-Host 'Continue? [y/N]'
    if ($answer -notmatch '^(?i:y|yes)$') { throw 'Cancelled; no game files were changed.' }
    if ($Action -eq 'install') { Install-Patch } else { Restore-Patch }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
