import "server-only";

export type BillingExperience = "oss" | "cloud";

export type FeatureFlag = "cloudBilling";

const ENABLED_VALUES = new Set(["1", "true", "yes", "on", "enabled"]);

function readEnv(name: string): string | undefined {
  const value = process.env[name];
  return value?.trim();
}

function isEnabledValue(value: string | undefined): boolean {
  return value ? ENABLED_VALUES.has(value.toLowerCase()) : false;
}

function getDeploymentExperience(): BillingExperience {
  const explicitExperience =
    readEnv("AGENTAREA_BILLING_EXPERIENCE") ??
    readEnv("NEXT_PUBLIC_AGENTAREA_BILLING_EXPERIENCE");

  if (explicitExperience?.toLowerCase() === "cloud") {
    return "cloud";
  }

  return "oss";
}

export function isFeatureEnabled(flag: FeatureFlag): boolean {
  switch (flag) {
    case "cloudBilling":
      return (
        getDeploymentExperience() === "cloud" ||
        isEnabledValue(readEnv("AGENTAREA_CLOUD_BILLING")) ||
        isEnabledValue(readEnv("NEXT_PUBLIC_AGENTAREA_CLOUD_BILLING"))
      );
  }
}

export function getBillingExperience(): BillingExperience {
  return isFeatureEnabled("cloudBilling") ? "cloud" : "oss";
}

export const featureService = {
  isEnabled: isFeatureEnabled,
  getBillingExperience,
};
