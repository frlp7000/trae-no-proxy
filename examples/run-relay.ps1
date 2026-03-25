param(
    [string]$UpstreamBase,
    [int]$ListenPort = 8787,
    [string]$LogDir = '.tmp\trae-relay'
)

if ([string]::IsNullOrWhiteSpace($UpstreamBase)) {
    throw 'Please pass -UpstreamBase https://your.gateway.example/v1'
}

trae-patch relay --listen-host 127.0.0.1 --listen-port $ListenPort --upstream-base $UpstreamBase --log-dir $LogDir