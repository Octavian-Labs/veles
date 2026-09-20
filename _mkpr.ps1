$token=[Environment]::GetEnvironmentVariable("GH_TOKEN","User")
$h=@{Authorization="token $token";Accept="application/vnd.github+json";"User-Agent"="veles-ci"}
$b=@{title="цель macos (x86-64): Mach-O, биб/*.macos.раз, CI macos";head="фича/macos";base="develop";body="Эмиттер Mach-O x86_64 (иск/махо.раз), прагма ;цель macos, --цель macos, платформенные модули биб для BSD-сисвызовов, сиды искра_мак/разум_мак, CI-джоба macos-14. Прогон 11/11 Win, 10/10 Linux."}|ConvertTo-Json
$bytes=[Text.Encoding]::UTF8.GetBytes($b)
$r=Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/Octavian-Labs/veles/pulls" -Headers $h -Body $bytes -ContentType "application/json; charset=utf-8"
"PR #$($r.number): $($r.html_url)"
