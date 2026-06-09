import { fetchBillingOverview } from "./actions";
import BillingClient from "./BillingClient";

export default async function BillingContent() {
  const { data, available, error } = await fetchBillingOverview();

  return (
    <BillingClient
      subscription={data?.subscription ?? null}
      usage={data?.usage ?? []}
      available={available}
      error={error}
    />
  );
}
