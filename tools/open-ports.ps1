# Let other PCs on the network reach stand servers running inside WSL.
#
# WSL in mirrored networking mode shares the PC's IP address, but the Hyper-V
# firewall in front of WSL blocks every incoming connection by default. This
# adds an allow rule there and in the normal Windows firewall, for the given
# ports only. Needs an administrator PowerShell (./stand.sh firewall asks).
#
#   .\open-ports.ps1                      # 8767: Human or Bot's human-player page
#   .\open-ports.ps1 -Ports 8765,8766     # other demos too
#   .\open-ports.ps1 -Remove              # take the rules away again

param([int[]]$Ports = @(8767), [switch]$Remove)

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Run this in an administrator PowerShell."; exit 1 }

$wsl = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'   # WSL's ID in the Hyper-V firewall

foreach ($p in $Ports) {
    $name = "AI Stand $p"
    Remove-NetFirewallHyperVRule -Name $name -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
    if ($Remove) { Write-Host "closed $p"; continue }
    New-NetFirewallHyperVRule -Name $name -DisplayName $name -Direction Inbound -VMCreatorId $wsl `
        -Protocol TCP -LocalPorts $p -Action Allow | Out-Null
    New-NetFirewallRule -Name $name -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $p `
        -Action Allow -Profile Any | Out-Null
    Write-Host "opened $p"
}
