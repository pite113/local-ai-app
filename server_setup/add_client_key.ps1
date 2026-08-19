$p = 'C:\local-ai-app\.env'
$c = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
if ($c -notmatch 'CLIENT_KEY=') {
    $c = $c + "`r`nCLIENT_KEY=cl-8K2pWmQ4xZ`r`n"
    [System.IO.File]::WriteAllText($p, $c, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host CLIENT_KEY_ADDED
} else {
    Write-Host CLIENT_KEY_EXISTS
}
