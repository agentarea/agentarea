"use client";

import { useEffect, useState } from "react";
import {
  Clock,
  CreditCard,
  DollarSign,
  Key,
  Network,
  Shield,
  Wallet,
} from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Badge } from "@/components/ui/badge";
import Divider from "@/components/ui/divider";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useAgentWallet,
  useCreateWallet,
  useDeleteWallet,
  useUpdateWallet,
} from "@/hooks/useAgentWallet";

const X402_NETWORKS = [
  { value: "eip155:8453", label: "Base (Mainnet)" },
  { value: "eip155:84532", label: "Base (Sepolia Testnet)" },
  { value: "eip155:1", label: "Ethereum (Mainnet)" },
  { value: "solana:mainnet", label: "Solana (Mainnet)" },
];

const BUDGET_PERIODS = [
  { value: "execution", label: "Per Execution" },
  { value: "daily", label: "Daily" },
  { value: "monthly", label: "Monthly" },
];

interface WalletFormContentProps {
  agentId: string;
}

export default function WalletFormContent({ agentId }: WalletFormContentProps) {
  const { wallet, loading, refetch } = useAgentWallet(agentId);
  const { createWallet } = useCreateWallet(agentId);
  const { updateWallet } = useUpdateWallet(agentId);
  const { deleteWallet, loading: deleting } = useDeleteWallet(agentId);

  const [walletType, setWalletType] = useState<string>("dual");
  const [network, setNetwork] = useState("eip155:8453");
  const [facilitatorUrl, setFacilitatorUrl] = useState(
    "https://x402.org/facilitator"
  );
  const [signerType, setSignerType] = useState("evm");
  const [mppPaymentMethods, setMppPaymentMethods] = useState("charge");
  const [mppSessionBudget, setMppSessionBudget] = useState("10.0");
  const [x402PrivateKey, setX402PrivateKey] = useState("");
  const [mppTempoKey, setMppTempoKey] = useState("");
  const [serviceBudget, setServiceBudget] = useState("5.0");
  const [budgetPeriod, setBudgetPeriod] = useState("execution");

  useEffect(() => {
    if (wallet) {
      setWalletType(wallet.wallet_type);
      if (wallet.x402_config) {
        setNetwork(wallet.x402_config.network || "eip155:8453");
        setFacilitatorUrl(
          wallet.x402_config.facilitator_url || "https://x402.org/facilitator"
        );
        setSignerType(wallet.x402_config.signer_type || "evm");
      }
      if (wallet.mpp_config) {
        setMppPaymentMethods(
          wallet.mpp_config.payment_method_types?.join(", ") || "charge"
        );
        setMppSessionBudget(
          String(wallet.mpp_config.session_budget_usd || 10.0)
        );
      }
      setServiceBudget(String(wallet.service_budget_usd));
      setBudgetPeriod(wallet.service_budget_period);
    }
  }, [wallet]);

  const showX402 = walletType === "x402" || walletType === "dual";
  const showMpp = walletType === "mpp" || walletType === "dual";

  const handleSave = async () => {
    const x402Config = showX402
      ? {
          network,
          facilitator_url: facilitatorUrl,
          scheme: "exact",
          signer_type: signerType,
        }
      : undefined;

    const mppConfig = showMpp
      ? {
          payment_method_types: mppPaymentMethods
            .split(",")
            .map((s) => s.trim()),
          session_budget_usd: parseFloat(mppSessionBudget),
        }
      : undefined;

    const credentials: Record<string, string> = {};
    if (x402PrivateKey) credentials.x402_private_key = x402PrivateKey;
    if (mppTempoKey) credentials.mpp_tempo_key = mppTempoKey;

    if (wallet) {
      await updateWallet({
        wallet_type: walletType,
        x402_config: x402Config,
        mpp_config: mppConfig,
        ...(Object.keys(credentials).length > 0 ? { credentials } : {}),
        service_budget_usd: parseFloat(serviceBudget),
        service_budget_period: budgetPeriod,
      });
    } else {
      await createWallet({
        wallet_type: walletType,
        x402_config: x402Config,
        mpp_config: mppConfig,
        credentials:
          Object.keys(credentials).length > 0 ? credentials : undefined,
        service_budget_usd: parseFloat(serviceBudget),
        service_budget_period: budgetPeriod,
      });
    }
    setX402PrivateKey("");
    setMppTempoKey("");
    refetch();
  };

  const handleDelete = async () => {
    await deleteWallet();
    refetch();
  };

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <form
      id="wallet-form"
      onSubmit={(e) => {
        e.preventDefault();
        handleSave();
      }}
      className="form-content mx-auto w-full max-w-2xl"
    >
      <div className="grid gap-6">
        <AnimatedTabs
          activeTab={walletType}
          onChange={setWalletType}
          size="md"
          tabs={[
            {
              value: "x402",
              label: "x402 (Crypto)",
              icon: <Wallet className="h-4 w-4" />,
            },
            {
              value: "mpp",
              label: "MPP (Fiat + Crypto)",
              icon: <CreditCard className="h-4 w-4" />,
            },
            {
              value: "dual",
              label: "Both",
              icon: <Wallet className="h-4 w-4" />,
            },
          ]}
        />

        {showX402 && (
          <div className="grid gap-4">
            <div className="flex items-center gap-2">
              <Badge variant="outline">x402</Badge>
              <span className="text-sm text-muted-foreground">
                Coinbase Protocol
              </span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <FormLabel htmlFor="x402-network" icon={Network}>
                  Network
                </FormLabel>
                <Select value={network} onValueChange={setNetwork}>
                  <SelectTrigger id="x402-network">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {X402_NETWORKS.map((n) => (
                      <SelectItem key={n.value} value={n.value}>
                        {n.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-2">
                <FormLabel htmlFor="signer-type" icon={Network}>
                  Signer Type
                </FormLabel>
                <Select value={signerType} onValueChange={setSignerType}>
                  <SelectTrigger id="signer-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="evm">EVM</SelectItem>
                    <SelectItem value="svm">SVM (Solana)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid gap-2">
              <FormLabel htmlFor="facilitator-url" icon={Network}>
                Facilitator URL
              </FormLabel>
              <Input
                id="facilitator-url"
                value={facilitatorUrl}
                onChange={(e) => setFacilitatorUrl(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <FormLabel htmlFor="x402-private-key" icon={Key}>
                Private Key
              </FormLabel>
              {wallet?.has_credentials ? (
                <div className="flex items-center gap-2">
                  <Input
                    id="x402-private-key"
                    type="password"
                    placeholder="Configured - enter new key to update"
                    value={x402PrivateKey}
                    onChange={(e) => setX402PrivateKey(e.target.value)}
                  />
                  <Shield className="h-4 w-4 text-green-500" />
                </div>
              ) : (
                <Input
                  id="x402-private-key"
                  type="password"
                  placeholder="Enter private key (hex)"
                  value={x402PrivateKey}
                  onChange={(e) => setX402PrivateKey(e.target.value)}
                />
              )}
              <p className="text-xs text-muted-foreground">
                Encrypted and stored server-side. Never transmitted in
                plaintext.
              </p>
            </div>
          </div>
        )}

        {walletType === "dual" && <Divider className="my-4" />}

        {showMpp && (
          <div className="grid gap-4">
            <div className="flex items-center gap-2">
              <Badge variant="outline">MPP</Badge>
              <span className="text-sm text-muted-foreground">
                Stripe / Tempo Protocol
              </span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <FormLabel htmlFor="payment-methods" icon={CreditCard}>
                  Payment Methods
                </FormLabel>
                <Input
                  id="payment-methods"
                  value={mppPaymentMethods}
                  onChange={(e) => setMppPaymentMethods(e.target.value)}
                  placeholder="charge"
                />
              </div>
              <div className="grid gap-2">
                <FormLabel htmlFor="session-budget" icon={DollarSign}>
                  Session Budget (USD)
                </FormLabel>
                <Input
                  id="session-budget"
                  type="number"
                  value={mppSessionBudget}
                  onChange={(e) => setMppSessionBudget(e.target.value)}
                  min="0"
                  step="0.01"
                />
              </div>
            </div>
            <div className="grid gap-2">
              <FormLabel htmlFor="tempo-key" icon={Key}>
                Tempo Account Key
              </FormLabel>
              {wallet?.has_credentials ? (
                <div className="flex items-center gap-2">
                  <Input
                    id="tempo-key"
                    type="password"
                    placeholder="Configured - enter new key to update"
                    value={mppTempoKey}
                    onChange={(e) => setMppTempoKey(e.target.value)}
                  />
                  <Shield className="h-4 w-4 text-green-500" />
                </div>
              ) : (
                <Input
                  id="tempo-key"
                  type="password"
                  placeholder="Enter Tempo account key"
                  value={mppTempoKey}
                  onChange={(e) => setMppTempoKey(e.target.value)}
                />
              )}
              <p className="text-xs text-muted-foreground">
                Encrypted and stored server-side. Never transmitted in
                plaintext.
              </p>
            </div>
          </div>
        )}

        <Divider className="my-4" />

        <div className="grid gap-4">
          <div className="gap-1 flex flex-col">
            <FormLabel icon={DollarSign}>Service Budget</FormLabel>
            <p className="text-xs text-muted-foreground">
              Maximum amount the agent can spend on paid external services per
              period.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <FormLabel htmlFor="service-budget" icon={DollarSign}>
                Budget (USD)
              </FormLabel>
              <Input
                id="service-budget"
                type="number"
                value={serviceBudget}
                onChange={(e) => setServiceBudget(e.target.value)}
                min="0"
                step="0.01"
              />
            </div>
            <div className="grid gap-2">
              <FormLabel htmlFor="budget-period" icon={Clock}>
                Period
              </FormLabel>
              <Select value={budgetPeriod} onValueChange={setBudgetPeriod}>
                <SelectTrigger id="budget-period">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BUDGET_PERIODS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </div>
      {wallet && (
        <div className="flex justify-start">
          <button
            type="button"
            className="text-sm text-destructive hover:underline"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting ? "Removing..." : "Remove Wallet"}
          </button>
        </div>
      )}
    </form>
  );
}
