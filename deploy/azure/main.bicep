// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param prefix string = 'astronomy-demo'
param sourceRevision string
param deploymentId string
param configDigest string
param imageLockDigest string
@secure()
param apps object

var tags = {
  application: 'astronomy-shop'
  increment: 'healthy-baseline'
  sourceRevision: sourceRevision
  deploymentId: deploymentId
  configDigest: configDigest
  imageLockDigest: imageLockDigest
  managedBy: 'astronomy-aca'
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-insights'
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: '${prefix}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

@batchSize(4)
module services 'service.bicep' = [for app in apps.services: {
  name: 'app-${app.name}'
  params: {
    location: location
    environmentId: environment.id
    environmentDomain: environment.properties.defaultDomain
    tags: tags
    app: app
    connectionString: app.name == 'telemetry-gateway' ? insights.properties.ConnectionString : ''
  }
}]

output workspaceId string = workspace.id
output workspaceCustomerId string = workspace.properties.customerId
output insightsId string = insights.id
output environmentId string = environment.id
output shopUrl string = 'https://frontend-proxy.${environment.properties.defaultDomain}'
