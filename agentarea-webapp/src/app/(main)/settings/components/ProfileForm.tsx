import { useTranslations } from "next-intl";
import { Mail } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import Note from "@/components/ui/note";

export default function ProfileForm(defaultValues: {
  name: string;
  email: string;
}) {
  const t = useTranslations("SettingsPage");

  return (
    <div className="space-y-8">
      {/* Profile Overview */}
      <div className="flex flex-col items-start gap-6 sm:flex-row">
        <div className="relative shrink-0">
          <Avatar className="h-20 w-20 border-2 border-gray-200 dark:border-gray-600">
            <AvatarFallback className="bg-blue-100 text-xl text-blue-700 dark:bg-blue-900 dark:text-blue-300">
              {defaultValues.name
                .split(" ")
                .map((n: string) => n[0])
                .join("")}
            </AvatarFallback>
          </Avatar>
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-xl font-semibold text-gray-900 dark:text-white">
            {defaultValues.name}
          </h3>
          <div className="mt-1 flex items-center gap-2 text-gray-600 dark:text-gray-400">
            <Mail className="h-4 w-4 shrink-0" />
            <span className="truncate text-sm">{defaultValues.email}</span>
          </div>
          <Note>{t("profile.accountInfoManaged")}</Note>
        </div>
      </div>

      {/* Account Details */}
      {/* <div className="space-y-6">
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
      </div> */}
    </div>
  );
}
