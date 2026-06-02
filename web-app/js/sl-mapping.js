// sl-mapping.js — Workload -> Microsoft Defender plan mapping and scoring config.
// Faithful port of src/defender_acr_dashboard/service_attach/mapping.py.
// Exposes window.SLMapping (and module.exports under Node for tests).

(() => {
  'use strict';

  // --- Row / dimension tokens used across the SL2/SL4 export ---------------
  const DEFENDER_SL2 = 'Microsoft Defender for Cloud';
  const SENTINEL_SL2 = 'Sentinel';
  const TOTAL_TOKEN = 'Total';

  // Foundational Defender plans: environment-wide, reported in a separate panel,
  // never used to dilute per-workload gap scores.
  const FOUNDATIONAL_PLANS = [
    'Microsoft Defender CSPM',
    'Microsoft Defender for Resource Manager',
    'Microsoft Defender for DNS',
    'Defender External Attack Surface Management',
  ];

  // SL2 buckets that are not Azure first-party workloads we attach Defender to.
  // Used only for the "Azure workload ACR" context figure; never part of the
  // eligible-workload denominator.
  const NON_AZURE_SL2 = [
    'Power BI',
    'Power BI Embedded',
    'Power Apps',
    'Power Automate',
    'Power Pages',
    'Microsoft Copilot Studio',
    'Dataverse',
    'GitHub',
    'MS Bing Services',
    'Microsoft Graph Services',
    'Microsoft Graph Data Connect',
    'Syntex',
    'UNKNOWN',
    'NONE',
  ];

  // WorkloadPlan: { planLabel, workloadSl2[], defenderSl4[], confidence,
  //                 pricingDriver, eligibleForGap }
  const WORKLOAD_PLANS = [
    {
      planLabel: 'Defender for Containers',
      workloadSl2: [
        'Azure Kubernetes Service',
        'Container Instances',
        'Azure Container Apps',
        'Advanced Container Networking Services',
        'Container Registry',
      ],
      defenderSl4: [
        'Microsoft Defender for Containers',
        'Microsoft Defender for Kubernetes',
        'Microsoft Defender for Container Registries',
      ],
      confidence: 'medium',
      pricingDriver: 'Per vCPU/core of monitored container hosts',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for SQL',
      workloadSl2: ['SQL Database', 'SQL Managed Instance'],
      defenderSl4: ['Microsoft Defender for SQL'],
      confidence: 'medium',
      pricingDriver: 'Per vCore / protected database instance',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for App Service',
      workloadSl2: ['Azure App Service'],
      defenderSl4: ['Microsoft Defender for App Service'],
      confidence: 'medium',
      pricingDriver: 'Per App Service instance',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for Key Vault',
      workloadSl2: ['Key Vault'],
      defenderSl4: ['Microsoft Defender for Key Vault'],
      confidence: 'medium',
      pricingDriver: 'Per 10K Key Vault transactions',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for PostgreSQL',
      workloadSl2: ['Azure Database for PostgreSQL'],
      defenderSl4: ['Microsoft Defender for PostgreSQL'],
      confidence: 'medium',
      pricingDriver: 'Per protected server instance',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for MySQL',
      workloadSl2: ['Azure Database for MySQL'],
      defenderSl4: ['Microsoft Defender for MySQL'],
      confidence: 'medium',
      pricingDriver: 'Per protected server instance',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for Azure Cosmos DB',
      workloadSl2: ['Azure Cosmos DB'],
      defenderSl4: ['Microsoft Defender for Azure Cosmos DB'],
      confidence: 'medium',
      pricingDriver: 'Per 100 RU/s provisioned',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for APIs',
      workloadSl2: ['API Management'],
      defenderSl4: ['Defender for APIs'],
      confidence: 'medium',
      pricingDriver: 'Per API call / protected API',
      eligibleForGap: true,
    },
    {
      planLabel: 'Defender for AI Services',
      workloadSl2: ['Foundry Models', 'Foundry Tools', 'Azure Machine Learning'],
      defenderSl4: ['Microsoft Defender for AI Services'],
      confidence: 'medium',
      pricingDriver: 'Per AI resource / monitored model',
      eligibleForGap: true,
    },
    // --- Coverage-only (unit priced; no honest %-of-ACR benchmark) ---------
    {
      planLabel: 'Defender for Servers',
      workloadSl2: ['Virtual Machines'],
      defenderSl4: ['Microsoft Defender for Servers'],
      confidence: 'low',
      pricingDriver: 'Per server/node per hour (not a % of compute ACR)',
      eligibleForGap: false,
    },
    {
      planLabel: 'Defender for Storage',
      workloadSl2: ['Storage'],
      defenderSl4: ['Microsoft Defender for Storage'],
      confidence: 'low',
      pricingDriver: 'Per storage account + per million transactions',
      eligibleForGap: false,
    },
  ];

  // AttachConfig with safe defaults (matches mapping.AttachConfig).
  function defaultConfig() {
    return {
      targetRatio: 0.06,
      planTargetRatios: {},
      weightGap: 0.5,
      weightMomentum: 0.3,
      weightBreadth: 0.2,
      coverageSignalDiscount: 0.5,
      minDenominator: 100.0,
      attachThreshold: 5.0,
      useCohortMedian: true,
      cohortMinSample: 5,
      momentumWindow: 3,
      momentumCap: 1.0,
      priorityMomentumEps: 0.02,
      priorityCoverageMedium: 0.5,
    };
  }

  function ratioFor(config, planLabel) {
    if (Object.prototype.hasOwnProperty.call(config.planTargetRatios, planLabel)) {
      return config.planTargetRatios[planLabel];
    }
    return config.targetRatio;
  }

  function normalizedWeights(config) {
    const total = config.weightGap + config.weightMomentum + config.weightBreadth;
    if (total <= 0) return [0.5, 0.3, 0.2];
    return [config.weightGap / total, config.weightMomentum / total, config.weightBreadth / total];
  }

  function workloadSl2Index() {
    const index = {};
    for (const plan of WORKLOAD_PLANS) {
      for (const sl2 of plan.workloadSl2) index[sl2] = plan;
    }
    return index;
  }

  function allMappedWorkloadSl2() {
    const names = [];
    for (const plan of WORKLOAD_PLANS) names.push(...plan.workloadSl2);
    return names;
  }

  const api = {
    DEFENDER_SL2,
    SENTINEL_SL2,
    TOTAL_TOKEN,
    FOUNDATIONAL_PLANS,
    NON_AZURE_SL2,
    WORKLOAD_PLANS,
    defaultConfig,
    ratioFor,
    normalizedWeights,
    workloadSl2Index,
    allMappedWorkloadSl2,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.SLMapping = api;
})();
