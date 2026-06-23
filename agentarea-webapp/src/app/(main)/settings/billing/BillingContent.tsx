import { getBillingExperience } from "@/lib/feature-service";
import { fetchBillingOverview, fetchCloudSetupEstimate } from "./actions";
import BillingClient from "./BillingClient";

export default async function BillingContent() {
  const { data, available, error } = await fetchBillingOverview();
  const billingExperience = getBillingExperience();
  const cloudEstimate =
    billingExperience === "cloud" && !available && !error
      ? await fetchCloudSetupEstimate()
      : null;

  return (
    <BillingClient
      subscription={data?.subscription ?? null}
      usage={data?.usage ?? []}
      available={available}
      error={error}
      billingExperience={billingExperience}
      cloudEstimate={cloudEstimate}
    />
  );
}
