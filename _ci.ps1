$token=[Environment]::GetEnvironmentVariable("GH_TOKEN","User")
$h=@{Authorization="token $token";Accept="application/vnd.github+json";"User-Agent"="veles-ci"}
1..40 | ForEach-Object {
  $r=Invoke-RestMethod -Uri "https://api.github.com/repos/Octavian-Labs/veles/pulls/22" -Headers $h
  $cr=Invoke-RestMethod -Uri "https://api.github.com/repos/Octavian-Labs/veles/commits/$($r.head.sha)/check-runs" -Headers $h
  $st=$cr.check_runs | ForEach-Object { "$($_.name):$($_.status)/$($_.conclusion)" }
  Write-Output ($st -join " | ")
  if ($cr.check_runs.Count -ge 3 -and -not ($st -match "in_progress|queued")) { break }
  Start-Sleep 20
}
