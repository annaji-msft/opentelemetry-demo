// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

param location string
param environmentId string
param environmentDomain string
param tags object
@secure()
param app object
@secure()
param connectionString string

var configuredSecrets = [for secret in app.secrets: {
  name: secret.name
  value: secret.resolveDomain ? replace(secret.value, '__ACA_DOMAIN__', environmentDomain) : secret.value
}]

resource containerApp 'Microsoft.App/containerApps@2025-07-01' = {
  name: app.name
  location: location
  tags: tags
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: app.ingress
      secrets: concat(configuredSecrets, empty(connectionString) ? [] : [
        { name: 'app-insights', value: connectionString }
      ])
    }
    template: json(replace(string(app.template), '__ACA_DOMAIN__', environmentDomain))
  }
}
