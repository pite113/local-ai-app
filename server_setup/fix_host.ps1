$p = 'C:\local-ai-app\.env'
$c = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
if ($c -match 'HOST=127\.0\.0\.1') {
    $c = $c.Replace('HOST=127.0.0.1', 'HOST=0.0.0.0')
    [System.IO.File]::WriteAllText($p, $c, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host HOST_FIXED
} else {
    Write-Host HOST_ALREADY_OK
}
