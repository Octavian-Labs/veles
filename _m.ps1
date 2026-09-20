$token=[Environment]::GetEnvironmentVariable("GH_TOKEN","User")
$h=@{Authorization="token $token";Accept="application/vnd.github+json";"User-Agent"="veles-ci"}
$r=Invoke-RestMethod -Uri "https://api.github.com/repos/Octavian-Labs/veles/pulls/22" -Headers $h
$cr=Invoke-RestMethod -Uri "https://api.github.com/repos/Octavian-Labs/veles/commits/$($r.head.sha)/check-runs" -Headers $h
($cr.check_runs | Where-Object {$_.name -eq "macos"}).details_url
