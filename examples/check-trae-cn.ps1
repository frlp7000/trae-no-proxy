param(
    [string]$AppRoot,
    [string]$SettingsFile
)

$doctorArgs = @('doctor')
if ($AppRoot) {
    $doctorArgs += @('--app-root', $AppRoot)
}
if ($SettingsFile) {
    $doctorArgs += @('--settings-file', $SettingsFile)
}
trae-patch @doctorArgs

$inspectArgs = @('inspect')
if ($AppRoot) {
    $inspectArgs += @('--app-root', $AppRoot)
}
if ($SettingsFile) {
    $inspectArgs += @('--settings-file', $SettingsFile)
}
trae-patch @inspectArgs