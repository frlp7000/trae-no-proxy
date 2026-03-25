param(
    [string]$AppRoot,
    [string]$SettingsFile
)

$patchArgs = @('patch-all')
if ($AppRoot) {
    $patchArgs += @('--app-root', $AppRoot)
}
if ($SettingsFile) {
    $patchArgs += @('--settings-file', $SettingsFile)
}
trae-patch @patchArgs

$doctorArgs = @('doctor')
if ($AppRoot) {
    $doctorArgs += @('--app-root', $AppRoot)
}
if ($SettingsFile) {
    $doctorArgs += @('--settings-file', $SettingsFile)
}
trae-patch @doctorArgs