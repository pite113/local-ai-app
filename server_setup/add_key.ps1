$p = 'C:\local-ai-app\.env'
$c = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
if ($c -notmatch 'ADMIN_KEY=') {
    $c = $c + "`r`n# 管理员口令`r`nADMIN_KEY=wk9fK3xQ7vZ2`r`n"
    [System.IO.File]::WriteAllText($p, $c, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host KEY_ADDED
} else {
    Write-Host KEY_EXISTS
}
