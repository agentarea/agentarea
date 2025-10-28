import { useTranslations } from "next-intl";
import { AnimatePresence, motion } from "framer-motion";
import { Key, Link, Settings } from "lucide-react";
import { Control, Controller, FieldErrors } from "react-hook-form";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Input } from "@/components/ui/input";
import ApiKeyEditInput from "./ApiKeyEditInput";

interface BaseInfoProps {
  control: Control<any>;
  errors: FieldErrors<any>;
  providerSpecId?: string;
  isEdit?: boolean;
}

export default function BaseInfo({
  control,
  errors,
  providerSpecId,
  isEdit,
}: BaseInfoProps) {
  const t = useTranslations("ProviderConfigForm");
  return (
    <AnimatePresence>
      {providerSpecId && (
        <motion.div
          initial={{ height: 0, opacity: 0, overflow: "hidden" }}
          animate={{ height: "auto", opacity: 1, overflow: "visible" }}
          exit={{ height: 0, opacity: 0, overflow: "hidden" }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="form-content"
        >
          <div className="space-y-2">
            <FormLabel htmlFor="name" icon={Settings} required>
              {t("configurationName")}
            </FormLabel>
            <Controller
              name="name"
              control={control}
              render={({ field }) => (
                <Input
                  id="name"
                  type="text"
                  value={field.value}
                  onChange={field.onChange}
                  placeholder={t("configurationNamePlaceholder")}
                />
              )}
            />
            {errors.name && (
              <p className="text-sm text-red-600">
                {String(errors.name.message)}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <FormLabel htmlFor="api_key" required icon={Key}>
              {t("apiKey")}
            </FormLabel>
            <Controller
              name="api_key"
              control={control}
              render={({ field }) =>
                isEdit ? (
                  <ApiKeyEditInput field={field} />
                ) : (
                  <Input
                    id="api_key"
                    type="password"
                    value={field.value}
                    onChange={field.onChange}
                    placeholder={t("apiKeyPlaceholder")}
                  />
                )
              }
            />
            {errors.api_key && (
              <p className="text-sm text-red-600">
                {String(errors.api_key.message)}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <FormLabel htmlFor="endpoint_url" icon={Link} optional>
              {t("customEndpointUrl")}
            </FormLabel>
            <Controller
              name="endpoint_url"
              control={control}
              render={({ field }) => (
                <Input
                  id="endpoint_url"
                  type="url"
                  value={field.value || ""}
                  onChange={field.onChange}
                  placeholder={t("customEndpointUrlPlaceholder")}
                />
              )}
            />
            {errors.endpoint_url && (
              <p className="text-sm text-red-600">
                {String(errors.endpoint_url.message)}
              </p>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
