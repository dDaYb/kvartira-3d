param(
    [switch]$Local
)

$ErrorActionPreference = 'Stop'
$site = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = (Resolve-Path (Join-Path $site '..')).Path
$blender = Join-Path $project 'tmp\tools\blender-5.2.3-windows-x64\blender.exe'
if (-not (Test-Path -LiteralPath $blender)) {
    throw "Blender 5.2.3 not found: $blender"
}

$sourceFile = Join-Path $site 'источник.txt'
$line = Get-Content -LiteralPath $sourceFile -Encoding UTF8 |
    Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') } |
    Select-Object -First 1
if (-not $line) {
    throw 'источник.txt has no blend path'
}
$blend = [System.IO.Path]::GetFullPath((Join-Path $site $line.Trim()))
if (-not (Test-Path -LiteralPath $blend)) {
    throw "Blend file not found: $blend"
}

$glb = Join-Path $site 'model\apartment.glb'
$info = Join-Path $site 'model\info.json'
$python = Join-Path $site 'scripts\export_web.py'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $glb) | Out-Null

& $blender --background --disable-autoexec --python $python -- $blend $glb $info
if ($LASTEXITCODE -ne 0) {
    throw "Blender exited with code $LASTEXITCODE"
}

function Get-SitePassword {
    if ($env:SITE_PASSWORD) { return $env:SITE_PASSWORD }
    $secure = Read-Host 'Пароль сайта' -AsSecureString
    if (-not $secure -or $secure.Length -eq 0) {
        throw 'Пароль пустой. Можно заранее задать переменную SITE_PASSWORD.'
    }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

$manifest = Join-Path $site 'model\crypt\manifest.json'
$protected = Test-Path -LiteralPath $manifest
if ($protected) {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw 'Сайт зашифрован, для новой модели нужен Node.js.'
    }
    $hadPassword = [bool]$env:SITE_PASSWORD
    if (-not $hadPassword) { $env:SITE_PASSWORD = Get-SitePassword }
    try {
        & node (Join-Path $site 'scripts\encrypt-site.mjs') --only 'model/apartment.glb' --only 'model/info.json'
        if ($LASTEXITCODE -ne 0) { throw "Шифрование завершилось с кодом $LASTEXITCODE" }
    }
    finally {
        if (-not $hadPassword) { Remove-Item Env:SITE_PASSWORD -ErrorAction SilentlyContinue }
    }
}
else {
    Write-Host 'Сайт ещё не закрыт паролем. В git попадёт открытый GLB. Закрыть: node scripts/encrypt-site.mjs'
}

if ($Local) {
    Write-Host "Updated locally: $glb"
    exit 0
}

Push-Location -LiteralPath $site
try {
    if ($protected) {
        git add -- 'model/crypt/apartment.glb.bin' 'model/crypt/info.json.bin' 'model/crypt/manifest.json'
        $pending = git status --porcelain -- 'model/crypt/apartment.glb.bin' 'model/crypt/info.json.bin' 'model/crypt/manifest.json'
    }
    else {
        git add -- 'model/apartment.glb' 'model/info.json'
        $pending = git status --porcelain -- 'model/apartment.glb' 'model/info.json'
    }
    if (-not $pending) {
        Write-Host 'GLB is unchanged. Nothing to push.'
        exit 0
    }
    $message = 'Обновить 3D-модель для просмотра.'
    $name = git config --get user.name
    $email = git config --get user.email
    if ($name -and $email) {
        git commit -m $message
    }
    else {
        $login = gh api user --jq .login
        $id = gh api user --jq .id
        $mail = gh api user --jq .email
        if (-not $mail -or $mail -eq 'null') {
            $mail = '{0}+{1}@users.noreply.github.com' -f $id, $login
        }
        git -c "user.name=$login" -c "user.email=$mail" commit -m $message
    }
    git push
    Write-Host 'Pushed. GitHub Pages will refresh the same URL.'
}
finally {
    Pop-Location
}
