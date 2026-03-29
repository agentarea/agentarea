"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Wallet, Shield, Trash2 } from "lucide-react";
import {
  useAgentWallet,
  useCreateWallet,
  useUpdateWallet,
  useDeleteWallet,
} from "@/hooks/useAgentWallet";
import { toast } from "sonner";

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

interface WalletConfigPanelProps {
  agentId: string;
}

export function WalletConfigPanel({ agentId }: WalletConfigPanelProps) {
  const { wallet, loading, refetch } = useAgentWallet(agentId);
  const { createWallet, loading: creating } = useCreateWallet(agentId);
  const { updateWallet, loading: updating } = useUpdateWallet(agentId);
  const { deleteWallet, loading: deleting } = useDeleteWallet(agentId);

  const [walletType, setWalletType] = useState<string>("dual");
  const [network, setNetwork] = useState("eip155:8453");
  const [facilitatorUrl, setFacilitatorUrl] = useState("https://x402.org/facilitator");
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
        setFacilitatorUrl(wallet.x402_config.facilitator_url || "https://x402.org/facilitator");
        setSignerType(wallet.x402_config.signer_type || "evm");
      }
      if (wallet.mpp_config) {
        setMppPaymentMethods(wallet.mpp_config.payment_method_types?.join(", ") || "charge");
        setMppSessionBudget(String(wallet.mpp_config.session_budget_usd || 10.0));
      }
      setServiceBudget(String(wallet.service_budget_usd));
      setBudgetPeriod(wallet.service_budget_period);
    }
  }, [wallet]);

  const showX402 = walletType === "x402" || walletType === "dual";
  const showMpp = walletType === "mpp" || walletType === "dual";

  const handleSave = async () => {
    try {
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
            payment_method_types: mppPaymentMethods.split(",").map((s) => s.trim()),
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
        toast.success("Wallet updated");
      } else {
        await createWallet({
          wallet_type: walletType,
          x402_config: x402Config,
          mpp_config: mppConfig,
          credentials: Object.keys(credentials).length > 0 ? credentials : undefined,
          service_budget_usd: parseFloat(serviceBudget),
          service_budget_period: budgetPeriod,
        });
        toast.success("Wallet created");
      }
      setX402PrivateKey("");
      setMppTempoKey("");
      refetch();
    } catch {
      toast.error("Failed to save wallet");
    }
  };

  const handleDelete = async () => {
    try {
      await deleteWallet();
      toast.success("Wallet removed");
      refetch();
    } catch {
      toast.error("Failed to delete wallet");
    }
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="animate-pulse space-y-4">
            <div className="h-4 bg-muted rounded w-1/3" />
            <div className="h-10 bg-muted rounded" />
            <div className="h-10 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Protocol Selection */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wallet className="h-5 w-5" />
            Wallet &amp; Payments
          </CardTitle>
          <CardDescription>
            Configure payment protocols to allow this agent to pay for external services and APIs.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Wallet Type */}
          <div className="space-y-2">
            <Label>Payment Protocol</Label>
            <Select value={walletType} onValueChange={setWalletType}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="x402">x402 (Crypto only - USDC)</SelectItem>
                <SelectItem value="mpp">MPP (Fiat + Crypto via Stripe)</SelectItem>
                <SelectItem value="dual">Both (x402 + MPP)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* x402 Configuration */}
          {showX402 && (
            <div className="space-y-4 rounded-lg border p-4">
              <div className="flex items-center gap-2">
                <Badge variant="outline">x402</Badge>
                <span className="text-sm text-muted-foreground">Coinbase Protocol</span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Network</Label>
                  <Select value={network} onValueChange={setNetwork}>
                    <SelectTrigger>
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
                <div className="space-y-2">
                  <Label>Signer Type</Label>
                  <Select value={signerType} onValueChange={setSignerType}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="evm">EVM</SelectItem>
                      <SelectItem value="svm">SVM (Solana)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Facilitator URL</Label>
                <Input value={facilitatorUrl} onChange={(e) => setFacilitatorUrl(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>Private Key</Label>
                {wallet?.has_credentials ? (
                  <div className="flex items-center gap-2">
                    <Input
                      type="password"
                      placeholder="Configured - enter new key to update"
                      value={x402PrivateKey}
                      onChange={(e) => setX402PrivateKey(e.target.value)}
                    />
                    <Shield className="h-4 w-4 text-green-500" />
                  </div>
                ) : (
                  <Input
                    type="password"
                    placeholder="Enter private key (hex)"
                    value={x402PrivateKey}
                    onChange={(e) => setX402PrivateKey(e.target.value)}
                  />
                )}
                <p className="text-xs text-muted-foreground">
                  Encrypted and stored server-side. Never transmitted in plaintext.
                </p>
              </div>
            </div>
          )}

          {/* MPP Configuration */}
          {showMpp && (
            <div className="space-y-4 rounded-lg border p-4">
              <div className="flex items-center gap-2">
                <Badge variant="outline">MPP</Badge>
                <span className="text-sm text-muted-foreground">Stripe / Tempo Protocol</span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Payment Methods</Label>
                  <Input
                    value={mppPaymentMethods}
                    onChange={(e) => setMppPaymentMethods(e.target.value)}
                    placeholder="charge"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Session Budget (USD)</Label>
                  <Input
                    type="number"
                    value={mppSessionBudget}
                    onChange={(e) => setMppSessionBudget(e.target.value)}
                    min="0"
                    step="0.01"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label>Tempo Account Key</Label>
                {wallet?.has_credentials ? (
                  <div className="flex items-center gap-2">
                    <Input
                      type="password"
                      placeholder="Configured - enter new key to update"
                      value={mppTempoKey}
                      onChange={(e) => setMppTempoKey(e.target.value)}
                    />
                    <Shield className="h-4 w-4 text-green-500" />
                  </div>
                ) : (
                  <Input
                    type="password"
                    placeholder="Enter Tempo account key"
                    value={mppTempoKey}
                    onChange={(e) => setMppTempoKey(e.target.value)}
                  />
                )}
                <p className="text-xs text-muted-foreground">
                  Encrypted and stored server-side. Never transmitted in plaintext.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Service Budget */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Service Budget</CardTitle>
          <CardDescription>
            Maximum amount the agent can spend on paid external services per period.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Budget (USD)</Label>
              <Input
                type="number"
                value={serviceBudget}
                onChange={(e) => setServiceBudget(e.target.value)}
                min="0"
                step="0.01"
              />
            </div>
            <div className="space-y-2">
              <Label>Period</Label>
              <Select value={budgetPeriod} onValueChange={setBudgetPeriod}>
                <SelectTrigger>
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
        </CardContent>
      </Card>

      {/* Actions */}
      <div className="flex justify-between">
        {wallet && (
          <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
            <Trash2 className="h-4 w-4 mr-2" />
            {deleting ? "Removing..." : "Remove Wallet"}
          </Button>
        )}
        <Button className="ml-auto" onClick={handleSave} disabled={creating || updating}>
          {creating || updating ? "Saving..." : wallet ? "Update Wallet" : "Create Wallet"}
        </Button>
      </div>
    </div>
  );
}
