# KalshiWatchdog 开机自启 (选项A) — 需在【管理员 PowerShell】里跑一次。
# 为什么要管理员: "开机即启 / 登录前运行" 的计划任务注册需要提权; 登录后
# 自愈的 HKCU Run 键不需要提权, 二者并存 = 双保险。
#
# 关键设计 (保住 git 凭据):
#  - 任务【以当前登录用户身份】运行 (不是 SYSTEM) —— quant_loop 每刻 git push
#    要用你的凭据库, SYSTEM 跑会丢凭据。
#  - 触发器 = 开机(AtStartup) + 每5分钟重复(自愈) —— 开机后即使没人登录也拉起。
#  - watchdog.ps1 自身单例锁 + 两个 daemon 各自的 pid 锁 => 与 HKCU Run 键、
#    与已在跑的实例重复触发都无害 (幂等)。
#  - RunLevel Limited (非最高权限): 交易循环不需要管理员, 最小权限原则。

$ErrorActionPreference = "Stop"
$user = "$env:USERDOMAIN\$env:USERNAME"
$ps   = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
# NOT $args — that is a PowerShell automatic variable
$taskArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ' +
            '"D:\Polymarket-Kelshi\scripts\watchdog.ps1" -Loop'

$action  = New-ScheduledTaskAction -Execute $ps -Argument $taskArgs `
             -WorkingDirectory "D:\Polymarket-Kelshi"
$trigger = New-ScheduledTaskTrigger -AtStartup
# 开机触发本身只在启动时点火一次; 叠加5分钟重复 => 进程被杀也会5分钟内自愈
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)).Repetition
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)

# 以当前用户身份、开机即运行(不要求登录)。S4U = 无需存密码即可后台运行。
# -LogonType/-RunLevel 属于 principal 对象, 不是 Register 的直接参数 (上个版本
# 报错就是把 -LogonType 直接挂在 Register 上了)。
# 注意: S4U 无交互桌面 + 不加载完整凭据库 —— 开机后、你登录前, 交易循环/采集/
# 止损全部照跑 (用 .pem 密钥, 不依赖 git); 唯 git push 可能要等你登录后凭据库
# 加载才成功 (loop 的 git() 会自动重试, 无害)。HKCU Run 键仍在, 登录后补齐。
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U `
    -RunLevel Limited
Register-ScheduledTask -TaskName "KalshiWatchdogBoot" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Force

Write-Host "OK: registered KalshiWatchdogBoot as user $user"
Write-Host "boot-start + 5-min self-heal; runs Python loop + git under your creds"
Write-Host "self-check:"
Get-ScheduledTask -TaskName "KalshiWatchdogBoot" | Select-Object TaskName, State
