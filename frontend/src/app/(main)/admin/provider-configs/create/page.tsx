import ContentBlock from '@/components/ContentBlock/ContentBlock';
import { getTranslations } from 'next-intl/server';
import { Suspense } from 'react';
import { LoadingSpinner } from '@/components/LoadingSpinner';
import ProviderConfigFormWrapper from './components/ProviderConfigFormWrapper';

export default async function CreateProviderConfigPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const resolvedSearchParams = await searchParams;
  const t = await getTranslations("Models");  
  const tCommon = await getTranslations("Common");  
  
  // Get the provider_spec_id from query params if provided
  const preselectedProviderId = typeof resolvedSearchParams.provider_spec_id === 'string' 
    ? resolvedSearchParams.provider_spec_id 
    : undefined;

  // Check if this is edit mode
  const isEdit = resolvedSearchParams.isEdit === 'true';

  return (
    <ContentBlock 
      header={{
        breadcrumb: isEdit ? [
          {label: t("title"), href: "/admin/provider-configs"},
          {label: tCommon("edit")},
        ] : [
          {label: t("title"), href: "/admin/provider-configs"},
          {label: tCommon("create")},
          {label:  t("configureProvider")}
        ],
    }}>
      <Suspense
        key={`${preselectedProviderId}-${isEdit}`}
        fallback={
          <div className="flex items-center justify-center h-32">
            <LoadingSpinner />
          </div>
        }
      >
        <ProviderConfigFormWrapper 
          preselectedProviderId={preselectedProviderId}
          isEdit={isEdit}
        />
      </Suspense>
  </ContentBlock>
  );
} 