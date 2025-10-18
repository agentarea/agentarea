"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function ConsentPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [consentRequest, setConsentRequest] = useState<any>(null);
  const router = useRouter();
  const searchParams = useSearchParams();
  const consentChallenge = searchParams.get("consent_challenge");

  useEffect(() => {
    if (!consentChallenge) {
      setError("Missing consent challenge");
      setLoading(false);
      return;
    }

    // Get consent request information (server-side should use proxy or server action instead)
    // TODO: This should be moved to a server action to avoid exposing admin URL to browser
    fetch(`http://localhost:4445/admin/oauth2/auth/requests/consent?consent_challenge=${consentChallenge}`)
      .then(response => response.json())
      .then(data => {
        setConsentRequest(data);
        setLoading(false);
      })
      .catch(error => {
        setError("Failed to fetch consent request");
        setLoading(false);
      });
  }, [consentChallenge]);

  const handleAccept = async () => {
    if (!consentChallenge) return;

    setLoading(true);
    try {
      const response = await fetch(`http://localhost:4445/admin/oauth2/auth/requests/consent/accept?consent_challenge=${consentChallenge}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          grant_scope: consentRequest?.requested_scope || ['openid', 'profile', 'email'],
          grant_access_token_audience: consentRequest?.requested_access_token_audience || [],
          session: {
            id_token: {
              email: consentRequest?.subject || '',
              name: 'Ory User'
            }
          }
        }),
      });

      if (response.ok) {
        const data = await response.json();
        window.location.href = data.redirect_to;
      } else {
        setError("Failed to accept consent");
      }
    } catch (err) {
      setError("Failed to accept consent");
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!consentChallenge) return;

    setLoading(true);
    try {
      const response = await fetch(`http://localhost:4445/admin/oauth2/auth/requests/consent/reject?consent_challenge=${consentChallenge}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          error: 'access_denied',
          error_description: 'The user denied the request'
        }),
      });

      if (response.ok) {
        const data = await response.json();
        window.location.href = data.redirect_to;
      } else {
        setError("Failed to reject consent");
      }
    } catch (err) {
      setError("Failed to reject consent");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-600 via-purple-600 to-indigo-700">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full border-t-2 border-b-2 border-white h-6 w-6"></div>
          <p className="mt-2 text-sm text-white">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-600 via-purple-600 to-indigo-700">
      <Card className="w-full max-w-md p-8 bg-white/95 dark:bg-gray-800/95 shadow-2xl rounded-xl backdrop-blur-sm border border-white/20 dark:border-gray-700/20">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Authorize Application
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mt-2">
            AgentArea would like to access your account
          </p>
        </div>

        {error && (
          <div className="text-red-600 text-sm text-center mb-4">
            {error}
          </div>
        )}

        {consentRequest && (
          <div className="mb-6">
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Requested permissions:
            </h3>
            <ul className="text-sm text-gray-600 dark:text-gray-400 space-y-1">
              {consentRequest.requested_scope?.map((scope: string) => (
                <li key={scope}>• {scope}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-3">
          <Button
            onClick={handleAccept}
            className="w-full bg-blue-600 hover:bg-blue-700"
            disabled={loading}
          >
            Allow Access
          </Button>
          <Button
            onClick={handleReject}
            variant="outline"
            className="w-full"
            disabled={loading}
          >
            Deny Access
          </Button>
        </div>
      </Card>
    </div>
  );
}