$p = 'C:\local-ai-app\.env'
$c = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
if ($c -notmatch 'TECH_KEY=') {
    $c = $c + "`r`nTECH_KEY=tk-5HpQ8mWz3K`r`n"
    [System.IO.File]::WriteAllText($p, $c, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host TECH_KEY_ADDED
} else {
    Write-Host TECH_KEY_EXISTS
}
