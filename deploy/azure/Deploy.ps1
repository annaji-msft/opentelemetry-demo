# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$ParameterFile,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
function Invoke-AzureCli { python "$PSScriptRoot\azure_cli.py" @args }
$parameters = Get-Content -LiteralPath $ParameterFile -Raw | ConvertFrom-Json
$prefix = $parameters.parameters.prefix.value
$names = @($parameters.parameters.apps.value.services.name) +
    @("$prefix-env", "$prefix-logs", "$prefix-insights")
$existing = Invoke-AzureCli resource list --subscription $SubscriptionId --resource-group $ResourceGroup -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect existing resources.' }
foreach ($resource in $existing) {
    if ($resource.name -in $names -and $resource.tags.managedBy -ne 'astronomy-aca') {
        throw "Refusing to modify unowned resource $($resource.id)"
    }
}
$arguments = @(
    '--subscription', $SubscriptionId, '--resource-group', $ResourceGroup,
    '--name', "$prefix-baseline", '--template-file', "$PSScriptRoot\main.bicep",
    '--parameters', "@$ParameterFile", '--only-show-errors'
)
Invoke-AzureCli deployment group validate @arguments --query 'properties.provisioningState' -o tsv
if ($LASTEXITCODE -ne 0) { throw 'ARM validation failed.' }
$preview = Invoke-AzureCli deployment group what-if @arguments --result-format ResourceIdOnly --no-pretty-print -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Deployment preview failed.' }
foreach ($change in $preview.changes) {
    $name = ($change.resourceId -split '/')[-1]
    if ($change.changeType -eq 'Delete') { throw "Unexpected deletion: $($change.resourceId)" }
    if ($change.changeType -notin @('NoChange', 'Ignore') -and $name -notin $names) {
        throw "Unexpected resource modification: $($change.resourceId)"
    }
    Write-Host "$($change.changeType): $($change.resourceId)"
}
if ($Apply) {
    $pending = @($parameters.parameters.apps.value.services)
    $waveFile = "$ParameterFile.wave.json"
    try {
        while ($pending.Count -gt 0) {
            $pendingNames = @($pending.name)
            $wave = @($pending | Where-Object {
                @($_.dependencies | Where-Object { $_ -in $pendingNames }).Count -eq 0
            })
            if ($wave.Count -eq 0) { throw 'Cyclic deployment dependencies.' }
            Write-Host "Deploying dependency wave: $($wave.name -join ', ')"
            $waveParameters = Get-Content -LiteralPath $ParameterFile -Raw | ConvertFrom-Json
            $waveParameters.parameters.apps.value.services = $wave
            $waveParameters | ConvertTo-Json -Depth 100 -Compress |
                Set-Content -LiteralPath $waveFile -Encoding utf8
            $waveArguments = @($arguments | ForEach-Object {
                if ($_ -eq "@$ParameterFile") { "@$waveFile" } else { $_ }
            })
            $outputs = Invoke-AzureCli deployment group create @waveArguments --query 'properties.outputs' -o json | ConvertFrom-Json
            if ($LASTEXITCODE -ne 0) { throw 'Deployment wave failed.' }
            python "$PSScriptRoot\verify_revisions.py" --subscription $SubscriptionId `
                --resource-group $ResourceGroup --parameters $waveFile --timeout 600
            if ($LASTEXITCODE -ne 0) { throw 'Dependency wave has unhealthy replicas; dependent services were not deployed.' }
            $pending = @($pending | Where-Object { $_.name -notin $wave.name })
        }
    }
    finally {
        if (Test-Path -LiteralPath $waveFile) { Remove-Item -LiteralPath $waveFile }
    }
    $event = @{
        deploymentId = $parameters.parameters.deploymentId.value
        timestamp = [DateTime]::UtcNow.ToString('o')
        sourceRevision = $parameters.parameters.sourceRevision.value
        configDigest = $parameters.parameters.configDigest.value
        imageLockDigest = $parameters.parameters.imageLockDigest.value
        resourceIds = @($outputs.environmentId.value, $outputs.workspaceId.value, $outputs.insightsId.value) +
            @($parameters.parameters.apps.value.services | ForEach-Object {
                "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.App/containerApps/$($_.name)"
            })
        outcome = 'provisioned'
    }
    $event | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$ParameterFile.event.json" -Encoding utf8
    $outputs | ConvertTo-Json -Depth 5
}
