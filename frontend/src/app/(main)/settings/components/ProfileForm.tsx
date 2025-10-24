import { useTranslations } from "next-intl";
import { ExternalLink, Mail, Shield, User as UserIcon } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function ProfileForm(defaultValues: {
  name: string;
  email: string;
  avatar: string;
}) {
  const t = useTranslations("SettingsPage");

  const handleManageAccount = () => {
    // This would typically open the authentication provider's user profile management
    // For Ory, this could be a custom profile page or Ory Account Experience
    alert(
      "Profile management through authentication provider not yet implemented"
    );
  };

  return (
    <div className="space-y-8">
      {/* Profile Overview */}
      <div className="flex flex-col items-start gap-6 sm:flex-row">
        <div className="relative shrink-0">
          <Avatar className="h-20 w-20 border-2 border-gray-200 dark:border-gray-600">
            <AvatarImage src={defaultValues.avatar} />
            <AvatarFallback className="bg-blue-100 text-xl text-blue-700 dark:bg-blue-900 dark:text-blue-300">
              {defaultValues.name
                .split(" ")
                .map((n: string) => n[0])
                .join("")}
            </AvatarFallback>
          </Avatar>
          <Badge
            variant="secondary"
            className="absolute -bottom-1 -right-1 border-0 bg-green-100 text-xs text-green-700 dark:bg-green-900/50 dark:text-green-400"
          >
            <Shield className="mr-1 h-3 w-3" />
            Verified
          </Badge>
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-xl font-semibold text-gray-900 dark:text-white">
            {defaultValues.name}
          </h3>
          <div className="mt-1 flex items-center gap-2 text-gray-600 dark:text-gray-400">
            <Mail className="h-4 w-4 shrink-0" />
            <span className="truncate text-sm">{defaultValues.email}</span>
          </div>
          <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500 dark:bg-gray-800/50 dark:text-gray-500">
            Account information is managed by your authentication provider and
            cannot be edited here.
          </p>
        </div>
      </div>

      {/* Account Details */}
      <div className="space-y-6">
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <Label className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Display Name
            </Label>
            <div className="relative">
              <Input
                value={defaultValues.name}
                disabled
                className="cursor-not-allowed border-gray-200 bg-gray-50 text-gray-500 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-400"
              />
              <div className="absolute inset-y-0 right-0 flex items-center pr-3">
                <Shield className="h-4 w-4 text-gray-400" />
              </div>
            </div>
          </div>
          <div className="space-y-2">
            <Label className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Email Address
            </Label>
            <div className="relative">
              <Input
                value={defaultValues.email}
                disabled
                className="cursor-not-allowed border-gray-200 bg-gray-50 text-gray-500 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-400"
              />
              <div className="absolute inset-y-0 right-0 flex items-center pr-3">
                <Shield className="h-4 w-4 text-gray-400" />
              </div>
            </div>
          </div>
        </div>

        {/* Action Section */}
        <div className="flex flex-col gap-4 border-t border-gray-200 pt-6 dark:border-gray-700 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex-1">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Need to update your profile information?
            </p>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
              Use your authentication provider&#39;s profile management to make
              changes.
            </p>
          </div>
          <Button
            onClick={handleManageAccount}
            variant="outline"
            className="shrink-0 gap-2"
          >
            <ExternalLink className="h-4 w-4" />
            Manage Account
          </Button>
        </div>
      </div>
    </div>
  );
}
